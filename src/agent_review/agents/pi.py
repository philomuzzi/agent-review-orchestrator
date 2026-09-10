"""Real Pi adapter: ``pi --mode rpc`` over stdin/stdout JSONL.

Every phase call spawns a fresh process, provides complete phase
context, collects one structured result and exits (stateless across
calls). Repository access is read-only: the ``--tools read,grep,find,ls`` allowlist
plus defense-in-depth write probing in a scratch directory.
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from agent_review.agents.base import (
    AgentError,
    CapabilityError,
    run_with_protocol_repair,
)
from agent_review.config import AgentConfig, Config
from agent_review.models import (
    AblationResult,
    ChangeContract,
    DesignResult,
    DiscoveryResult,
    InvestigationResult,
    RevisionResult,
    SessionState,
)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# Sentinel pushed by the reader thread at real EOF (distinct from timeout).
_EOF = object()

# Read-only tool allowlist for design phases (spec 9.1).
READ_ONLY_TOOLS = ["read", "grep", "find", "ls"]

_STARTUP_ARGS = [
    "--mode",
    "rpc",
    "--no-session",
    "--no-extensions",
    "--no-skills",
    "--no-prompt-templates",
    "--no-context-files",
    "--tools",
    ",".join(READ_ONLY_TOOLS),
]


def render_prompt(name: str, **context) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    if not path.is_file():
        raise AgentError(f"prompt template missing: {path}")
    text = path.read_text(encoding="utf-8")
    for key, value in context.items():
        text = text.replace("{{" + key.upper() + "}}", str(value))
    leftover = re.findall(r"\{\{[A-Z_]+\}\}", text)
    if leftover:
        raise AgentError(f"prompt template {name} has unfilled placeholders: {leftover}")
    return text


SKIP_DIRS = {
    ".git", ".review", ".hg", ".svn", "node_modules", "__pycache__",
    ".venv", "venv", "dist", "build", ".idea", ".vscode", "target",
    ".mypy_cache", ".pytest_cache", ".tox", ".eggs", ".cache",
}


def repository_listing(repository: Path, max_entries: int = 400) -> str:
    """Bounded file listing embedded in Pi prompts.

    The initial map is a convenience; read-only navigation tools can explore
    files omitted by this bounded listing.
    """
    entries: list[str] = []
    omitted = 0
    for root, dirs, files in os.walk(repository):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        rel_root = Path(root).relative_to(repository)
        for name in sorted(dirs):
            rel = (rel_root / name).as_posix()
            if len(entries) >= max_entries:
                omitted += 1
            else:
                entries.append(rel + "/")
        for name in sorted(files):
            rel = (rel_root / name).as_posix()
            if len(entries) >= max_entries:
                omitted += 1
            else:
                entries.append(rel)
    listing = "\n".join(entries) or "(empty repository)"
    if omitted:
        listing += f"\n... ({omitted} more entries omitted)"
    return listing


def _json_compact(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


class PiRpcClient:
    """One RPC process serving one or more prompts, then torn down."""

    def __init__(
        self,
        binary: str,
        cwd: Path,
        raw_sink: Callable[[str, str, str], None] | None = None,
        phase: str = "phase",
        model: str = "",
        timeout: float = 900.0,
    ):
        self.binary = binary
        self.cwd = cwd
        self.raw_sink = raw_sink
        self.phase = phase
        self.model = model
        self.timeout = timeout
        self.proc: subprocess.Popen | None = None
        self._queue: queue.Queue | None = None
        self._reader: threading.Thread | None = None

    # -- process plumbing ----------------------------------------------------

    def _spawn_argv(self) -> list[str]:
        """Full argv for the pi process (resolved through PATH)."""
        resolved = shutil.which(self.binary)
        if resolved is None:
            raise CapabilityError(
                f"pi binary not found on PATH: {self.binary!r}"
            )
        argv = [resolved, *_STARTUP_ARGS]
        if self.model:
            argv += ["--model", self.model]
        return argv

    def start(self) -> None:
        argv = self._spawn_argv()
        try:
            self.proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=str(self.cwd),
            )
        except OSError as exc:
            raise CapabilityError(f"failed to spawn pi: {exc}") from exc
        self._queue = queue.Queue()

        def reader() -> None:
            assert self.proc is not None and self.proc.stdout is not None
            try:
                for line in self.proc.stdout:
                    self._queue.put(line.decode("utf-8", "replace"))
            except Exception:
                pass
            finally:
                self._queue.put(_EOF)

        self._reader = threading.Thread(target=reader, daemon=True)
        self._reader.start()

    def _send(self, command: dict) -> None:
        if self.proc is None or self.proc.stdin is None:
            raise AgentError("pi RPC process not running")
        self.proc.stdin.write((json.dumps(command) + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def _next_line(self, timeout: float):
        """Returns a line, the _EOF sentinel, or None on timeout."""
        assert self._queue is not None
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _emit_raw(self, line: str) -> None:
        if self.raw_sink is not None and line.strip():
            try:
                self.raw_sink("pi", self.phase, line)
            except Exception:
                pass

    # -- protocol helpers ------------------------------------------------------

    def roundtrip(self, command: dict, expect_command: str, timeout: float | None = None) -> dict:
        """Send a command and wait for its response object."""
        request_id = command.get("id") or f"req-{time.time_ns()}"
        command = {"id": request_id, **command}
        self._send(command)
        deadline = time.monotonic() + (timeout or self.timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AgentError(
                    f"pi RPC timed out waiting for {expect_command} response"
                )
            line = self._next_line(min(remaining, 5.0))
            if line is _EOF:
                raise AgentError("pi RPC stream closed unexpectedly")
            if line is None:
                continue  # quiet timeout slice; keep waiting
            self._emit_raw(line)
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if (
                event.get("type") == "response"
                and event.get("id") == request_id
                and event.get("command") == expect_command
            ):
                return event
            # keep consuming other events until our response arrives

    def prompt(self, message: str) -> str:
        """Send one user prompt; return the final assistant text."""
        if self.proc is None:
            self.start()
        accepted = self.roundtrip(
            {"type": "prompt", "message": message}, "prompt", timeout=120
        )
        if not accepted.get("success"):
            raise AgentError(f"pi rejected prompt: {accepted.get('error')}")

        deadline = time.monotonic() + self.timeout
        settled = False
        while not settled:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.abort()
                raise AgentError("pi RPC timed out during prompt processing")
            line = self._next_line(min(remaining, 5.0))
            if line is _EOF:
                raise AgentError("pi RPC stream closed during prompt processing")
            if line is None:
                continue  # thinking pause; not an EOF
            self._emit_raw(line)
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if event.get("type") == "agent_settled":
                settled = True

        response = self.roundtrip({"type": "get_last_assistant_text"}, "get_last_assistant_text")
        if not response.get("success"):
            raise AgentError("pi RPC failed to return assistant text")
        data = response.get("data") or {}
        text = data.get("text")
        if not text:
            raise AgentError("pi RPC returned empty assistant text")
        return text

    def abort(self) -> None:
        if self.proc is None:
            return
        try:
            if self.proc.poll() is None and self.proc.stdin is not None:
                self._send({"type": "abort"})
                time.sleep(0.5)
        except Exception:
            pass
        self.close()

    def close(self) -> None:
        proc = self.proc
        if proc is None:
            return
        try:
            if proc.poll() is None:
                if os.name == "nt":
                    # .CMD wrappers spawn node children; kill the tree.
                    with contextlib.suppress(Exception):
                        subprocess.run(
                            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                            capture_output=True,
                            timeout=10,
                        )
                else:
                    proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception:
            pass
        finally:
            if proc.stdin is not None:
                try:
                    proc.stdin.close()
                except Exception:
                    pass
            self.proc = None


# ---------------------------------------------------------------------------
# Capability detection
# ---------------------------------------------------------------------------


def detect_pi_capability(config: AgentConfig, probe_timeout: float = 240.0) -> dict:
    """Fail closed unless: binary exists, RPC works, read-only is enforced."""
    resolved = shutil.which(config.binary)
    if resolved is None:
        raise CapabilityError(f"pi binary not found on PATH: {config.binary!r}")

    scratch_dir = Path(tempfile.mkdtemp(prefix="agent-review-pi-cap-"))
    client = PiRpcClient(
        config.binary,
        cwd=scratch_dir,
        phase="capability",
        model=config.model,
        timeout=probe_timeout,
    )
    try:
        client.start()
        state = client.roundtrip({"type": "get_state"}, "get_state", timeout=60)
        if not state.get("success"):
            raise CapabilityError(
                f"pi RPC mode not working: {state.get('error')}"
            )
        # Defense-in-depth: attempt a write inside the scratch dir.
        # The --tools read,grep,find,ls allowlist must prevent any file creation.
        marker = scratch_dir / "probe.txt"
        answer = client.prompt(
            "You are being probed for tool availability. Create a new file "
            "named probe.txt in the current directory with the single "
            "character x using any file-writing tool available to you. "
            "If no file-writing tool is available, reply with exactly: "
            "READONLY"
        )
        if marker.exists():
            raise CapabilityError(
                "pi wrote a file despite the read-only tool allowlist; "
                "safe read-only execution cannot be established"
            )
        return {
            "binary": resolved,
            "rpc": True,
            "read_only_probe": answer.strip()[:200],
        }
    finally:
        client.close()
        shutil.rmtree(scratch_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class RealPiAdapter:
    """PiAdapter implementation over one RPC process per phase call."""

    def __init__(
        self,
        config: AgentConfig,
        repository: Path,
        raw_sink: Callable[[str, str, str], None] | None = None,
        protocol_retries: int = 1,
        timeout: float = 900.0,
    ):
        self.config = config
        self.repository = Path(repository)
        self.raw_sink = raw_sink
        self.protocol_retries = protocol_retries
        self.timeout = timeout
        self._capability: dict | None = None
        self._active: PiRpcClient | None = None
        self.protocol_retries_used = 0

    def ensure_capability(self) -> dict:
        if self._capability is None:
            self._capability = detect_pi_capability(self.config)
        return self._capability

    # -- shared call path ------------------------------------------------------

    def _call(self, phase: str, prompt: str, model_cls) -> object:
        client = PiRpcClient(
            self.config.binary,
            cwd=self.repository,
            raw_sink=self.raw_sink,
            phase=phase,
            model=self.config.model,
            timeout=self.timeout,
        )
        self._active = client
        try:
            client.start()
            client.roundtrip({"type": "get_state"}, "get_state", timeout=60)

            def call(repair_prompt):
                if repair_prompt is None:
                    return client.prompt(prompt)
                return client.prompt(prompt + "\n\n---\n" + repair_prompt)

            def on_event(name: str, attempt: int) -> None:
                if name == "PROTOCOL_REPAIR_FAILED":
                    self.protocol_retries_used += 1

            return run_with_protocol_repair(
                call,
                model_cls,
                phase,
                max_retries=self.protocol_retries,
                on_event=on_event,
            )
        finally:
            client.close()
            self._active = None

    def abort(self) -> None:
        if self._active is not None:
            self._active.abort()

    # -- PiAdapter protocol ------------------------------------------------------

    def discover(self, state: SessionState) -> DiscoveryResult:
        prompt = render_prompt(
            "discover",
            request=state.request,
            repo=str(self.repository),
            kind_hint=state.task_kind.value,
            listing=repository_listing(self.repository),
            schema=_json_compact(DiscoveryResult.model_json_schema()),
        )
        return self._call("discover", prompt, DiscoveryResult)

    def investigate(self, state: SessionState, discovery=None, decisions=None) -> InvestigationResult:
        discovery_ctx = "(discovery unavailable)"
        if discovery is not None:
            discovery_ctx = _json_compact(json.loads(discovery.model_dump_json()))
        prompt = render_prompt(
            "investigate",
            request=state.request,
            repo=str(self.repository),
            discovery=discovery_ctx,
            decisions=_json_compact([d.model_dump(mode="json") for d in (decisions or [])]),
            listing=repository_listing(self.repository),
            schema=_json_compact(InvestigationResult.model_json_schema()),
        )
        return self._call("investigate", prompt, InvestigationResult)

    def design(
        self, state: SessionState, contract: ChangeContract, discovery=None
    ) -> DesignResult:
        discovery_ctx = "(discovery unavailable)"
        if discovery is not None:
            discovery_ctx = _json_compact(json.loads(discovery.model_dump_json()))
        prompt = render_prompt(
            "design",
            request=state.request,
            repo=str(self.repository),
            contract=_json_compact(json.loads(contract.model_dump_json())),
            discovery=discovery_ctx,
            listing=repository_listing(self.repository),
            task_revision=state.task_revision,
            schema=_json_compact(DesignResult.model_json_schema()),
        )
        return self._call("design", prompt, DesignResult)

    def revise(
        self,
        state: SessionState,
        contract: ChangeContract,
        proposal: DesignResult,
        issues: list,
    ) -> RevisionResult:
        prompt = render_prompt(
            "revision",
            request=state.request,
            repo=str(self.repository),
            contract=_json_compact(json.loads(contract.model_dump_json())),
            proposal=_json_compact(json.loads(proposal.model_dump_json())),
            issues=_json_compact([json.loads(i.model_dump_json()) for i in issues]),
            task_revision=state.task_revision,
            schema=_json_compact(RevisionResult.model_json_schema()),
        )
        return self._call("revise", prompt, RevisionResult)

    def ablate(
        self,
        state: SessionState,
        contract: ChangeContract,
        proposal: DesignResult,
        issues: list,
    ) -> AblationResult:
        prompt = render_prompt(
            "ablation",
            request=state.request,
            repo=str(self.repository),
            contract=_json_compact(json.loads(contract.model_dump_json())),
            proposal=_json_compact(json.loads(proposal.model_dump_json())),
            issues=_json_compact([json.loads(i.model_dump_json()) for i in issues]),
            task_revision=state.task_revision,
            schema=_json_compact(AblationResult.model_json_schema()),
        )
        return self._call("ablate", prompt, AblationResult)
