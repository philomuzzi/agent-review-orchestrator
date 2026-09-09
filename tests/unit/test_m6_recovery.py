"""M6: recovery behavior — interruption, resume, protocol repair caps."""

from __future__ import annotations

import json

from agent_review.agents.base import ProtocolError
from agent_review.agents.fakes import FakeCodexAdapter, FakePiAdapter, make_blocking_issue
from agent_review.config import Config
from agent_review.models import ExitCode, Phase, SessionStatus
from agent_review.orchestrator import Orchestrator


class NonInteractiveUI:
    def is_interactive(self) -> bool:
        return False

    def echo(self, text: str) -> None:
        pass

    def ask(self, prompt: str) -> str:  # pragma: no cover
        return ""


def make(repo, pi=None, codex=None):
    return Orchestrator.create(
        repository=repo,
        request="add pause capability",
        config=Config(),
        pi=pi or FakePiAdapter(),
        codex=codex or FakeCodexAdapter(),
        ui=NonInteractiveUI(),
    )


# --- Scenario 16: Ctrl+C -> INTERRUPTED, exit 130 --------------------------------


def test_ctrl_c_persists_interrupted(repo):
    pi = FakePiAdapter(script={"design": [KeyboardInterrupt()]})
    o = make(repo, pi=pi)
    code = o.run()
    assert code == int(ExitCode.INTERRUPTED)
    state = o.store.load_state()
    assert state.phase == Phase.INTERRUPTED
    assert state.status == SessionStatus.INTERRUPTED
    assert state.resume_phase == Phase.DESIGN
    # completed phases remain intact
    assert o.store.load_discovery() is not None
    assert o.store.load_contract() is not None
    events = [
        json.loads(l)["event"]
        for l in (o.store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert "SESSION_INTERRUPTED" in events
    assert "SESSION_DONE" not in events


# --- Scenario 17: resume restores the correct boundary ----------------------------


def test_resume_after_interrupt_continues_from_boundary(repo):
    pi_interrupting = FakePiAdapter(script={"design": [KeyboardInterrupt()]})
    o = make(repo, pi=pi_interrupting)
    assert o.run() == int(ExitCode.INTERRUPTED)

    pi = FakePiAdapter()  # fresh adapter; state comes from the session store
    resumed = Orchestrator.resume(
        repository=repo,
        session_id=o.state.session_id,
        config=Config(),
        pi=pi,
        codex=FakeCodexAdapter(),
        ui=NonInteractiveUI(),
    )
    code = resumed.run()
    assert code == int(ExitCode.DONE)
    # discovery/intake did NOT re-run (design was the interrupted boundary)
    discover_calls = [c for c in pi.calls if c[0] == "discover"]
    assert discover_calls == []
    design_calls = [c for c in pi.calls if c[0] == "design"]
    assert len(design_calls) == 1
    assert resumed.store.read_text("final.md") is not None


def test_resume_after_failure_retries_phase(repo):
    from agent_review.agents.base import AgentError

    pi = FakePiAdapter(script={"design": [AgentError("pi crashed mid-design")]})
    o = make(repo, pi=pi)
    assert o.run() == int(ExitCode.FAILED)
    assert o.state.error and "pi crashed" in o.state.error

    resumed = Orchestrator.resume(
        repository=repo,
        session_id=o.state.session_id,
        config=Config(),
        pi=FakePiAdapter(),
        codex=FakeCodexAdapter(),
        ui=NonInteractiveUI(),
    )
    assert resumed.run() == int(ExitCode.DONE)


# --- Protocol repair caps (scenarios 14/15) at orchestration level -----------------


def test_protocol_repair_recovers_session(repo):
    pi = FakePiAdapter(
        script={
            "discover": ["<<<not json>>>"],
        }
    )
    o = make(repo, pi=pi)
    assert o.run() == int(ExitCode.DONE)
    assert o.state.budgets.protocol_retries_used == 1


def test_second_protocol_failure_fails_session(repo):
    pi = FakePiAdapter(
        script={"discover": ["bad"], "discover:repair": ["bad again"]}
    )
    o = make(repo, pi=pi)
    assert o.run() == int(ExitCode.FAILED)
    assert isinstance(o.state.error, str) and "failed schema validation" in o.state.error
    assert o.state.budgets.protocol_retries_used == 1


# --- events and raw artifacts ------------------------------------------------------


def test_events_cover_full_lifecycle(repo):
    o = make(repo)
    o.run()
    events = [
        json.loads(l)["event"]
        for l in (o.store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    for expected in (
        "SESSION_CREATED",
        "DISCOVER_STARTED",
        "DISCOVER_COMPLETED",
        "TASK_CONTRACT_CREATED",
        "PROPOSAL_CREATED",
        "INITIAL_REVIEW_STARTED",
        "INITIAL_REVIEW_COMPLETED",
        "PASS_COMPUTED",
        "FINAL_MD_WRITTEN",
        "SESSION_DONE",
    ):
        assert expected in events, expected


def test_issue_events_recorded(repo):
    codex = FakeCodexAdapter(
        script={
            "initial_review": [
                json.dumps({"issues": [make_blocking_issue(1, "gap").model_dump()], "summary": "s"})
            ]
        }
    )
    o = make(repo, codex=codex)
    o.run()
    events = [
        json.loads(l)
        for l in (o.store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(e["event"] == "ISSUE_CREATED" and e["issue_id"] == "R001" for e in events)
    assert any(e["event"] == "ISSUE_ADDRESSED" and e["issue_id"] == "R001" for e in events)
    assert any(e["event"] == "ISSUE_RESOLVED" and e["issue_id"] == "R001" for e in events)


# --- corrupted session state fails closed -------------------------------------------


def test_resume_corrupt_state_fails(repo):
    o = make(repo)
    sid = o.state.session_id
    (o.store.dir / "state.json").write_text("{ not json", encoding="utf-8")
    import pytest

    with pytest.raises(Exception):
        Orchestrator.resume(
            repository=repo, session_id=sid, config=Config(),
            pi=FakePiAdapter(), codex=FakeCodexAdapter(), ui=NonInteractiveUI(),
        )
