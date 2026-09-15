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


def coverage_entry(criterion, status, issue_title=None, acceptance_id=None):
    entry = {"criterion": criterion, "status": status}
    if issue_title:
        entry["issue_title"] = issue_title
    if acceptance_id:
        entry["acceptance_id"] = acceptance_id
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


# --- acceptance coverage (design §40 + RC1 B403) -------------------------------------


def test_acceptance_coverage_recorded_and_persisted(repo):
    issue = blocker(title="validation evidence gap")
    codex = FakeCodexAdapter(
        script={
            "initial_review": [
                initial_with(
                    issue,
                    [
                        coverage_entry(
                            "原始请求的期望行为已交付：给同步任务增加暂停能力",
                            "PASS",
                            acceptance_id="A001",
                        ),
                        coverage_entry(
                            "验证证据具备区分力",
                            "FAIL",
                            "validation evidence gap",
                            acceptance_id="A002",
                        ),
                    ],
                )
            ]
        }
    )
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    # The scripted coverage references A002 which is not in the baseline
    # (A001 only) -> unknown id fails closed.
    assert o.run() == int(ExitCode.FAILED)
    assert "unknown: A002" in (o.state.error or "")


def test_acceptance_coverage_exact_baseline_ids_persisted(repo):
    issue = blocker(title="validation evidence gap")
    codex = FakeCodexAdapter(
        script={
            "initial_review": [
                initial_with(
                    issue,
                    [
                        coverage_entry(
                            "原始请求的期望行为已交付：给同步任务增加暂停能力",
                            "FAIL",
                            "validation evidence gap",
                            acceptance_id="A001",
                        )
                    ],
                )
            ]
        }
    )
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.DONE)
    stored = o.store.load_acceptance_coverage()
    assert [(e.acceptance_id, e.status) for e in stored] == [("A001", "FAIL")]
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


def test_coverage_duplicate_ids_fail_closed(repo):
    issue = blocker()
    bad = initial_with(
        issue,
        [
            coverage_entry(
                "原始请求的期望行为已交付：给同步任务增加暂停能力",
                "PASS",
                acceptance_id="A001",
            ),
            coverage_entry(
                "duplicate id",
                "PASS",
                acceptance_id="A001",
            ),
        ],
    )
    codex = FakeCodexAdapter(script={"initial_review": [bad, bad]})
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.FAILED)
    assert "duplicate acceptance_id" in (o.state.error or "")


def test_coverage_missing_baseline_id_fails_closed(repo):
    """B403: coverage omitting a baseline criterion cannot pass — and
    can never produce a false APPROVED."""
    issue = blocker()
    wrong_id = initial_with(
        issue,
        [
            coverage_entry(
                "not in the baseline", "PASS", acceptance_id="A002"
            )
        ],
    )
    codex = FakeCodexAdapter(script={"initial_review": [wrong_id, wrong_id]})
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.FAILED)
    assert "must account for exactly the current Contract Acceptance Baseline" in (
        o.state.error or ""
    )
    assert "missing: A001" in (o.state.error or "")
    assert "unknown: A002" in (o.state.error or "")


def test_initial_coverage_empty_on_rc1_contract_fails_closed(repo):
    """B403 unit boundary: an RC1 contract with ZERO reported coverage is
    invalid (no empty-baseline false-APPROVED path)."""
    from agent_review.models import InitialReviewResult
    from agent_review.phases.review import (
        _validate_initial_coverage_ids,
        effective_acceptance_baseline,
    )

    o = make_orchestrator(repo, ui=ScriptedUI(interactive=False))
    while o.state.phase.value != "INITIAL_REVIEW":
        o.step()
    baseline = effective_acceptance_baseline(o)
    assert [c.id for c in baseline] == ["A001"]
    empty = InitialReviewResult(issues=[], summary="no coverage")
    import pytest

    with pytest.raises(Exception, match="exactly the current Contract"):
        _validate_initial_coverage_ids(o, baseline, empty)


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


