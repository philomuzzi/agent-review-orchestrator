"""V0.3 C3 — Focused Revision contract (design §33–§37).

The focused mechanism preserves ACTIVE Human Decisions and unrelated
design, never rediscovers, respects the allowed change scope, and
responds issue by issue. Budgets: focused revision is a separate
mechanism, not a sequential life after full revision.
"""

from __future__ import annotations

import json

import pytest

from agent_review.agents.fakes import (
    FakeCodexAdapter,
    FakePiAdapter,
    make_blocking_issue,
)
from agent_review.models import (
    CorrectionAction,
    ExitCode,
    FocusArea,
    IssueStatus,
    Phase,
)
from agent_review.orchestrator import Orchestrator

from tests.unit.test_m3_human_gate import (
    ScriptedUI,
    candidate,
    discovery_with_candidates,
    make_orchestrator,
)


def focused_issue(number=1, change_scope=(), title="validation evidence has no discrimination"):
    return make_blocking_issue(number, title=title).model_copy(
        update={
            "correction_action": CorrectionAction.FOCUSED_REVISION,
            "focus_area": FocusArea.VALIDATION,
            "change_scope": list(change_scope),
        }
    )


def review_with(issue):
    return json.dumps({"issues": [issue.model_dump()], "summary": "blocked"})


