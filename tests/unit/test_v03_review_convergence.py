"""V0.3 C4 — Review Convergence Contract (design §38–§49).

Differentiated review phases; acceptance coverage that may not
silently disappear; late blockers carry provenance (never suppressed
when explained); evidence-discrimination review contract.
"""

from __future__ import annotations

import json

from agent_review.agents.fakes import (
    FakeCodexAdapter,
    FakePiAdapter,
    make_blocking_issue,
)
from agent_review.models import ExitCode, IssueCategory, IssueStatus
from agent_review.prompts import __file__ as _unused  # noqa: F401

from tests.unit.test_m3_human_gate import (
    ScriptedUI,
    make_orchestrator,
)

PROMPTS_DIR = __file__.replace("tests\\unit\\test_v03_review_convergence.py", "").replace(
    "tests/unit/test_v03_review_convergence.py", ""
) + "src/agent_review/prompts/"


def events_of(o) -> list[dict]:
    return [
        json.loads(line)
        for line in (o.store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def coverage_entry(criterion, status, issue_title=None):
    entry = {"criterion": criterion, "status": status}
    if issue_title:
        entry["issue_title"] = issue_title
    return entry


def blocker(number=1, title="validation evidence has no discrimination", **update):
    return make_blocking_issue(number, title=title).model_copy(update=update)


def initial_with(issue, coverage):
    return json.dumps(
        {
            "issues": [issue.model_dump()],
            "acceptance_coverage": coverage,
            "summary": "reviewed",
        }
    )


# --- acceptance coverage (design §40) ---------------------------------------------


def test_acceptance_coverage_recorded_and_persisted(repo):
    issue = blocker(title="validation evidence gap")
    codex = FakeCodexAdapter(
        script={
            "initial_review": [
                initial_with(
                    issue,
                    [
                        coverage_entry("A01 pause semantics", "PASS"),
                        coverage_entry("A02 in-flight work safety", "FAIL", "validation evidence gap"),
                    ],
                )
            ]
        }
    )
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.DONE)
    stored = o.store.load_acceptance_coverage()
    assert [e.criterion for e in stored] == [
        "A01 pause semantics",
        "A02 in-flight work safety",
    ]
    events = [e["event"] for e in events_of(o)]
    assert "ACCEPTANCE_COVERAGE_RECORDED" in events


def test_coverage_fail_without_matching_blocking_issue_fails_closed(repo):
    issue = blocker(title="some other problem")
    bad = initial_with(
        issue,
        [coverage_entry("A01", "FAIL", "title that matches nothing")],
    )
    codex = FakeCodexAdapter(script={"initial_review": [bad, bad]})
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.FAILED)
    assert "must reference the exact title of a BLOCKING issue" in (o.state.error or "")


def test_coverage_duplicate_criteria_fail_closed(repo):
    issue = blocker()
    bad = initial_with(
        issue,
        [
            coverage_entry("A01", "PASS"),
            coverage_entry("A01", "PASS"),
        ],
    )
    codex = FakeCodexAdapter(script={"initial_review": [bad, bad]})
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.FAILED)
    assert "duplicate criterion" in (o.state.error or "")


def test_coverage_fail_entry_model_requires_issue_title():
    from agent_review.models import AcceptanceCoverageEntry

    import pytest

    with pytest.raises(ValueError):
        AcceptanceCoverageEntry(criterion="A01", status="FAIL")


def test_coverage_status_enum_rejects_unknown():
    from agent_review.models import AcceptanceCoverageEntry

    import pytest

    with pytest.raises(ValueError):
        AcceptanceCoverageEntry(criterion="A01", status="MAYBE")


# --- final review completeness (design §44) ----------------------------------------


def final_flow_scripts(initial_issue, initial_coverage, final_payload):
    return {
        "initial_review": [initial_with(initial_issue, initial_coverage)],
        # closure unresolved with explicit ABLATION recommendation keeps
        # the V0.2-style path to FINAL_REVIEW alive for this fixture.
        "closure_review": [
            json.dumps(
                {
                    "issue_outcomes": [
                        {
                            "issue_id": "R001",
                            "resolution": "UNRESOLVED",
                            "note": "over-design; ablate to minimum sufficient design",
                            "correction_action": "ABLATION",
                        }
                    ],
                    "new_issues": [],
                    "summary": "closure",
                }
            )
        ],
        "final_review": [json.dumps(final_payload)],
    }


