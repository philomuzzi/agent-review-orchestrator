"""V0.2-RC2 regressions: Final Review authority routing, Problem Mode
FACT convergence re-investigation, and decision-candidate packet
integrity (B201/B202/B203 + N201/N202).

Spec: docs/V0_2_RC2_FIX_SPEC.md sections 2, 3 and 4 (RC2 regression
suite items 1-16).
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent_review.agents.fakes import (
    FakeCodexAdapter,
    FakePiAdapter,
    default_investigation,
    make_blocking_issue,
)
from agent_review.config import Config
from agent_review.models import (
    BudgetLimits,
    ExitCode,
    GateCategory,
    GateOption,
    GateQuestion,
    IssueCategory,
    IssueStatus,
    Phase,
    SessionStatus,
)
from agent_review.orchestrator import Orchestrator
from agent_review.phases.human_gate import compute_resume_semantics

from tests.unit.test_m3_human_gate import (
    ScriptedUI,
    candidate,
    discovery_with_candidates,
    make_orchestrator,
)


def events_of(o) -> list[dict]:
    return [
        json.loads(line)
        for line in (o.store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def event_names(o) -> list[str]:
    return [e["event"] for e in events_of(o)]


def requirement_blocker(number=1, title="Missing decided scope coverage"):
    return make_blocking_issue(
        number,
        title=title,
        category=IssueCategory.REQUIREMENT,
        acceptance=["Design covers the already-decided scope."],
    )


def fact_blocker(number=1, title="Disputed production fact"):
    return make_blocking_issue(
        number,
        title=title,
        category=IssueCategory.FACT,
        acceptance=["The authoritative fact is established."],
    )


def review_with_issues(*issues, summary="blocked"):
    return json.dumps(
        {
            "issues": [
                i.model_dump(mode="json") if hasattr(i, "model_dump") else i
                for i in issues
            ],
            "summary": summary,
        }
    )


def covered_result(issue_id="R001", decision_ids=("D001",)):
    return json.dumps(
        {
            "outcomes": [
                {
                    "issue_id": issue_id,
                    "outcome": "COVERED_BY_ACTIVE_DECISION",
                    "referenced_decision_ids": list(decision_ids),
                    "rationale": (
                        "D001 already placed the disputed semantics inside the "
                        "decided scope; the issue is an implementation gap."
                    ),
                }
            ]
        }
    )


def needs_new_result(
    issue_id="R001",
    category="REQUIREMENT",
    question="现有全量日报在修复后如何统一展示统计（§5.4/A07）？",
    options=None,
    recommendation="precise",
    source_issue_ids=None,
):
    options = options or [
        {"key": "precise", "label": "重算日报统计为精确匹配口径", "impact": "历史与新增一致"},
        {"key": "legacy", "label": "保持现状并注明历史分类", "impact": "零改动，口径混合"},
    ]
    return json.dumps(
        {
            "outcomes": [
                {
                    "issue_id": issue_id,
                    "outcome": "NEEDS_NEW_HUMAN_DECISION",
                    "rationale": "No ACTIVE decision establishes the semantics.",
                    "decision_candidate": {
                        "category": category,
                        "question": question,
                        "why_human": "业务语义，仓库与既有决策均未定义。",
                        "options": options,
                        "recommendation": recommendation,
                        "source_issue_ids": source_issue_ids or [issue_id],
                    },
                }
            ]
        }
    )


def cannot_determine_result(issue_id="R001"):
    return json.dumps(
        {
            "outcomes": [
                {
                    "issue_id": issue_id,
                    "outcome": "CANNOT_DETERMINE",
                    "rationale": "coverage depends on production data lineage",
                }
            ]
        }
    )


# ---------------------------------------------------------------------------
# B201 helpers: drive a CHANGE session all the way to FINAL_REVIEW
# ---------------------------------------------------------------------------


def final_review_script(*new_issues, satisfies=False, unresolved=()):
    """FINAL_REVIEW result raising new blockers (closure restrictions
    require why_not_detected_initially for non-REGRESSION BLOCKING)."""
    issues = []
    for issue in new_issues:
        data = issue.model_dump(mode="json") if hasattr(issue, "model_dump") else dict(issue)
        data["why_not_detected_initially"] = (
            data.get("why_not_detected_initially")
            or "the semantic gap only became visible after ablation reshaped the design"
        )
        issues.append(data)
    return json.dumps(
        {
            "satisfies_requirement": satisfies,
            "unresolved_issue_ids": list(unresolved),
            "issues": issues,
            "summary": "final review verdict",
        }
    )


def closure_script(resolved: bool, issue_ids=("R001",)):
    return json.dumps(
        {
            "issue_outcomes": [
                {
                    "issue_id": i,
                    "resolution": "RESOLVED" if resolved else "UNRESOLVED",
                    "note": "verified" if resolved else "not verified",
                }
                for i in issue_ids
            ],
            "new_issues": [],
            "summary": "closure",
        }
    )


def make_final_review_orchestrator(
    repo,
    authority_script,
    ui_answers,
    config=None,
    final_issues=None,
    second_closure_resolves=True,
):
    """CHANGE flow: intake gate (D001) -> design -> DESIGN blocker ->
    REVISION -> unresolved closure -> ABLATION -> FINAL_REVIEW raising a
    BLOCKING REQUIREMENT issue R002 -> authority check."""
    design_blocker = make_blocking_issue(1, title="Design gap in proposal")
    final_issues = final_issues if final_issues is not None else [requirement_blocker(2)]
    pi = FakePiAdapter(
        script={
            "discover": [discovery_with_candidates([candidate()])],
            "human_authority_check": [authority_script],
        }
    )
    codex = FakeCodexAdapter(
        script={
            "initial_review": [review_with_issues(design_blocker)],
            "closure_review": [
                closure_script(resolved=False),
                # second round (B201-A covered path re-enters REVISION)
                closure_script(resolved=second_closure_resolves, issue_ids=("R001", "R002")),
            ],
            "final_review": [
                final_review_script(*final_issues, satisfies=False, unresolved=["R001"])
            ],
        }
    )
    return Orchestrator.create(
        repository=repo,
        request="统一订单同步状态口径",
        config=config or Config(),
        pi=pi,
        codex=codex,
        ui=ScriptedUI(answers=ui_answers),
    )


# --- 1. B201-A: FINAL_REVIEW REQUIREMENT covered -> correction, not handoff ---


def test_b201a_final_review_covered_requirement_routes_to_correction(repo):
    config = Config(budgets=BudgetLimits(max_revision_rounds=2))
    o = make_final_review_orchestrator(
        repo, covered_result(issue_id="R002"), ui_answers=["1"], config=config
    )
    code = o.run()

    # No category-driven termination: the covered blocker consumed the
    # remaining correction budget and the session converged.
    assert code == int(ExitCode.DONE)
    assert o.state.phase == Phase.DONE
    assert o.state.status == SessionStatus.DONE

    events = events_of(o)
    assert any(e["event"] == "ISSUE_NEED_HUMAN" and e["issue_id"] == "R002" for e in events)
    covered = [
        e for e in events
        if e["event"] == "ISSUE_COVERED_BY_DECISION" and e["issue_id"] == "R002"
    ]
    assert covered and covered[0]["decision_ids"] == ["D001"]
    assert not any(e["event"] == "CONVERGENCE_GATE_CREATED" for e in events)
    assert not any(e["event"] == "SESSION_HUMAN_HANDOFF" for e in events)

    # Correction path actually ran: second revision + resolved closure.
    assert o.state.budgets.revision_used == 2
    assert o.state.budgets.ablation_used == 1
    assert o.state.budgets.human_interruptions_used == 1  # only the intake gate
    statuses = {i.id: i.status for i in o.store.load_issues().issues}
    assert statuses["R001"] == IssueStatus.RESOLVED
    assert statuses["R002"] == IssueStatus.RESOLVED
    assert o.store.read_text("final.md")


def test_b201a_final_review_covered_but_budgets_exhausted_is_budget_handoff(repo):
    """Covered outcome + exhausted correction budgets -> budget-driven
    handoff, never a category-driven one (B201-A boundary)."""
    o = make_final_review_orchestrator(
        repo, covered_result(issue_id="R002"), ui_answers=["1"]
    )
    code = o.run()
    assert code == int(ExitCode.HUMAN_HANDOFF)
    reason = o.state.handoff_reason or ""
    # The handoff is budget-driven, and the covered routing still ran.
    assert "convergence budget exhausted" in reason
    assert "REQUIREMENT" not in reason
    events = events_of(o)
    assert any(
        e["event"] == "ISSUE_COVERED_BY_DECISION" and e["issue_id"] == "R002"
        for e in events
    )
    assert (o.store.dir / "handoff.md").is_file()


# --- 2+3. B201-B: FINAL_REVIEW new decision -> Convergence Gate -> rebuild ---


def test_b201b_final_review_new_decision_opens_gate_and_rebuilds(repo):
    custom_text = "日报统计按精确匹配口径重算，历史保持现状并注明分类"
    o = make_final_review_orchestrator(
        repo,
        needs_new_result(issue_id="R002", source_issue_ids=["R002"]),
        ui_answers=["1", "0", custom_text],
    )
    code = o.run()

    assert code == int(ExitCode.DONE)
    events = events_of(o)
    conv = [e for e in events if e["event"] == "CONVERGENCE_GATE_CREATED"]
    assert conv and conv[0]["gate_id"] == "HG002"
    assert conv[0]["source_issue_ids"] == ["R002"]
    assert conv[0]["resume_semantics"] == "REQUIREMENT"

    # The gate opened FROM Final Review (previously impossible).
    gate_log = o.store.load_gate_log()
    gate = next(g for g in gate_log.gates if g.gate_id == "HG002")
    assert gate.category == GateCategory.CONVERGENCE
    assert gate.created_in_phase == "FINAL_REVIEW"
    assert gate.source_issue_ids == ["R002"]

    # Custom answer became ACTIVE, bumped the task revision, invalidated
    # the stale basis and rebuilt the design.
    decisions = o.store.load_decisions().decisions
    d002 = decisions[1]
    assert d002.decision_id == "D002"
    assert d002.source.value == "CUSTOM"
    assert d002.answer_text == custom_text
    assert o.state.task_revision == 3  # intake gate -> 2, convergence -> 3
    statuses = {i.id: i.status for i in o.store.load_issues().issues}
    assert statuses["R001"] == IssueStatus.SUPERSEDED
    assert statuses["R002"] == IssueStatus.SUPERSEDED
    assert o.store.load_proposal().based_on_task_revision == 3
    assert o.state.budgets.human_interruptions_used == 2
    # Audit order: final review -> flip -> gate -> rebuild. The intake
    # gate also incremented the revision earlier, so compare against the
    # LAST revision increment.
    names = event_names(o)
    assert names.index("FINAL_REVIEW_STARTED") < names.index("ISSUE_NEED_HUMAN")
    assert names.index("ISSUE_NEED_HUMAN") < names.index("CONVERGENCE_GATE_CREATED")
    last_increment = len(names) - 1 - names[::-1].index("TASK_REVISION_INCREMENTED")
    assert names.index("CONVERGENCE_GATE_CREATED") < last_increment
    assert o.store.read_text("final.md")


def test_b201b_final_review_option_answer_also_rebuilds(repo):
    o = make_final_review_orchestrator(
        repo,
        needs_new_result(issue_id="R002", source_issue_ids=["R002"]),
        ui_answers=["1", "1"],
    )
    assert o.run() == int(ExitCode.DONE)
    decisions = o.store.load_decisions().decisions
    assert decisions[1].selected_option_key == "precise"
    assert decisions[1].source.value == "OPTION"
    assert o.state.task_revision == 3


# --- 4. B201-C: FINAL_REVIEW convergence with exhausted Human budget ---


def test_b201c_final_review_new_decision_budget_exhausted_hands_off(repo):
    config = Config(budgets=BudgetLimits(max_human_interruptions=1))
    o = make_final_review_orchestrator(
        repo,
        needs_new_result(issue_id="R002", source_issue_ids=["R002"]),
        ui_answers=["1"],
        config=config,
    )
    code = o.run()
    assert code == int(ExitCode.HUMAN_HANDOFF)
    assert "Human interruption budget exhausted" in (o.state.handoff_reason or "")
    # No convergence gate was created (the intake gate stays the only
    # one); the handoff package carries the pending packet.
    gates = o.store.load_gate_log().gates
    assert [g.gate_id for g in gates] == ["HG001"]
    assert all(g.category != GateCategory.CONVERGENCE for g in gates)
    assert not any(e["event"] == "CONVERGENCE_GATE_CREATED" for e in events_of(o))
    assert o.state.budgets.human_interruptions_used == 1
    handoff = o.store.read_text("handoff.md")
    assert handoff and "R002" in handoff
    assert "precise" in handoff  # derivable suggested options preserved
    assert "cannot be resumed" in handoff


def test_b201_final_review_cannot_determine_fails_closed(repo):
    o = make_final_review_orchestrator(
        repo, cannot_determine_result(issue_id="R002"), ui_answers=["1"]
    )
    assert o.run() == int(ExitCode.HUMAN_HANDOFF)
    assert "could not be determined" in (o.state.handoff_reason or "")
    assert (o.store.dir / "handoff.md").is_file()


# ---------------------------------------------------------------------------
# B202: Problem Mode FACT convergence re-investigation
# ---------------------------------------------------------------------------


class DecisionCapturingPi(FakePiAdapter):
    """Records the ACTIVE decisions each investigate call receives."""

    def __init__(self, script=None):
        super().__init__(script)
        self.investigate_decisions: list[list[str]] = []

    def investigate(self, state, discovery=None, decisions=None):
        self.investigate_decisions.append(
            [d.decision_id for d in (decisions or [])]
        )
        return super().investigate(state, discovery=discovery, decisions=decisions)


def supported_investigation():
    return json.dumps(
        {
            "evidence": [
                {"description": "状态回写仅覆盖 initial 模式", "location": "src/sync/task_runner.py:120"},
            ],
            "hypotheses": [{"statement": "非 initial 模式跳过回写", "status": "CONFIRMED"}],
            "root_cause": "DONE 店在非 initial 模式下不回写 PENDING 行",
            "root_cause_status": "SUPPORTED",
            "causal_chain": ["DONE 判定", "模式分支跳过回写", "行残留 PENDING"],
            "missing_evidence": [],
            "human_candidates": [],
        }
    )


def problem_discovery():
    return json.dumps(
        {
            "task_kind": "PROBLEM",
            "current_state": "同步任务将 DONE 店的行残留为 PENDING",
            "relevant_components": ["src/sync/"],
            "existing_constraints": ["不删除历史数据"],
            "change_surface": ["src/sync/task_runner.py"],
            "unknowns": [],
            "human_candidates": [],
        }
    )


def make_problem_orchestrator(repo, authority_script, ui_answers, category="FACT"):
    pi = DecisionCapturingPi(
        script={
            "discover": [problem_discovery()],
            "investigate": [supported_investigation(), supported_investigation()],
            "human_authority_check": [authority_script],
        }
    )
    codex = FakeCodexAdapter(
        script={
            "initial_review": [review_with_issues(fact_blocker(1))],
        }
    )
    return Orchestrator.create(
        repository=repo,
        request="PROD-001 残留 PENDING 根因与修复",
        task_kind_explicit="problem",
        config=Config(),
        pi=pi,
        codex=codex,
        ui=ScriptedUI(answers=ui_answers),
    )


# --- 5. B202-A: FACT convergence decision re-enters INVESTIGATE ---


def test_b202a_problem_fact_convergence_reinvestigates_with_new_fact(repo):
    o = make_problem_orchestrator(
        repo,
        needs_new_result(issue_id="R001", category="FACT",
                         question="失败日志降级路径上的实际写入语义是什么？",
                         options=[
                             {"key": "atomic", "label": "失败即整批不落盘", "impact": "无脏数据"},
                             {"key": "partial", "label": "失败前已写行保留", "impact": "需对账"},
                         ],
                         recommendation="atomic",
                         source_issue_ids=["R001"]),
        ui_answers=["1"],
    )
    code = o.run()

    assert code == int(ExitCode.DONE)
    events = events_of(o)

    # The gate is CONVERGENCE-provenance but FACT-semantics.
    conv = [e for e in events if e["event"] == "CONVERGENCE_GATE_CREATED"]
    assert conv and conv[0]["resume_semantics"] == "FACT"
    gate = o.store.load_gate_log().gates[0]
    assert gate.category == GateCategory.CONVERGENCE
    assert gate.resume_semantics == "FACT"

    # task_revision invalidated, then INVESTIGATE (not INTAKE).
    names = [e["event"] for e in events]
    closed = names.index("HUMAN_GATE_CLOSED")
    incremented = names.index("TASK_REVISION_INCREMENTED")
    reinvestigate = names.index("INVESTIGATE_STARTED", closed)
    assert closed < incremented < reinvestigate
    assert names.count("INVESTIGATE_STARTED") == 2

    # The new ACTIVE FACT decision was passed into the re-investigation.
    assert o.pi.investigate_decisions[0] == []
    assert o.pi.investigate_decisions[1] == ["D001"]
    decisions = o.store.load_decisions().decisions
    assert decisions[0].selected_option_key == "atomic"
    assert o.state.task_revision == 2
    # Old fact-basis issue superseded by the revision.
    r001 = next(i for i in o.store.load_issues().issues if i.id == "R001")
    assert r001.status == IssueStatus.SUPERSEDED
    assert o.store.read_text("final.md")


# --- 6. B202-B: custom FACT decision does the same ---


def test_b202b_problem_custom_fact_convergence_reinvestigates(repo):
    custom_text = "失败即整批不落盘，且降级路径写审计日志留回执"
    o = make_problem_orchestrator(
        repo,
        needs_new_result(issue_id="R001", category="FACT",
                         question="失败日志降级路径上的实际写入语义是什么？",
                         source_issue_ids=["R001"]),
        ui_answers=["0", custom_text],
    )
    assert o.run() == int(ExitCode.DONE)
    decisions = o.store.load_decisions().decisions
    assert decisions[0].source.value == "CUSTOM"
    assert decisions[0].answer_text == custom_text
    # Custom FACT decision participates in re-investigation identically.
    assert o.pi.investigate_decisions[1] == ["D001"]
    names = event_names(o)
    assert names.count("INVESTIGATE_STARTED") == 2
    assert o.store.read_text("final.md")


# --- B202 mixed packets: conservative FACT rule ---


def test_b202_mixed_fact_and_requirement_packet_is_conservatively_fact(repo):
    """Any FACT question in a mixed convergence packet forces FACT
    semantics (deterministic conservative rule, spec B202 req 4)."""
    pi = DecisionCapturingPi(
        script={
            "discover": [problem_discovery()],
            "investigate": [supported_investigation(), supported_investigation()],
            "human_authority_check": [json.dumps({
                "outcomes": [
                    {
                        "issue_id": "R001",
                        "outcome": "NEEDS_NEW_HUMAN_DECISION",
                        "rationale": "fact vacuum",
                        "decision_candidate": {
                            "category": "FACT",
                            "question": "降级路径的写入语义是什么？",
                            "why_human": "生产语义。",
                            "options": [
                                {"key": "atomic", "label": "整批不落盘", "impact": "无脏数据"},
                                {"key": "partial", "label": "保留已写行", "impact": "需对账"},
                            ],
                            "recommendation": "atomic",
                            "source_issue_ids": ["R001"],
                        },
                    },
                    {
                        "issue_id": "R002",
                        "outcome": "NEEDS_NEW_HUMAN_DECISION",
                        "rationale": "requirement vacuum",
                        "decision_candidate": {
                            "category": "REQUIREMENT",
                            "question": "降级路径是否需要新增审计回执？",
                            "why_human": "业务取舍。",
                            "options": [
                                {"key": "yes", "label": "需要", "impact": "增加审计表"},
                                {"key": "no", "label": "不需要", "impact": "零新增"},
                            ],
                            "recommendation": None,
                            "source_issue_ids": ["R002"],
                        },
                    },
                ]
            })],
        }
    )
    r2 = make_blocking_issue(
        2, title="降级路径审计回执缺失", category=IssueCategory.REQUIREMENT,
        acceptance=["审计回执语义已定。"],
    )
    codex = FakeCodexAdapter(
        script={"initial_review": [review_with_issues(fact_blocker(1), r2)]}
    )
    o = Orchestrator.create(
        repository=repo,
        request="PROD-001 残留 PENDING 根因与修复",
        task_kind_explicit="problem",
        config=Config(),
        pi=pi,
        codex=codex,
        ui=ScriptedUI(answers=["1", "2"]),
    )
    assert o.run() == int(ExitCode.DONE)
    gate = o.store.load_gate_log().gates[0]
    assert gate.category == GateCategory.CONVERGENCE
    assert gate.resume_semantics == "FACT"  # any-FACT forces FACT
    names = event_names(o)
    assert names.count("INVESTIGATE_STARTED") == 2


# --- 8. B202-C: Problem Mode + REQUIREMENT convergence -> INTAKE ---


def test_b202c_problem_requirement_convergence_goes_intake(repo):
    pi = DecisionCapturingPi(
        script={
            "discover": [problem_discovery()],
            "investigate": [supported_investigation()],
            "human_authority_check": [
                needs_new_result(issue_id="R001", category="REQUIREMENT",
                                 question="修复范围是否包含展示统计统一？",
                                 source_issue_ids=["R001"])
            ],
        }
    )
    codex = FakeCodexAdapter(
        script={
            # first review raises the REQUIREMENT blocker, second is clean
            "initial_review": [
                review_with_issues(requirement_blocker(1)),
            ],
        }
    )
    o = Orchestrator.create(
        repository=repo,
        request="PROD-001 残留 PENDING 根因与修复",
        task_kind_explicit="problem",
        config=Config(),
        pi=pi,
        codex=codex,
        ui=ScriptedUI(answers=["1"]),
    )
    assert o.run() == int(ExitCode.DONE)
    gate = o.store.load_gate_log().gates[0]
    assert gate.resume_semantics == "REQUIREMENT"
    # INVESTIGATE ran exactly once; the rebuild went through INTAKE.
    names = event_names(o)
    assert names.count("INVESTIGATE_STARTED") == 1
    closed = names.index("HUMAN_GATE_CLOSED")
    assert "INVESTIGATE_STARTED" not in names[closed:]
    assert "INTAKE_STARTED" in names[closed:]


# --- compute_resume_semantics determinism ---


def q(category, key_offset=0):
    return GateQuestion(
        decision_key=f"K-{category}-{key_offset}",
        category=category,
        question=f"Q {category} {key_offset}?",
        options=[
            GateOption(key="a", label="A"),
            GateOption(key="b", label="B"),
        ],
    )


def test_compute_resume_semantics_deterministic_rules():
    assert compute_resume_semantics([q("FACT")]) == "FACT"
    assert compute_resume_semantics([q("REQUIREMENT")]) == "REQUIREMENT"
    assert compute_resume_semantics([q("TRADE_OFF")]) == "TRADE_OFF"
    # Any FACT forces FACT (conservative mixed rule).
    assert compute_resume_semantics([q("REQUIREMENT"), q("FACT")]) == "FACT"
    assert compute_resume_semantics([q("FACT"), q("SCOPE"), q("TRADE_OFF")]) == "FACT"
    # Mixed non-FACT -> MIXED (resumes through INTAKE).
    assert compute_resume_semantics([q("REQUIREMENT"), q("TRADE_OFF")]) == "MIXED"


# ---------------------------------------------------------------------------
# B203: candidate packet integrity
# ---------------------------------------------------------------------------


def make_candidate_flow(repo, authority_script):
    """Minimal CHANGE flow: review raises one BLOCKING REQUIREMENT issue;
    the authority check returns whatever packet the test shaped."""
    pi = FakePiAdapter(
        script={
            "human_authority_check": [authority_script],
        }
    )
    codex = FakeCodexAdapter(
        script={"initial_review": [review_with_issues(requirement_blocker(1))]}
    )
    return Orchestrator.create(
        repository=repo,
        request="统一订单同步状态口径",
        config=Config(),
        pi=pi,
        codex=codex,
        ui=ScriptedUI(answers=[]),
    )


def assert_fail_closed_before_gate(repo, authority_script, reason_fragment):
    o = make_candidate_flow(repo, authority_script)
    code = o.run()
    assert code == int(ExitCode.HUMAN_HANDOFF)
    assert reason_fragment in (o.state.handoff_reason or "")
    # No malformed gate persisted, no Human interruption consumed.
    assert o.store.load_gate_log().current is None
    assert o.state.budgets.human_interruptions_used == 0
    # The issue was never downgraded/reclassified by the invalid packet.
    r001 = next(i for i in o.store.load_issues().issues if i.id == "R001")
    assert r001.status == IssueStatus.NEED_HUMAN
    assert r001.category == IssueCategory.REQUIREMENT
    # Structured handoff explains the invalid authority packet boundary.
    handoff = o.store.read_text("handoff.md")
    assert handoff and "R001" in handoff
    assert reason_fragment in handoff
    return o


# --- 9. unknown source issue id outside the batch ---


def test_b203_unknown_source_issue_id_fails_closed(repo):
    # Includes the outcome issue, but also references an id that is not
    # part of the current authority-check batch.
    assert_fail_closed_before_gate(
        repo,
        needs_new_result(issue_id="R001", source_issue_ids=["R001", "R999"]),
        "outside the current authority-check batch",
    )


def test_b203_source_excluding_outcome_issue_fails_closed(repo):
    # Batch of one; the candidate points somewhere else entirely.
    assert_fail_closed_before_gate(
        repo,
        needs_new_result(issue_id="R001", source_issue_ids=["R999"]),
        "do not include the outcome issue R001",
    )


# --- 10. outcome issue missing from candidate provenance ---


def test_b203_outcome_issue_not_in_provenance_fails_closed(repo):
    r2 = make_blocking_issue(
        2, title="第二个需求阻塞", category=IssueCategory.REQUIREMENT,
        acceptance=["语义已定。"],
    )
    authority = json.dumps(
        {
            "outcomes": [
                {
                    "issue_id": "R001",
                    "outcome": "NEEDS_NEW_HUMAN_DECISION",
                    "rationale": "vacuum",
                    "decision_candidate": {
                        "category": "REQUIREMENT",
                        "question": "现有口径如何统一？",
                        "why_human": "业务语义。",
                        "options": [
                            {"key": "a", "label": "A", "impact": "x"},
                            {"key": "b", "label": "B", "impact": "y"},
                        ],
                        "recommendation": "a",
                        # R002 belongs to the batch, but the outcome is for
                        # R001 — provenance must include the outcome issue.
                        "source_issue_ids": ["R002"],
                    },
                },
                {
                    "issue_id": "R002",
                    "outcome": "CANNOT_DETERMINE",
                    "rationale": "unreachable in this test",
                },
            ]
        }
    )
    pi = FakePiAdapter(script={"human_authority_check": [authority]})
    codex = FakeCodexAdapter(
        script={"initial_review": [review_with_issues(requirement_blocker(1), r2)]}
    )
    o = Orchestrator.create(
        repository=repo,
        request="统一订单同步状态口径",
        config=Config(),
        pi=pi,
        codex=codex,
        ui=ScriptedUI(answers=[]),
    )
    assert o.run() == int(ExitCode.HUMAN_HANDOFF)
    assert "do not include the outcome issue R001" in (o.state.handoff_reason or "")
    assert o.store.load_gate_log().current is None
    assert o.state.budgets.human_interruptions_used == 0
    statuses = {i.id: i.status for i in o.store.load_issues().issues}
    assert statuses["R001"] == IssueStatus.NEED_HUMAN
    assert statuses["R002"] == IssueStatus.NEED_HUMAN


# --- 11. category=CONVERGENCE is not a decision semantic ---


def test_b203_convergence_category_rejected(repo):
    assert_fail_closed_before_gate(
        repo,
        needs_new_result(issue_id="R001", category="CONVERGENCE"),
        "not a Human decision semantic category",
    )


# --- 12+13. duplicate option keys (exact and normalized) ---


def test_b203_duplicate_option_keys_rejected(repo):
    options = [
        {"key": "fix", "label": "修复方案A", "impact": "x"},
        {"key": "fix", "label": "修复方案B", "impact": "y"},
    ]
    assert_fail_closed_before_gate(
        repo,
        needs_new_result(issue_id="R001", options=options, recommendation="fix"),
        "duplicate option keys",
    )


def test_b203_duplicate_normalized_option_keys_rejected(repo):
    options = [
        {"key": "fix", "label": "修复方案A", "impact": "x"},
        {"key": "FIX ", "label": "修复方案B", "impact": "y"},
    ]
    assert_fail_closed_before_gate(
        repo,
        needs_new_result(issue_id="R001", options=options, recommendation=None),
        "duplicate option keys",
    )


def test_b203_reserved_selector_option_key_rejected(repo):
    options = [
        {"key": "custom", "label": "伪装自定义", "impact": "x"},
        {"key": "real", "label": "真实选项", "impact": "y"},
    ]
    assert_fail_closed_before_gate(
        repo,
        needs_new_result(issue_id="R001", options=options, recommendation=None),
        "reserved custom-decision selector",
    )


def test_b203_empty_option_key_rejected(repo):
    options = [
        {"key": "  ", "label": "空键", "impact": "x"},
        {"key": "real", "label": "真实选项", "impact": "y"},
    ]
    assert_fail_closed_before_gate(
        repo,
        needs_new_result(issue_id="R001", options=options, recommendation=None),
        "non-empty key and label",
    )


# --- 14. duplicate decision_key across candidates ---


def test_b203_duplicate_decision_key_across_candidates_rejected(repo):
    r2 = make_blocking_issue(
        2, title="第二个需求阻塞", category=IssueCategory.REQUIREMENT,
        acceptance=["语义已定。"],
    )
    same_question = "现有口径如何统一？"
    authority = json.dumps(
        {
            "outcomes": [
                {
                    "issue_id": "R001",
                    "outcome": "NEEDS_NEW_HUMAN_DECISION",
                    "rationale": "vacuum 1",
                    "decision_candidate": {
                        "category": "REQUIREMENT",
                        "question": same_question,
                        "why_human": "业务语义。",
                        "options": [
                            {"key": "a1", "label": "A1", "impact": "x"},
                            {"key": "b1", "label": "B1", "impact": "y"},
                        ],
                        "recommendation": "a1",
                        "source_issue_ids": ["R001"],
                    },
                },
                {
                    "issue_id": "R002",
                    "outcome": "NEEDS_NEW_HUMAN_DECISION",
                    "rationale": "vacuum 2",
                    "decision_candidate": {
                        # Same category+question -> identical decision_key,
                        # different option packet.
                        "category": "REQUIREMENT",
                        "question": same_question,
                        "why_human": "业务语义。",
                        "options": [
                            {"key": "a2", "label": "A2", "impact": "x"},
                            {"key": "b2", "label": "B2", "impact": "y"},
                        ],
                        "recommendation": "a2",
                        "source_issue_ids": ["R002"],
                    },
                },
            ]
        }
    )
    pi = FakePiAdapter(script={"human_authority_check": [authority]})
    codex = FakeCodexAdapter(
        script={"initial_review": [review_with_issues(requirement_blocker(1), r2)]}
    )
    o = Orchestrator.create(
        repository=repo,
        request="统一订单同步状态口径",
        config=Config(),
        pi=pi,
        codex=codex,
        ui=ScriptedUI(answers=[]),
    )
    assert o.run() == int(ExitCode.HUMAN_HANDOFF)
    assert "duplicate decision_key" in (o.state.handoff_reason or "")
    assert o.store.load_gate_log().current is None
    assert o.state.budgets.human_interruptions_used == 0
    statuses = {i.id: i.status for i in o.store.load_issues().issues}
    assert statuses["R001"] == IssueStatus.NEED_HUMAN
    assert statuses["R002"] == IssueStatus.NEED_HUMAN


# --- shared GateQuestion model boundary (intake gates inherit too) ---


def test_gate_question_rejects_duplicate_option_keys():
    with pytest.raises(ValidationError, match="duplicate option keys"):
        GateQuestion(
            decision_key="K",
            category="REQUIREMENT",
            question="Q?",
            options=[
                GateOption(key="fix", label="A"),
                GateOption(key="fix", label="B"),
            ],
        )
    with pytest.raises(ValidationError, match="duplicate option keys"):
        GateQuestion(
            decision_key="K",
            category="REQUIREMENT",
            question="Q?",
            options=[
                GateOption(key="fix", label="A"),
                GateOption(key="Fix-", label="B"),  # normalizes to "fix"
            ],
        )


def test_intake_candidate_with_duplicate_keys_is_suppressed(repo):
    """Intake path fails closed too: the malformed candidate is
    suppressed (never asked), the session continues without it."""
    dup = candidate(
        question="重复键候选？",
        options=[
            {"key": "same", "label": "选项A", "impact": "x"},
            {"key": "same", "label": "选项B", "impact": "y"},
        ],
    )
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates([dup])]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=[]))
    assert o.run() == int(ExitCode.DONE)
    events = events_of(o)
    suppressed = [
        e for e in events
        if e["event"] == "HUMAN_CANDIDATE_SUPPRESSED"
        and "duplicate option keys" in e.get("reason", "")
    ]
    assert suppressed
    assert o.store.load_gate_log().current is None
    assert o.state.budgets.human_interruptions_used == 0


# ---------------------------------------------------------------------------
# N201: handoff.md minimal deterministic fallback
# ---------------------------------------------------------------------------


def test_n201_handoff_render_failure_writes_minimal_fallback(repo, monkeypatch):
    import agent_review.rendering as rendering_mod

    def boom(*args, **kwargs):
        raise RuntimeError("render explosion")

    monkeypatch.setattr(rendering_mod, "render_handoff", boom)
    o = make_candidate_flow(repo, cannot_determine_result())
    code = o.run()

    # The authoritative terminal state is untouched by the failure.
    assert code == int(ExitCode.HUMAN_HANDOFF)
    assert o.state.phase == Phase.HUMAN_HANDOFF
    assert o.state.status == SessionStatus.HUMAN_HANDOFF

    # The minimal deterministic fallback was written.
    minimal = o.store.read_text("handoff.md")
    assert minimal and "# Human Handoff" in minimal
    assert o.state.session_id in minimal
    assert "could not be determined" in minimal  # sanitized reason survives
    assert "R001" in minimal  # blocking issue ids readable
    assert "cannot be resumed in place" in minimal
    events = events_of(o)
    written = [e for e in events if e["event"] == "HANDOFF_WRITTEN"]
    assert written and written[-1].get("fallback") == "minimal"


def test_n201_total_write_failure_keeps_handoff_authoritative(repo, monkeypatch):
    import agent_review.rendering as rendering_mod

    def boom(*args, **kwargs):
        raise RuntimeError("render explosion")

    monkeypatch.setattr(rendering_mod, "render_handoff", boom)
    o = make_candidate_flow(repo, cannot_determine_result())

    original_write = o.store.write_text

    def failing_write(name, text):
        if name == "handoff.md":
            raise OSError("disk full")
        return original_write(name, text)

    monkeypatch.setattr(o.store, "write_text", failing_write)
    code = o.run()

    assert code == int(ExitCode.HUMAN_HANDOFF)
    assert o.state.phase == Phase.HUMAN_HANDOFF
    assert o.state.status == SessionStatus.HUMAN_HANDOFF
    events = events_of(o)
    assert any(e["event"] == "HANDOFF_WRITE_FAILED" for e in events)
    # The state.json persisted before the write attempts is the truth.
    assert (o.store.dir / "state.json").is_file()


# ---------------------------------------------------------------------------
# N202: authority-check prompt semantics
# ---------------------------------------------------------------------------


def test_n202_authority_check_prompt_options_are_suggestions():
    from pathlib import Path

    from agent_review.agents.pi import PROMPTS_DIR

    text = (PROMPTS_DIR / "human_authority_check.md").read_text(encoding="utf-8")
    # The contradictory instruction is gone.
    assert "Do not invent options the Human never saw" not in text
    # Options may be proposed, never claimed Human-approved; the Human
    # can reject all of them and use the custom-decision path.
    assert "suggestions only" in text
    assert "may reject all of them" in text
    assert "custom-decision path" in text
    # RC2 packet rules are stated for the agent.
    assert "never" in text and "CONVERGENCE" in text
    assert "unique" in text
    assert "MUST include the issue" in text


def test_final_review_convergence_handoff_written_from_final_review(repo):
    """B201 handoff from FINAL_REVIEW explains the boundary (D16 analog)."""
    config = Config(budgets=BudgetLimits(max_human_interruptions=1))
    o = make_final_review_orchestrator(
        repo, cannot_determine_result(issue_id="R002"), ui_answers=["1"], config=config
    )
    assert o.run() == int(ExitCode.HUMAN_HANDOFF)
    assert "could not be determined" in (o.state.handoff_reason or "")
    handoff = o.store.read_text("handoff.md")
    assert handoff and "R002" in handoff
    assert "cannot be resumed" in handoff