# --- final review completeness (design §44 + RC1 B403) ------------------------------


def test_final_review_must_reaccount_every_criterion(repo):
    """RC1 B403: exact-ID equality against the current baseline."""
    issue = blocker(title="validation evidence gap")
    final = {
        "satisfies_requirement": True,
        "unresolved_issue_ids": [],
        "issues": [],
        # A001 silently replaced by an unknown id
        "acceptance_coverage": [
            coverage_entry("not in the baseline", "PASS", acceptance_id="A002")
        ],
        "summary": "ready",
    }
    bad_final = json.dumps(final)
    codex = FakeCodexAdapter(
        script={
            "initial_review": [
                initial_with(
                    issue,
                    [
                        coverage_entry(
                            "原始请求的期望行为已交付：给同步任务增加暂停能力",
                            "FAIL",
                            "validation evidence gap",
                            acceptance_id="A001",
                        )
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
            "final_review": [bad_final],
        }
    )
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.FAILED)
    assert "must re-account every acceptance id" in (o.state.error or "")
    assert "missing: A001" in (o.state.error or "")


def test_final_review_complete_coverage_passes(repo):
    issue = blocker(title="validation evidence gap")
    final = {
        "satisfies_requirement": True,
        "unresolved_issue_ids": [],
        "issues": [],
        "acceptance_coverage": [
            coverage_entry(
                "原始请求的期望行为已交付：给同步任务增加暂停能力",
                "PASS",
                acceptance_id="A001",
            )
        ],
        "summary": "ready",
    }
    codex = FakeCodexAdapter(
        script={
            "initial_review": [
                initial_with(
                    issue,
                    [
                        coverage_entry(
                            "原始请求的期望行为已交付：给同步任务增加暂停能力",
                            "FAIL",
                            "validation evidence gap",
                            acceptance_id="A001",
                        )
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


def test_unexplained_late_blocker_fails_closed(repo):
    """RC1 B401: missing provenance is a protocol failure (repair, then
    FAILED) — never a severity downgrade and never a false APPROVED."""
    late = blocker(9, title="unexplained taste blocker").model_dump()
    bad = late_blocker_flow(late)["closure_review"][0]
    codex = FakeCodexAdapter(
        script={
            "initial_review": [
                json.dumps({"issues": [make_blocking_issue(1).model_dump()], "summary": "one"})
            ],
            "closure_review": [bad],
            "closure_review:repair": [bad],
        }
    )
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.FAILED)
    assert o.state.result_status == "FAILED"
    assert "must record origin" in (o.state.error or "")
    # The malformed blocker never became a NON_BLOCKING issue: no issue
    # was ingested from the invalid packet at all.
    assert all(i.id != "R002" for i in o.store.load_issues().issues)


def test_unexplained_late_blocker_repaired_once_converges(repo):
    """The repair path works: the re-emitted packet carries provenance
    and the blocker stays BLOCKING."""
    explained = blocker(9, title="late but explained").model_dump()
    explained["origin"] = "NEW_EVIDENCE"
    explained["correction_action"] = "FOCUSED_REVISION"
    explained["change_scope"] = ["verification_plan"]
    repaired = late_blocker_flow(explained)["closure_review"][0]
    bad = late_blocker_flow(blocker(9, title="late but explained").model_dump())["closure_review"][0]
    codex = FakeCodexAdapter(
        script={
            "initial_review": [
                json.dumps({"issues": [make_blocking_issue(1).model_dump()], "summary": "one"})
            ],
            "closure_review": [bad],
            "closure_review:repair": [repaired],
        }
    )
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.DONE)
    issues = {i.id: i for i in o.store.load_issues().issues}
    assert issues["R002"].severity.value == "BLOCKING"
    assert issues["R002"].origin.value == "NEW_EVIDENCE"


def test_previous_review_miss_without_explanation_fails_closed(repo):
    late = blocker(9, title="severe miss without explanation").model_dump()
    late["origin"] = "PREVIOUS_REVIEW_MISS"
    # why_not_detected_initially intentionally absent
    bad = late_blocker_flow(late)["closure_review"][0]
    codex = FakeCodexAdapter(
        script={
            "initial_review": [
                json.dumps({"issues": [make_blocking_issue(1).model_dump()], "summary": "one"})
            ],
            "closure_review": [bad],
            "closure_review:repair": [bad],
        }
    )
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.FAILED)
    assert "why_not_detected_initially" in (o.state.error or "")


def test_non_blocking_late_issue_needs_no_provenance(repo):
    """B401: NON_BLOCKING late issues do not require blocker provenance."""
    from agent_review.models import IssueSeverity

    late = blocker(9, title="minor taste note").model_copy(
        update={"severity": IssueSeverity.NON_BLOCKING}
    )
    flow = late_blocker_flow(late.model_dump())
    codex = FakeCodexAdapter(script=flow)
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    code = o.run()
    issues = {i.id: i for i in o.store.load_issues().issues}
    assert issues["R002"].severity.value == "NON_BLOCKING"
    assert "must record origin" not in (o.state.error or "")
    assert code != int(ExitCode.FAILED)


def test_final_new_blocker_with_origin_and_focused_fix_converges(repo):
    """c454-P2 remedy: a late blocker WITH provenance gets one targeted
    focused revision instead of a dead end at zero full-revision budget.
    RC1 B404: the scripted focused proposal echoes the current design
    and changes ONLY the in-scope canonical section."""
    from tests.unit.test_m3_human_gate import default_proposal_dict

    late = blocker(9, title="mixed-error no-data case lacks a test").model_dump()
    late["origin"] = "PREVIOUS_REVIEW_MISS"
    late["why_not_detected_initially"] = (
        "initial review audited only the ops-handover acceptance items"
    )
    late["correction_action"] = "FOCUSED_REVISION"
    late["focus_area"] = "VALIDATION"
    late["change_scope"] = ["verification_plan"]

    echoed = default_proposal_dict()
    # The ABLATION step ran first in this flow, so the CURRENT proposal
    # carries the ablated summary; the focused fix echoes it verbatim.
    echoed["summary"] = "Ablated minimal design: 给同步任务增加暂停能力"
    echoed["verification_plan"] = [
        "mixed-error no-data case now asserted before retry exhaustion"
    ]

    def focused_result(ids, scope, changed):
        return json.dumps(
            {
                "proposal": echoed,
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
                focused_result(["R001", "R002"], ["verification_plan"], ["verification_plan"])
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
    assert "never silently disappear" in text
    assert "acceptance_id" in text
    assert "origin" in text
    assert "correction_recommendations" in text


def test_prompts_expose_rc1_protocols():
    """RC1: the Agent-facing prompts expose the candidate_id dependency
    protocol, the ID-based acceptance coverage and the correction-delta
    evidence."""
    discover = open(PROMPTS_DIR + "discover.md", encoding="utf-8").read()
    assert "candidate_id" in discover
    assert "depends_on" in discover
    investigate = open(PROMPTS_DIR + "investigate.md", encoding="utf-8").read()
    assert "candidate_id" in investigate
    initial = open(PROMPTS_DIR + "initial_review.md", encoding="utf-8").read()
    assert "acceptance_id" in initial
    assert "acceptance_criteria" in initial
    closure = open(PROMPTS_DIR + "closure_review.md", encoding="utf-8").read()
    assert "{{CORRECTION_DELTA}}" in closure
    assert "actual_changed_sections" in closure
    focused = open(PROMPTS_DIR + "focused_revision.md", encoding="utf-8").read()
    assert "canonical section names" in focused
    authority = open(PROMPTS_DIR + "human_authority_check.md", encoding="utf-8").read()
    assert "authority_refs" in authority