def test_final_review_must_reaccount_every_criterion(repo):
    issue = blocker(title="validation evidence gap")
    final = {
        "satisfies_requirement": True,
        "unresolved_issue_ids": [],
        "issues": [],
        "acceptance_coverage": [
            coverage_entry("A01 pause semantics", "PASS"),
            # A02 silently disappeared
        ],
        "summary": "ready",
    }
    codex = FakeCodexAdapter(
        script=final_flow_scripts(
            issue,
            [
                coverage_entry("A01 pause semantics", "PASS"),
                coverage_entry("A02 in-flight work safety", "FAIL", "validation evidence gap"),
            ],
            final,
        )
    )
    bad_final = json.dumps(final)
    codex = FakeCodexAdapter(
        script={
            "initial_review": [
                initial_with(
                    issue,
                    [
                        coverage_entry("A01 pause semantics", "PASS"),
                        coverage_entry("A02 in-flight work safety", "FAIL", "validation evidence gap"),
                    ],
                )
            ],
            "closure_review": [
                json.dumps(
                    {
                        "issue_outcomes": [
                            {
                                "issue_id": "R001",
                                "resolution": "UNRESOLVED",
                                "note": "over-design; ablate",
                                "correction_action": "ABLATION",
                            }
                        ],
                        "new_issues": [],
                        "summary": "closure",
                    }
                )
            ],
            "final_review": [bad_final, bad_final],
        }
    )
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.FAILED)
    assert "must re-account every criterion" in (o.state.error or "")
    assert "A02 in-flight work safety" in (o.state.error or "")


def test_final_review_complete_coverage_passes(repo):
    issue = blocker(title="validation evidence gap")
    final = {
        "satisfies_requirement": True,
        "unresolved_issue_ids": [],
        "issues": [],
        "acceptance_coverage": [
            coverage_entry("A01 pause semantics", "PASS"),
            coverage_entry("A02 in-flight work safety", "PASS"),
        ],
        "summary": "ready",
    }
    codex = FakeCodexAdapter(
        script={
            "initial_review": [
                initial_with(
                    issue,
                    [
                        coverage_entry("A01 pause semantics", "PASS"),
                        coverage_entry("A02 in-flight work safety", "FAIL", "validation evidence gap"),
                    ],
                )
            ],
            "closure_review": [
                json.dumps(
                    {
                        "issue_outcomes": [
                            {
                                "issue_id": "R001",
                                "resolution": "UNRESOLVED",
                                "note": "over-design; ablate",
                                "correction_action": "ABLATION",
                            }
                        ],
                        "new_issues": [],
                        "summary": "closure",
                    }
                )
            ],
            "final_review": [json.dumps(final)],
        }
    )
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.DONE)


# --- late-blocker provenance (design §42/§43/§45) ----------------------------------


def late_blocker_flow(new_issue_dump, phase="closure_review"):
    issue = make_blocking_issue(1)
    outcome_resolution = "RESOLVED" if phase == "closure_review" else "UNRESOLVED"
    return {
        "initial_review": [json.dumps({"issues": [issue.model_dump()], "summary": "one"})],
        phase: [
            json.dumps(
                {
                    "issue_outcomes": [
                        {
                            "issue_id": "R001",
                            "resolution": outcome_resolution,
                            "note": "verified",
                            **(
                                {}
                                if phase == "closure_review"
                                else {"correction_action": "ABLATION"}
                            ),
                        }
                    ],
                    "new_issues": [new_issue_dump],
                    "summary": "late blocker",
                }
            )
        ],
    }


def test_closure_new_blocker_with_new_evidence_origin_stays_blocking(repo):
    late = blocker(9, title="new evidence contradiction").model_dump()
    late["origin"] = "NEW_EVIDENCE"
    codex = FakeCodexAdapter(script=late_blocker_flow(late))
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    code = o.run()
    issues = {i.id: i for i in o.store.load_issues().issues}
    assert issues["R002"].severity.value == "BLOCKING"
    assert issues["R002"].origin.value == "NEW_EVIDENCE"
    # Late blocker with provenance routes (never suppressed): default FULL.
    assert code == int(ExitCode.HUMAN_HANDOFF)
    assert o.state.result_status == "DESIGN_NOT_APPROVED"


def test_regression_defaults_to_introduced_by_correction(repo):
    late = blocker(9, title="revision breaks pause/resume").model_copy(
        update={"category": IssueCategory.REGRESSION}
    )
    dump = late.model_dump()
    dump["correction_action"] = "FOCUSED_REVISION"
    codex = FakeCodexAdapter(script=late_blocker_flow(dump))
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.DONE)
    issues = {i.id: i for i in o.store.load_issues().issues}
    assert issues["R002"].severity.value == "BLOCKING"
    assert issues["R002"].origin.value == "INTRODUCED_BY_CORRECTION"