def events_of(o) -> list[dict]:
    return [
        json.loads(line)
        for line in (o.store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def focused_result_json(issue_ids, allowed_scope, changed_sections, extra=""):
    responses = [
        {"issue_id": i, "how_addressed": f"focused fix satisfies the close condition of {i}"}
        for i in issue_ids
    ]
    return json.dumps(
        {
            "proposal": {
                "summary": "focused revised design",
                "explicitly_unchanged": ["everything outside the allowed scope"],
                "changes": ["bounded fix inside the allowed scope"],
            },
            "target_issue_ids": list(issue_ids),
            "allowed_change_scope": list(allowed_scope),
            "preserved_invariants": [
                "ACTIVE Human Decisions preserved unchanged",
                "explicitly unchanged sections preserved",
            ],
            "changed_sections": list(changed_sections),
            "issue_responses": responses,
            "acceptance_changes": [],
            "notes": "focused only" + extra,
        }
    )


# --- routing into the mechanism ------------------------------------------------


def test_focused_revision_preserves_human_decisions_and_task_revision(repo):
    """C3 §35: ACTIVE Human Decisions are preserved — the focused fix
    never invalidates the design basis (no task_revision bump, decisions
    untouched, no proposal STALE event)."""
    issue = focused_issue()
    pi = FakePiAdapter(
        script={
            "discover": [discovery_with_candidates([candidate()])],
            "focused_revise": [
                focused_result_json(["R001"], ["verification-plan"], ["verification-plan"])
            ],
        }
    )
    codex = FakeCodexAdapter(script={"initial_review": [review_with(issue)]})
    o = make_orchestrator(repo, pi=pi, codex=codex, ui=ScriptedUI(answers=["1"]))
    assert o.run() == int(ExitCode.DONE)
    # The intake decision D001 stays ACTIVE and untouched.
    decisions = o.store.load_decisions().decisions
    assert len(decisions) == 1
    assert decisions[0].status.value == "ACTIVE"
    # task_revision unchanged (2 after the intake gate; never bumped by
    # the focused correction).
    assert o.state.task_revision == 2
    events = [e["event"] for e in events_of(o)]
    # ...and nothing AFTER the focused revision started invalidates the basis.
    focused_at = events.index("FOCUSED_REVISION_STARTED")
    post_focus = events[focused_at:]
    assert "TASK_REVISION_INCREMENTED" not in post_focus
    assert "PROPOSAL_STALE" not in post_focus
    assert "ISSUE_SUPERSEDED" not in post_focus


def test_focused_revision_does_not_rediscover(repo):
    """Exactly one focused_revise call; no DISCOVER re-run from the
    focused path."""
    issue = focused_issue()
    pi = FakePiAdapter(
        script={
            "focused_revise": [
                focused_result_json(["R001"], [], [])
            ]
        }
    )
    codex = FakeCodexAdapter(script={"initial_review": [review_with(issue)]})
    o = make_orchestrator(repo, pi=pi, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.DONE)
    discover_calls = [c for c in pi.calls if c[0] == "discover"]
    focused_calls = [c for c in pi.calls if c[0] == "focused_revise"]
    assert len(discover_calls) == 1  # the original DISCOVER only
    assert len(focused_calls) == 1
    # No revision-phase call happened.
    assert not [c for c in pi.calls if c[0] == "revise"]


def test_focused_revision_respects_allowed_change_scope(repo):
    """changed_sections outside the declared change_scope fail closed."""
    issue = focused_issue(change_scope=["verification-plan", "test-matrix"])
    bad = focused_result_json(
        ["R001"], ["verification-plan", "test-matrix"], ["unrelated-module"]
    )
    pi = FakePiAdapter(script={"focused_revise": [bad, bad]})
    codex = FakeCodexAdapter(script={"initial_review": [review_with(issue)]})
    o = make_orchestrator(repo, pi=pi, codex=codex, ui=ScriptedUI(interactive=False))
    code = o.run()
    assert code == int(ExitCode.FAILED)
    assert "outside the allowed change scope" in (o.state.error or "")


def test_focused_revision_must_target_routed_issues(repo):
    issue = focused_issue()
    wrong = focused_result_json(["R999"], [], [])
    pi = FakePiAdapter(script={"focused_revise": [wrong, wrong]})
    codex = FakeCodexAdapter(script={"initial_review": [review_with(issue)]})
    o = make_orchestrator(repo, pi=pi, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.FAILED)
    assert "exactly the routed target issues" in (o.state.error or "")


def test_focused_revision_model_requires_issue_by_issue_responses():
    from agent_review.models import FocusedRevisionResult

    with pytest.raises(ValueError):
        FocusedRevisionResult(
            proposal={
                "summary": "x",
                "explicitly_unchanged": ["y"],
            },
            target_issue_ids=["R001", "R002"],
            issue_responses=[
                {"issue_id": "R001", "how_addressed": "done"}
            ],
        )


def test_focused_revision_flow_artifacts_and_budget(repo):
    issue = focused_issue(change_scope=["verification-plan"])
    pi = FakePiAdapter(
        script={
            "focused_revise": [
                focused_result_json(["R001"], ["verification-plan"], ["verification-plan"])
            ],
        }
    )
    codex = FakeCodexAdapter(script={"initial_review": [review_with(issue)]})
    o = make_orchestrator(repo, pi=pi, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.DONE)
    assert o.state.budgets.focused_revision_used == 1
    assert o.state.budgets.revision_used == 0
    assert o.state.last_correction_action == "FOCUSED_REVISION"
    assert (o.store.dir / "focused-revision.md").is_file()
    focused_md = o.store.read_text("focused-revision.md")
    assert "target issues: R001" in focused_md
    assert "preserved invariants" in focused_md
    r001 = next(i for i in o.store.load_issues().issues if i.id == "R001")
    assert r001.status == IssueStatus.RESOLVED  # closure verified it
    # Closure review followed the focused revision.
    events = [e["event"] for e in events_of(o)]
    assert events.index("FOCUSED_REVISION_COMPLETED") < events.index("CLOSURE_REVIEW_STARTED")


def test_focused_revision_budget_is_separate_mechanism(repo):
    """Design §37: focused revision is not a sequential life after full
    revision — after a REVISION (1/1 used), a FOCUSED_REVISION
    recommendation still executes on its own budget."""
    first = make_blocking_issue(1, title="broad gap").model_copy(
        update={"correction_action": CorrectionAction.FULL_REVISION}
    )
    regression = focused_issue(2, change_scope=["verification-plan"]).model_copy(
        update={"title": "focused gap introduced later"}
    )
    regression_dump = regression.model_dump()
    regression_dump["origin"] = "INTRODUCED_BY_CORRECTION"
    codex = FakeCodexAdapter(
        script={
            "initial_review": [json.dumps({"issues": [first.model_dump()], "summary": "one"})],
            "closure_review": [
                json.dumps(
                    {
                        "issue_outcomes": [
                            {"issue_id": "R001", "resolution": "RESOLVED", "note": "ok"}
                        ],
                        "new_issues": [regression_dump],
                        "summary": "fixed but introduced a focused gap",
                    }
                )
            ],
        }
    )
    pi = FakePiAdapter(
        script={
            "focused_revise": [
                focused_result_json(["R002"], ["verification-plan"], ["verification-plan"])
            ],
        }
    )
    o = make_orchestrator(repo, pi=pi, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.DONE)
    assert o.state.budgets.revision_used == 1
    assert o.state.budgets.focused_revision_used == 1
