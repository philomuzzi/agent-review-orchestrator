"""M0 acceptance: package skeleton, models, storage, CLI help."""

from __future__ import annotations

import json

from agent_review.models import (
    BudgetLimits,
    ChangeContract,
    DesignResult,
    DiscoveryResult,
    ExitCode,
    GateQuestion,
    HumanGate,
    Issue,
    IssueSeverity,
    Phase,
    SessionState,
    TaskKind,
)
from agent_review.storage import StateStore


def test_m0_session_create_and_persist(repo):
    store = StateStore.create_session(repo, "Add pause capability to sync task", None)
    assert (store.dir / "state.json").is_file()
    assert (store.dir / "input.md").is_file()
    state = store.load_state()
    assert state is not None
    assert state.phase == Phase.INIT
    assert state.task_kind == TaskKind.CHANGE
    assert state.kind_explicit is False
    # V0.1: compact stable id, independent of request wording.
    import re

    assert re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{4}", state.session_id)
    assert "pause" not in state.session_id
    assert state.task_title is None and state.task_title_source is None


def test_m0_state_roundtrip_and_events(repo):
    store = StateStore.create_session(repo, "fix flaky test", None)
    state = store.load_state()
    state.phase = Phase.DISCOVER
    store.save_state(state)
    store.append_event({"event": "DISCOVER_STARTED"})
    reloaded = store.load_state()
    assert reloaded.phase == Phase.DISCOVER
    events = (store.dir / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(events[0])["event"] == "SESSION_CREATED"
    assert json.loads(events[1])["event"] == "DISCOVER_STARTED"


def test_m0_blocking_issue_requires_acceptance():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Issue(title="no acceptance", severity=IssueSeverity.BLOCKING)


def test_m0_gate_question_option_bounds():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GateQuestion(decision_key="D1", question="q", options=[])


def test_m0_latest_session_selection(repo):
    """Latest = newest by persisted created_at (V0.1-RC2 B101 policy).

    The random 4-hex id suffix carries no temporal meaning within one
    second, so directory-name order must never decide recency.
    """
    first = StateStore.create_session(repo, "first request", None)
    second = StateStore.create_session(repo, "second request", None)
    sessions = StateStore.list_sessions(repo)
    assert len(sessions) == 2
    assert StateStore.latest_session(repo, unfinished_only=False) == second.session_id
    assert first.session_id != second.session_id