def test_unexplained_late_blocker_is_downgraded(repo):
    late = blocker(9, title="unexplained taste blocker").model_dump()
    codex = FakeCodexAdapter(script=late_blocker_flow(late))
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.DONE)
    issues = {i.id: i for i in o.store.load_issues().issues}
    assert issues["R002"].severity.value == "NON_BLOCKING"
    assert "downgraded" in (issues["R002"].resolution or "")


def test_previous_review_miss_without_explanation_downgraded(repo):
    late = blocker(9, title="severe miss without explanation").model_dump()
    late["origin"] = "PREVIOUS_REVIEW_MISS"
    # why_not_detected_initially intentionally absent
    codex = FakeCodexAdapter(script=late_blocker_flow(late))
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.DONE)
    issues = {i.id: i for i in o.store.load_issues().issues}
    assert issues["R002"].severity.value == "NON_BLOCKING"


def test_final_new_blocker_with_origin_and_focused_fix_converges(repo):
    """c454-P2 remedy: a late blocker WITH provenance gets one targeted
    focused revision instead of a dead end at zero full-revision budget."""
    late = blocker(9, title="mixed-error no-data case lacks a test").model_dump()
    late["origin"] = "PREVIOUS_REVIEW_MISS"
    late["why_not_detected_initially"] = (
        "initial review audited only the ops-handover acceptance items"
    )
    late["correction_action"] = "FOCUSED_REVISION"
    late["focus_area"] = "VALIDATION"
    late["change_scope"] = ["test-matrix"]

    def focused_result(ids, scope, changed):
        return json.dumps(
            {
                "proposal": {
                    "summary": "focused fix",
                    "explicitly_unchanged": ["everything else"],
                },
                "target_issue_ids": ids,
                "allowed_change_scope": scope,
                "preserved_invariants": ["ACTIVE Human Decisions"],
                "changed_sections": changed,
                "issue_responses": [
                    {"issue_id": i, "how_addressed": "test added"} for i in ids
                ],
            }
        )

    pi = FakePiAdapter(
        script={
            "focused_revise": [
                focused_result(["R001", "R002"], ["test-matrix"], ["test-matrix"])
            ]
        }
    )
    codex = FakeCodexAdapter(
        script={
            "initial_review": [json.dumps({"issues": [make_blocking_issue(1).model_dump()], "summary": "one"})],
            "closure_review": [
                json.dumps(
                    {
                        "issue_outcomes": [
                            {
                                "issue_id": "R001",
                                "resolution": "UNRESOLVED",
                                "note": "over-design; ablate",
                                "correction_action": "ABLATION",
                            }
                        ],
                        "new_issues": [],
                        "summary": "closure",
                    }
                )
            ],
            "final_review": [
                json.dumps(
                    {
                        "satisfies_requirement": False,
                        "unresolved_issue_ids": ["R001"],
                        "issues": [late],
                        "summary": "late coverage gap",
                    }
                )
            ],
        }
    )
    o = make_orchestrator(repo, pi=pi, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.DONE)
    assert o.state.budgets.focused_revision_used == 1
    issues = {i.id: i for i in o.store.load_issues().issues}
    assert issues["R002"].severity.value == "BLOCKING"  # not suppressed
    assert issues["R002"].status == IssueStatus.RESOLVED


# --- prompt contracts (evidence discrimination etc.) --------------------------------


def test_initial_review_prompt_carries_evidence_discrimination_contract():
    text = open(PROMPTS_DIR + "initial_review.md", encoding="utf-8").read()
    assert "Evidence Discrimination" in text
    assert "distinguish" in text
    assert "acceptance_coverage" in text
    assert "correction_action" in text


def test_closure_prompt_carries_differential_and_provenance_contract():
    text = open(PROMPTS_DIR + "closure_review.md", encoding="utf-8").read()
    assert "DIFFERENTIAL" in text
    assert "INTRODUCED_BY_CORRECTION" in text
    assert "PREVIOUS_REVIEW_MISS" in text
    assert "NEW_EVIDENCE" in text
    assert "DIRECTLY_REQUIRED_FOR_CLOSURE" in text
    assert "material_progress" in text


def test_final_prompt_carries_readiness_and_completeness_contract():
    text = open(PROMPTS_DIR + "final_review.md", encoding="utf-8").read()
    assert "READINESS review" in text
    assert "may not silently disappear" in text
    assert "origin" in text
    assert "correction_recommendations" in text
