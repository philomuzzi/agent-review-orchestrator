"""M1 acceptance: deterministic state machine through fake adapters."""

from __future__ import annotations

from agent_review.agents.fakes import FakeCodexAdapter, FakePiAdapter
from agent_review.config import Config
from agent_review.models import ExitCode, Phase, SessionStatus, TaskKind
from agent_review.orchestrator import Orchestrator
from agent_review.state_machine import ALLOWED_TRANSITIONS, assert_transition
from agent_review.storage import StateStore

import pytest


def make_orchestrator(repo, pi=None, codex=None, kind=None, request="add pause to sync task"):
    return Orchestrator.create(
        repository=repo,
        request=request,
        task_kind_explicit=kind,
        config=Config(),
        pi=pi or FakePiAdapter(),
        codex=codex or FakeCodexAdapter(),
    )


def test_state_machine_table_shape():
    # Spot-check the frozen Change flow.
    assert Phase.DESIGN in ALLOWED_TRANSITIONS[Phase.INTAKE]
    assert Phase.REVISION in ALLOWED_TRANSITIONS[Phase.INITIAL_REVIEW]
    assert Phase.DONE in ALLOWED_TRANSITIONS[Phase.FINALIZE]
    assert Phase.DONE not in ALLOWED_TRANSITIONS[Phase.DESIGN]
    assert ALLOWED_TRANSITIONS[Phase.DONE] == set()
    with pytest.raises(ValueError):
        assert_transition(Phase.DONE, Phase.DESIGN)
    with pytest.raises(ValueError):
        assert_transition(Phase.DESIGN, Phase.DONE)


def test_m1_no_blocker_flow_reaches_done(repo):
    o = make_orchestrator(repo)
    code = o.run()
    assert code == int(ExitCode.DONE)
    state = o.store.load_state()
    assert state.phase == Phase.DONE
    assert state.status == SessionStatus.DONE
    assert state.round == 1
    final = o.store.read_text("final.md")
    assert final is not None
    for section in (
        "Change Goal",
        "Current Behavior",
        "Final Design",
        "Explicitly Unchanged",
        "Verification Plan",
        "Implementation Notes",
    ):
        assert section in final


def test_m1_phase_artifacts_persisted_in_order(repo):
    o = make_orchestrator(repo)
    o.run()
    for name in (
        "input.md",
        "discovery.json",
        "discovery.md",
        "task.json",
        "task.md",
        "proposal.json",
        "proposal.md",
        "change-map.json",
        "issues.json",
        "state.json",
        "final.md",
        "events.jsonl",
    ):
        assert (o.store.dir / name).is_file(), name


def test_m1_resume_after_done_is_idempotent(repo):
    o = make_orchestrator(repo)
    assert o.run() == int(ExitCode.DONE)
    sid = o.state.session_id
    resumed = Orchestrator.resume(repository=repo, session_id=sid, config=Config())
    assert resumed.run() == int(ExitCode.DONE)
    # No second review round was executed.
    assert resumed.state.round == 1


def test_m1_problem_mode_routes_through_investigate(repo):
    pi = FakePiAdapter()
    o = make_orchestrator(repo, pi=pi, kind="problem")
    assert o.run() == int(ExitCode.DONE)
    # Fake investigation returns SUPPORTED root cause; flow reaches DONE.
    assert ("investigate", None) in [c for c in pi.calls]
    assert o.store.load_investigation() is not None
    contract = o.store.load_contract()
    assert contract.root_cause


def test_m1_task_kind_discovered_when_not_explicit(repo):
    from agent_review.agents.fakes import default_discovery
    from agent_review.models import SessionState

    pi = FakePiAdapter()
    # Script a PROBLEM discovery while --kind is not explicit.
    def problem_discovery_result():
        d = default_discovery(SessionState(session_id="x", repository=str(repo), request="r"))
        d.task_kind = TaskKind.PROBLEM
        return d

    pi.script["discover"] = [problem_discovery_result().model_dump_json()]
    o = make_orchestrator(repo, pi=pi)
    assert o.run() == int(ExitCode.DONE)
    assert o.state.task_kind == TaskKind.PROBLEM


def test_m1_explicit_kind_overrides_discovery(repo):
    pi = FakePiAdapter()
    o = make_orchestrator(repo, pi=pi, kind="change")
    # Fake discovery returns CHANGE anyway; prove explicitness is recorded
    # and the flow skips INVESTIGATE.
    assert o.run() == int(ExitCode.DONE)
    assert o.state.kind_explicit is True
    assert o.store.load_investigation() is None
