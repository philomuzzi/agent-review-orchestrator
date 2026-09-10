"""Session persistence: the StateStore owns ``<repo>/.review/<session-id>/``.

Only the orchestrator writes to ``.review/``. Every write is atomic
(tmp file + ``os.replace``) so an interrupted run never corrupts a
previously completed phase boundary.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_review.models import (
    ChangeContract,
    DecisionLog,
    DesignResult,
    DiscoveryResult,
    GateLog,
    InvestigationResult,
    IssueLog,
    SessionState,
)

REVIEW_DIRNAME = ".review"


def review_root(repo: Path | str) -> Path:
    return Path(repo) / REVIEW_DIRNAME


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _write_json(path: Path, payload: Any) -> None:
    _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _read_json(path: Path) -> Any | None:
    if not path.is_file():
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def slugify(text: str, max_len: int = 24) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:max_len].strip("-") or "session"


def new_session_id(request: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{slugify(request)}"


class StateStore:
    """Read/write access to one session directory."""

    def __init__(self, repository: Path | str, session_id: str):
        self.repository = Path(repository).resolve()
        self.session_id = session_id
        self.dir = review_root(self.repository) / session_id
        self.raw_dir = self.dir / "raw"
        self.history_dir = self.dir / "history"

    # -- lifecycle ---------------------------------------------------------

    @staticmethod
    def create_session(
        repository: Path | str,
        request: str,
        task_kind_explicit: str | None = None,
        limits=None,
    ) -> "StateStore":
        """Create a fresh session directory with input.md and state.json."""
        repo = Path(repository).resolve()
        root = review_root(repo)
        base = new_session_id(request)
        session_id = base
        n = 1
        while (root / session_id).exists():
            n += 1
            session_id = f"{base}-{n}"

        store = StateStore(repo, session_id)
        store.dir.mkdir(parents=True, exist_ok=True)
        store.raw_dir.mkdir(exist_ok=True)
        store.history_dir.mkdir(exist_ok=True)

        from agent_review.models import (  # noqa: PLC0415
            BudgetLimits,
            Phase,
            SessionStatus,
            TaskKind,
        )

        kind = TaskKind(task_kind_explicit.upper()) if task_kind_explicit else TaskKind.CHANGE
        state = SessionState(
            session_id=session_id,
            repository=str(repo),
            request=request,
            task_kind=kind,
            kind_explicit=task_kind_explicit is not None,
            phase=Phase.INIT,
            status=SessionStatus.RUNNING,
            limits=limits or BudgetLimits(),
        )
        store.save_state(state)
        store.write_text("input.md", f"# Review Request\n\n{request}\n")
        store.append_event({"event": "SESSION_CREATED", "session_id": session_id})
        return store

    # -- state -------------------------------------------------------------

    def begin_phase(self) -> None:
        """Durable undo checkpoint; audit/raw/history are not recovery truth."""
        files = {
            p.name: p.read_text(encoding="utf-8")
            for p in self.dir.iterdir()
            if p.is_file() and p.suffix in (".json", ".md")
            and p.name != "phase-checkpoint.json"
        }
        _write_json(self.dir / "phase-checkpoint.json", files)

    def commit_phase(self) -> None:
        (self.dir / "phase-checkpoint.json").unlink(missing_ok=True)

    def recover_phase(self) -> bool:
        checkpoint = _read_json(self.dir / "phase-checkpoint.json")
        if checkpoint is None:
            return False
        if (not isinstance(checkpoint, dict) or "state.json" not in checkpoint
                or any(not isinstance(name, str) or Path(name).name != name
                       or "/" in name or "\\" in name
                       or name == "phase-checkpoint.json"
                       or not isinstance(data, str)
                       for name, data in checkpoint.items())):
            raise ValueError("invalid phase checkpoint")
        SessionState.model_validate_json(checkpoint["state.json"])
        # Restore state last. Keep the checkpoint until restoration completes,
        # so a second crash during recovery is itself recoverable.
        for name, data in checkpoint.items():
            if name != "state.json":
                _atomic_write(self.dir / name, data)
        for path in self.dir.iterdir():
            if (path.is_file() and path.suffix in (".json", ".md")
                    and path.name != "phase-checkpoint.json"
                    and path.name not in checkpoint):
                path.unlink()
        _atomic_write(self.dir / "state.json", checkpoint["state.json"])
        self.commit_phase()
        return True

    def save_state(self, state: SessionState) -> None:
        state.updated_at = datetime.now(timezone.utc)
        _write_json(self.dir / "state.json", json.loads(state.model_dump_json()))

    def load_state(self) -> SessionState | None:
        data = _read_json(self.dir / "state.json")
        if data is None:
            return None
        return SessionState.model_validate(data)

    # -- phase artifacts ----------------------------------------------------

    def write_text(self, name: str, text: str) -> None:
        _atomic_write(self.dir / name, text)

    def read_text(self, name: str) -> str | None:
        path = self.dir / name
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def save_discovery(self, result: DiscoveryResult) -> None:
        _write_json(self.dir / "discovery.json", json.loads(result.model_dump_json()))

    def load_discovery(self) -> DiscoveryResult | None:
        data = _read_json(self.dir / "discovery.json")
        return DiscoveryResult.model_validate(data) if data else None

    def save_investigation(self, result: InvestigationResult) -> None:
        _write_json(self.dir / "investigation.json", json.loads(result.model_dump_json()))

    def load_investigation(self) -> InvestigationResult | None:
        data = _read_json(self.dir / "investigation.json")
        return InvestigationResult.model_validate(data) if data else None

    def save_contract(self, contract: ChangeContract) -> None:
        _write_json(self.dir / "task.json", json.loads(contract.model_dump_json()))

    def load_contract(self) -> ChangeContract | None:
        data = _read_json(self.dir / "task.json")
        return ChangeContract.model_validate(data) if data else None

    def save_proposal(self, proposal: DesignResult) -> None:
        _write_json(self.dir / "proposal.json", json.loads(proposal.model_dump_json()))
        _write_json(self.dir / "change-map.json", json.loads(proposal.change_map.model_dump_json()))

    def load_proposal(self) -> DesignResult | None:
        data = _read_json(self.dir / "proposal.json")
        proposal = DesignResult.model_validate(data) if data else None
        state = self.load_state()
        if proposal and state and proposal.based_on_task_revision != state.task_revision:
            return None  # retained for recovery, but not an active design
        return proposal

    def archive_proposal(self, reason: str) -> Path | None:
        """Copy the current proposal to history; retain the last valid artifact."""
        proposal = self.load_proposal()
        if proposal is None:
            return None
        from uuid import uuid4
        stamp = uuid4().hex
        dest = self.history_dir / f"proposal-{stamp}.md"
        payload = self.read_text("proposal.md")
        header = f"> STALE proposal (based_on_task_revision={proposal.based_on_task_revision})\n> Reason: {reason}\n\n"
        _atomic_write(dest, header + (payload or ""))
        return dest

    # -- issues / decisions / gates ----------------------------------------

    def save_issues(self, log: IssueLog) -> None:
        _write_json(self.dir / "issues.json", json.loads(log.model_dump_json()))

    def load_issues(self) -> IssueLog:
        data = _read_json(self.dir / "issues.json")
        return IssueLog.model_validate(data) if data else IssueLog()

    def save_decisions(self, log: DecisionLog) -> None:
        _write_json(self.dir / "decisions.json", json.loads(log.model_dump_json()))

    def load_decisions(self) -> DecisionLog:
        data = _read_json(self.dir / "decisions.json")
        return DecisionLog.model_validate(data) if data else DecisionLog()

    def save_gate_log(self, log: GateLog) -> None:
        _write_json(self.dir / "human-gate.json", json.loads(log.model_dump_json()))

    def load_gate_log(self) -> GateLog:
        data = _read_json(self.dir / "human-gate.json")
        return GateLog.model_validate(data) if data else GateLog()

    # -- audit --------------------------------------------------------------

    def append_event(self, event: dict[str, Any]) -> None:
        event = {"ts": datetime.now(timezone.utc).isoformat(), **event}
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / "events.jsonl", "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    def append_raw(self, agent: str, phase: str, line: str) -> Path:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        path = self.raw_dir / f"{agent}-{phase}.jsonl"
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(line.rstrip("\n") + "\n")
        return path

    # -- session lookup -----------------------------------------------------

    @staticmethod
    def list_sessions(repository: Path | str) -> list[str]:
        root = review_root(Path(repository))
        if not root.is_dir():
            return []
        return sorted(
            p.name
            for p in root.iterdir()
            if p.is_dir() and (p / "state.json").is_file()
        )

    @staticmethod
    def load_state_of(repository: Path | str, session_id: str) -> SessionState | None:
        store = StateStore(repository, session_id)
        try:
            return store.load_state()
        except FileNotFoundError:
            return None

    @staticmethod
    def latest_session(
        repository: Path | str, unfinished_only: bool = False
    ) -> str | None:
        from agent_review.models import SessionStatus  # noqa: PLC0415

        sessions = StateStore.list_sessions(repository)
        if not unfinished_only:
            return sessions[-1] if sessions else None
        unfinished: list[str] = []
        for sid in sessions:
            state = StateStore.load_state_of(repository, sid)
            if state is None:
                continue
            if state.status == SessionStatus.RUNNING:
                unfinished.append(sid)
        return unfinished[-1] if unfinished else None
