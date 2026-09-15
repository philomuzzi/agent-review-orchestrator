"""V0.3 C2 — generic correction action routing (design §24–§32).

Agents recommend; the orchestrator controls execution. ABLATION is
never the default fallback; STOP and no-material-progress stops land as
a precise DESIGN_NOT_APPROVED — never mislabeled as NEEDS_HUMAN_DECISION.
"""

from __future__ import annotations

import json

from agent_review.agents.fakes import (
    FakeCodexAdapter,
    FakePiAdapter,
    make_blocking_issue,
)
from agent_review.config import Config
from agent_review.models import (
    CorrectionAction,
    FocusArea,
    ExitCode,
    IssueCategory,
    Phase,
    SessionStatus,
)
from agent_review.orchestrator import Orchestrator
from agent_review.phases.review import route_engineering_correction
from agent_review.models import CorrectionRecommendation

from tests.unit.test_m3_human_gate import (
    ScriptedUI,
    candidate,
    discovery_with_candidates,
    make_orchestrator,
)


def blocker(number=1, **update):
    issue = make_blocking_issue(number)
    return issue.model_copy(update=update)

def review_with(issue, coverage=None):
    payload = {"issues": [issue.model_dump()], "summary": "blocked"}
    if coverage is not None:
        payload["acceptance_coverage"] = coverage
    return json.dumps(payload)


