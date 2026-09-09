"""Real Codex adapter: non-interactive ``codex exec`` with structured output.

Reviewer safety: ``-s read-only`` sandbox plus defense-in-depth write
probing in a scratch directory. If safe read-only reviewer execution
cannot be established, capability detection fails closed.
"""

from __future__ import annotations

import json
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
from agent_review.agents.pi import render_prompt
from agent_review.config import AgentConfig
from agent_review.models import (
    ChangeContract,
    ClosureReviewResult,
    DesignResult,
    FinalReviewResult,
    InitialReviewResult,
    Issue,
    SessionState,
)


def _json_compact(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def strict_output_schema(model_cls) -> dict:
    """Convert a Pydantic JSON schema to codex --output-schema (strict) form.

    Structured-output mode requires ``additionalProperties: false`` and a
    complete ``required`` list on every object; ``default`` is unsupported.
    """
    import copy

    def walk(node):
        if isinstance(node, list):
            return [walk(item) for item in node]
        if not isinstance(node, dict):
            return node
        node = {key: walk(value) for key, value in node.items()}
        node.pop("default", None)
        if node.get("type") == "object":
            node["additionalProperties"] = False
            properties = node.get("properties")
            if isinstance(properties, dict):
                node["required"] = list(properties.keys())
        return node

    return walk(copy.deepcopy(model_cls.model_json_schema()))


def _kill_tree(proc: subprocess.Popen) -> None:
    import os

    try:
        if proc.poll() is None:
            if os.name == "nt":
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


class CodexExecRunner:
    """One ``codex exec`` invocation."""

    active_proc: subprocess.Popen | None = None  # last spawned process (abort path)

    def __init__(
        self,
        binary: str,
        repository: Path,
        phase: str,
        raw_sink: Callable[[str, str, str], None] | None = None,
        model: str = "",
        timeout: float = 900.0,
        extra_args: list[str] | None = None,
    ):
        self.binary = binary
        self.repository = repository
        self.phase = phase
        self.raw_sink = raw_sink
        self.model = model
        self.timeout = timeout
        self.extra_args = extra_args or []

    def run(self, prompt: str, schema: dict | None = None) -> str:
        resolved = shutil.which(self.binary)
        if resolved is None:
            raise CapabilityError(f"codex binary not found on PATH: {self.binary!r}")

        tmp = Path(tempfile.mkdtemp(prefix="agent-review-codex-"))
        try:
            argv = [
                resolved,
                "exec",
                "-s",
                "read-only",  # reviewer reads the repository, never mutates
                "--ephemeral",
                "--skip-git-repo-check",
                "-C",
                str(self.repository),
                "--json",
                "-o",
                str(tmp / "last.txt"),
            ]
            if self.model:
                argv += ["-m", self.model]
            argv += self.extra_args
            if schema is not None:
                schema_file = tmp / "schema.json"
                schema_file.write_text(
                    json.dumps(schema, ensure_ascii=False), encoding="utf-8"
                )
                argv += ["--output-schema", str(schema_file)]
            # Prompts are read from stdin via `-`: avoids command-line
            # length limits and shell quoting entirely.
            argv.append("-")

            try:
                proc = subprocess.Popen(
                    argv,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=str(self.repository),
                )
            except OSError as exc:
                raise CapabilityError(f"failed to spawn codex: {exc}") from exc
            CodexExecRunner.active_proc = proc

            try:
                stdout, stderr = proc.communicate(
                    input=prompt.encode("utf-8"), timeout=self.timeout
                )
            except subprocess.TimeoutExpired:
                _kill_tree(proc)
                raise AgentError(f"codex exec timed out in phase {self.phase}")
            except BaseException:
                # Ctrl+C or other interruption: kill the child before bubbling.
                _kill_tree(proc)
                raise
            finally:
                CodexExecRunner.active_proc = None

            if self.raw_sink is not None and stdout:
                for line in stdout.decode("utf-8", "replace").splitlines():
                    if line.strip():
                        try:
                            self.raw_sink("codex", self.phase, line)
                        except Exception:
                            pass

            if proc.returncode != 0:
                tail = stderr.decode("utf-8", "replace")[-500:]
                raise AgentError(
                    f"codex exec failed (rc={proc.returncode}) in phase "
                    f"{self.phase}: {tail}"
                )

            last = tmp / "last.txt"
            if not last.is_file():
                raise AgentError(
                    f"codex exec produced no final message in phase {self.phase}"
                )
            text = last.read_text(encoding="utf-8").strip()
            if not text:
                raise AgentError(
                    f"codex exec final message empty in phase {self.phase}"
                )
            return text
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Capability detection
# ---------------------------------------------------------------------------


def detect_codex_capability(config: AgentConfig, probe_timeout: float = 300.0) -> dict:
    """Fail closed unless: binary exists, non-interactive exec works,
    output is deterministic, and read-only is enforced."""
    resolved = shutil.which(config.binary)
    if resolved is None:
        raise CapabilityError(f"codex binary not found on PATH: {config.binary!r}")

    scratch_dir = Path(tempfile.mkdtemp(prefix="agent-review-codex-cap-"))
    try:
        (scratch_dir / "README.md").write_text("# probe\n", encoding="utf-8")
        runner = CodexExecRunner(
            config.binary,
            repository=scratch_dir,
            phase="capability",
            model=config.model,
            timeout=probe_timeout,
        )

        # 1. Non-interactive execution works and output is deterministic.
        answer = runner.run(
            "Reply with exactly the single word: OK", schema=None
        )
        if "OK" not in answer:
            raise CapabilityError(
                f"codex exec output not deterministic: {answer[:200]!r}"
            )

        # 2. Read-only enforcement: writing must fail inside the sandbox.
        marker = scratch_dir / "probe.txt"
        runner.run(
            "Create a new file named probe.txt in the current directory with "
            "the single character x using shell. If the sandbox prevents it, "
            "reply with exactly: READONLY"
        )
        if marker.exists():
            raise CapabilityError(
                "codex wrote a file despite the read-only sandbox; safe "
                "read-only reviewer execution cannot be established"
            )
        return {"binary": resolved, "exec": True, "read_only_probe": True}
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class RealCodexAdapter:
    """CodexAdapter implementation over one codex exec per phase call."""

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
        self._active: CodexExecRunner | None = None
        self.protocol_retries_used = 0

    def ensure_capability(self) -> dict:
        if self._capability is None:
            self._capability = detect_codex_capability(self.config)
        return self._capability

    def _runner(self, phase: str) -> CodexExecRunner:
        runner = CodexExecRunner(
            self.config.binary,
            repository=self.repository,
            phase=phase,
            raw_sink=self.raw_sink,
            model=self.config.model,
            timeout=self.timeout,
        )
        self._active = runner
        return runner

    def _call(self, phase: str, prompt: str, model_cls):
        runner = self._runner(phase)
        schema = strict_output_schema(model_cls)

        def call(repair_prompt):
            if repair_prompt is None:
                return runner.run(prompt, schema=schema)
            return runner.run(prompt + "\n\n---\n" + repair_prompt, schema=schema)

        def on_event(name: str, attempt: int) -> None:
            if name == "PROTOCOL_REPAIR_FAILED":
                self.protocol_retries_used += 1

        try:
            return run_with_protocol_repair(
                call,
                model_cls,
                phase,
                max_retries=self.protocol_retries,
                on_event=on_event,
            )
        finally:
            self._active = None

    def abort(self) -> None:
        proc = CodexExecRunner.active_proc
        if proc is not None:
            _kill_tree(proc)
            CodexExecRunner.active_proc = None

    # -- CodexAdapter protocol ------------------------------------------------

    def initial_review(
        self, state: SessionState, contract: ChangeContract, proposal: DesignResult
    ) -> InitialReviewResult:
        prompt = render_prompt(
            "initial_review",
            request=state.request,
            repo=str(self.repository),
            contract=_json_compact(json.loads(contract.model_dump_json())),
            proposal=_json_compact(json.loads(proposal.model_dump_json())),
            task_revision=state.task_revision,
            schema=_json_compact(InitialReviewResult.model_json_schema()),
        )
        return self._call("initial_review", prompt, InitialReviewResult)

    def closure_review(
        self,
        state: SessionState,
        contract: ChangeContract,
        proposal: DesignResult,
        issues: list[Issue],
    ) -> ClosureReviewResult:
        prompt = render_prompt(
            "closure_review",
            request=state.request,
            repo=str(self.repository),
            contract=_json_compact(json.loads(contract.model_dump_json())),
            proposal=_json_compact(json.loads(proposal.model_dump_json())),
            issues=_json_compact([json.loads(i.model_dump_json()) for i in issues]),
            task_revision=state.task_revision,
            schema=_json_compact(ClosureReviewResult.model_json_schema()),
        )
        return self._call("closure_review", prompt, ClosureReviewResult)

    def final_review(
        self,
        state: SessionState,
        contract: ChangeContract,
        proposal: DesignResult,
        issues: list[Issue],
    ) -> FinalReviewResult:
        prompt = render_prompt(
            "final_review",
            request=state.request,
            repo=str(self.repository),
            contract=_json_compact(json.loads(contract.model_dump_json())),
            proposal=_json_compact(json.loads(proposal.model_dump_json())),
            issues=_json_compact([json.loads(i.model_dump_json()) for i in issues]),
            task_revision=state.task_revision,
            schema=_json_compact(FinalReviewResult.model_json_schema()),
        )
        return self._call("final_review", prompt, FinalReviewResult)
