"""M0: fake adapters produce valid protocol models."""

from __future__ import annotations

from agent_review.agents.fakes import FakeCodexAdapter, FakePiAdapter
from agent_review.models import Phase, SessionState


def make_state(repo, request="add feature") -> SessionState:
    return SessionState(
        session_id="20260909-000000-test",
        repository=str(repo),
        request=request,
        phase=Phase.DESIGN,
    )


def test_fake_pi_defaults(repo):
    pi = FakePiAdapter()
    state = make_state(repo)
    discovery = pi.discover(state)
    assert discovery.current_state
    investigation = pi.investigate(state)
    assert investigation.root_cause_status == "SUPPORTED"
    design = pi.design(state, _real_contract())
    assert design.explicitly_unchanged
    assert design.based_on_task_revision == state.task_revision


def _real_contract():
    from agent_review.models import ChangeContract

    return ChangeContract(
        user_intent="add pause capability",
        current_behavior="sync task runs to completion",
        desired_behavior="sync task can pause",
    )


def test_fake_pi_scripted_invalid_then_repair(repo):
    pi = FakePiAdapter(script={"discover": ["not json at all"]})
    state = make_state(repo)
    result = pi.discover(state)
    assert result.current_state
    repair_calls = [c for c in pi.calls if c[0] == "discover" and c[1] is not None]
    assert repair_calls, "expected exactly one protocol-repair attempt"


def test_fake_pi_second_invalid_raises_protocol_error(repo):
    from agent_review.agents.base import ProtocolError

    pi = FakePiAdapter(
        script={
            "discover": ["not json"],
            "discover:repair": ["still not json"],
        }
    )
    state = make_state(repo)
    try:
        pi.discover(state)
        raise AssertionError("expected ProtocolError")
    except ProtocolError as exc:
        assert "discover" in str(exc)


def test_fake_codex_defaults(repo):
    codex = FakeCodexAdapter()
    state = make_state(repo)
    contract = _real_contract()
    design = FakePiAdapter().design(state, contract)
    review = codex.initial_review(state, contract, design)
    assert review.issues == []