def events_of(o) -> list[dict]:
    return [
        json.loads(line)
        for line in (o.store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def run_with_blocker(repo, issue, extra_script=None, ui=None):
    script = {"initial_review": [review_with(issue)]}
    script.update(extra_script or {})
    codex = FakeCodexAdapter(script=script)
    o = make_orchestrator(repo, codex=codex, ui=ui or ScriptedUI(interactive=False))
    return o, o.run()


# --- FULL_REVISION routing -------------------------------------------------------


def test_full_revision_routing(repo):
    o, code = run_with_blocker(repo, blocker(1, correction_action=CorrectionAction.FULL_REVISION))
    assert code == int(ExitCode.DONE)
    assert o.state.budgets.revision_used == 1
    events = [e["event"] for e in events_of(o)]
    assert "CORRECTION_ROUTED" in events
    routed = next(e for e in events_of(o) if e["event"] == "CORRECTION_ROUTED")
    assert routed["action"] == "FULL_REVISION"
    assert "ABLATION_TRIGGERED" not in events


def test_default_without_recommendation_is_full_revision(repo):
    o, code = run_with_blocker(repo, blocker(1))
    assert code == int(ExitCode.DONE)
    assert o.state.budgets.revision_used == 1
    assert o.state.budgets.ablation_used == 0


# --- FOCUSED_REVISION routing ------------------------------------------------------


def test_focused_revision_routing(repo):
    o, code = run_with_blocker(
        repo,
        blocker(
            1,
            correction_action=CorrectionAction.FOCUSED_REVISION,
            focus_area=FocusArea.VALIDATION,  # descriptive only
        ),
    )
    assert code == int(ExitCode.DONE)
    assert o.state.budgets.focused_revision_used == 1
    assert o.state.budgets.revision_used == 0
    events = [e["event"] for e in events_of(o)]
    routed = next(e for e in events_of(o) if e["event"] == "CORRECTION_ROUTED")
    assert routed["action"] == "FOCUSED_REVISION"
    assert "FOCUSED_REVISION_STARTED" in events
    assert "ABLATION_TRIGGERED" not in events


def test_priority_full_over_focused_when_both_recommended(repo):
    """Deterministic preference: the broadest available correction
    handles all recommended blockers in one round (design §32)."""
    issues = [
        blocker(1, title="broad gap", correction_action=CorrectionAction.FULL_REVISION),
        blocker(2, title="narrow gap", correction_action=CorrectionAction.FOCUSED_REVISION),
    ]
    payload = {"issues": [i.model_dump() for i in issues], "summary": "two"}
    codex = FakeCodexAdapter(script={"initial_review": [json.dumps(payload)]})
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.DONE)
    assert o.state.budgets.revision_used == 1
    assert o.state.budgets.focused_revision_used == 0


# --- explicit ABLATION routing -----------------------------------------------------


def test_explicit_ablation_routing(repo):
    o, code = run_with_blocker(
        repo,
        blocker(1, correction_action=CorrectionAction.ABLATION),
    )
    assert code == int(ExitCode.DONE)
    assert o.state.budgets.ablation_used == 1
    assert o.state.budgets.revision_used == 0
    assert (o.store.dir / "ablation.md").is_file()
    events = [e["event"] for e in events_of(o)]
    assert "ABLATION_TRIGGERED" in events


def test_ablation_never_auto_triggers_after_failed_revision(repo):
    """Design §28 hard rule: closure-unresolved WITHOUT an ablation
    recommendation stops; ABLATION budget stays untouched."""
    codex = FakeCodexAdapter(
        script={
            "initial_review": [review_with(blocker(1))],
            "closure_review": [
                json.dumps(
                    {
                        "issue_outcomes": [
                            {
                                "issue_id": "R001",
                                "resolution": "UNRESOLVED",
                                "note": "close condition not satisfied",
                                "material_progress": "PROGRESSED",
                                "note_extra": None,
                                "correction_action": "FULL_REVISION",
                            }
                        ],
                        "new_issues": [],
                        "summary": "not verified",
                    }
                )
            ],
        }
    )
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    code = o.run()
    assert code == int(ExitCode.HUMAN_HANDOFF)
    assert o.state.budgets.ablation_used == 0
    assert o.state.result_status == "DESIGN_NOT_APPROVED"
    assert "ABLATION_TRIGGERED" not in [e["event"] for e in events_of(o)]


# --- HUMAN_DECISION routing --------------------------------------------------------


def test_human_decision_recommendation_runs_authority_check(repo):
    """A HUMAN_DECISION recommendation on an engineering-categorized
    issue routes through the same Human Authority Check as
    REQUIREMENT/FACT category (design §29)."""
    from tests.unit.test_v02_authority_convergence import covered_result

    issue = blocker(
        1,
        category=IssueCategory.DESIGN,
        correction_action=CorrectionAction.HUMAN_DECISION,
    )
    pi = FakePiAdapter(
        script={
            "discover": [discovery_with_candidates([candidate()])],
            "human_authority_check": [covered_result()],
        }
    )
    codex = FakeCodexAdapter(script={"initial_review": [review_with(issue)]})
    o = make_orchestrator(
        repo, pi=pi, codex=codex, ui=ScriptedUI(answers=["1"])
    )
    assert o.run() == int(ExitCode.DONE)
    events = [e["event"] for e in events_of(o)]
    assert "ISSUE_NEED_HUMAN" in events
    assert "ISSUE_COVERED_BY_DECISION" in events
    assert "CONVERGENCE_GATE_CREATED" not in events
    assert o.state.budgets.revision_used == 1  # covered -> engineering fix


# --- STOP routing --------------------------------------------------------------------


def test_stop_recommendation_terminates_design_not_approved(repo):
    o, code = run_with_blocker(
        repo,
        blocker(
            1,
            correction_action=CorrectionAction.STOP,
            title="external evidence unavailable",
        ),
    )
    assert code == int(ExitCode.HUMAN_HANDOFF)
    assert o.state.result_status == "DESIGN_NOT_APPROVED"
    assert o.state.budgets.revision_used == 0
    assert o.state.budgets.focused_revision_used == 0
    assert o.state.budgets.ablation_used == 0
    events = [e["event"] for e in events_of(o)]
    assert "CORRECTION_STOPPED" in events
    result = o.store.read_text("session-result.md")
    assert "DESIGN_NOT_APPROVED" in result
    # Agent convergence failure is NOT a Human decision need.
    assert "NEEDS_HUMAN_DECISION" not in result.split("## Status")[1].split("##")[0]


def test_unknown_action_value_fails_closed(repo):
    raw = blocker(1).model_dump()
    raw["correction_action"] = "RESTART_EVERYTHING"
    bad = json.dumps({"issues": [raw], "summary": "blocked"})
    pi = FakePiAdapter()
    codex = FakeCodexAdapter(
        script={"initial_review": [bad], "initial_review:repair": [bad]}
    )
    o = make_orchestrator(repo, pi=pi, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.FAILED)


# --- material progress (design §46–§49) ------------------------------------------------


def closure_unresolved(correction, progress, note="close condition not satisfied"):
    return json.dumps(
        {
            "issue_outcomes": [
                {
                    "issue_id": "R001",
                    "resolution": "UNRESOLVED",
                    "note": note,
                    "correction_action": correction,
                    "material_progress": progress,
                }
            ],
            "new_issues": [],
            "summary": "closure",
        }
    )


def test_no_material_progress_repeat_stops(repo):
    """Same blocker, correction attempted, no narrowing, next action
    repeats the same work -> STOP -> DESIGN_NOT_APPROVED (design §48)."""
    o, code = run_with_blocker(
        repo,
        blocker(1, correction_action=CorrectionAction.FOCUSED_REVISION),
        extra_script={
            "closure_review": [
                closure_unresolved(
                    "FOCUSED_REVISION",
                    "NO_PROGRESS",
                    "close condition unchanged; no new evidence",
                )
            ]
        },
    )
    assert code == int(ExitCode.HUMAN_HANDOFF)
    assert o.state.result_status == "DESIGN_NOT_APPROVED"
    assert o.state.budgets.focused_revision_used == 1
    events = [e["event"] for e in events_of(o)]
    assert "NO_MATERIAL_PROGRESS_STOP" in events
    assert "CORRECTION_STOPPED" in events


def test_material_progress_allows_next_action(repo):
    """PROGRESSED (with structured evidence) + a different next action
    continues instead of stopping."""
    o, code = run_with_blocker(
        repo,
        blocker(1, correction_action=CorrectionAction.FOCUSED_REVISION),
        extra_script={
            "closure_review": [
                closure_unresolved(
                    "FULL_REVISION",
                    "PROGRESSED",
                    "close condition narrowed to the transaction boundary only",
                )
            ]
        },
    )
    assert code == int(ExitCode.DONE)
    assert o.state.budgets.focused_revision_used == 1
    assert o.state.budgets.revision_used == 1
    assert "NO_MATERIAL_PROGRESS_STOP" not in [e["event"] for e in events_of(o)]


def test_progressed_without_evidence_note_rejected(repo):
    raw = {
        "issue_outcomes": [
            {
                "issue_id": "R001",
                "resolution": "UNRESOLVED",
                "correction_action": "FULL_REVISION",
                "material_progress": "PROGRESSED",
                "note": "",
            }
        ],
        "new_issues": [],
        "summary": "closure",
    }
    bad = json.dumps(raw)
    codex = FakeCodexAdapter(
        script={
            "initial_review": [review_with(blocker(1))],
            "closure_review": [bad, bad],
        }
    )
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.FAILED)


def test_budget_exhaustion_for_recommended_action_stops(repo):
    """FOCUSED recommended but its budget is gone (and nothing else is
    recommended): stop — mechanisms are not ladder lives."""
    o, code = run_with_blocker(
        repo,
        blocker(1, correction_action=CorrectionAction.FOCUSED_REVISION),
        extra_script={
            "closure_review": [
                closure_unresolved(
                    "FOCUSED_REVISION",
                    "PROGRESSED",
                    "close condition materially narrower",
                )
            ]
        },
    )
    assert code == int(ExitCode.HUMAN_HANDOFF)
    assert o.state.result_status == "DESIGN_NOT_APPROVED"
    assert "no recommended corrective action has remaining budget" in (
        o.state.handoff_reason or ""
    )


# --- unit-level routing engine -----------------------------------------------------


def test_route_engineering_empty_recommendations_handoff_not_crash(repo):
    o = make_orchestrator(repo, ui=ScriptedUI(interactive=False))
    code = route_engineering_correction(o, [])
    assert code == int(ExitCode.HUMAN_HANDOFF)
    assert o.state.result_status == "DESIGN_NOT_APPROVED"


def test_recommendation_model_progressed_requires_note():
    from agent_review.models import CorrectionRecommendation
    import pytest

    with pytest.raises(ValueError):
        CorrectionRecommendation(
            issue_id="R001",
            correction_action=CorrectionAction.FULL_REVISION,
            material_progress="PROGRESSED",
            note="",
        )
