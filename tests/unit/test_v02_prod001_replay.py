"""V0.2 real-case acceptance: PROD-001 deterministic replay.

Permanent regression modeled on
docs/V0_1_CASE_AUDIT_20260911_PROD001_HANDOFF.md — the first post-V0.1
real Shopify session (20260911-112256-4409) terminated with
HUMAN_HANDOFF because R001 was categorized BLOCKING + REQUIREMENT while
an ACTIVE Human Decision (D001 full_doc5) had already placed the
disputed §5.4 display/statistics scope inside the requirement.

Spec: docs/V0_2_HUMAN_DECISION_CONVERGENCE_SPEC.md section 14.

Critical acceptance condition:

    D001 already covers display/statistics unification
    + R001 emitted as BLOCKING + REQUIREMENT claiming the proposal
      omitted that scope
    -> V0.2 must NOT immediately HUMAN_HANDOFF merely because the
       Reviewer used category REQUIREMENT.

Both replays use the same shape as the real session: one intake gate
(3 decisions), a proposal on task_revision 2, and an initial review
raising R001 (REQUIREMENT) + R002 (DESIGN) + R003 (REGRESSION).
"""

from __future__ import annotations

import json

from agent_review.agents.fakes import FakeCodexAdapter, FakePiAdapter
from agent_review.config import Config
from agent_review.models import (
    ExitCode,
    IssueCategory,
    IssueStatus,
    Phase,
    SessionStatus,
)
from agent_review.orchestrator import Orchestrator

from tests.unit.test_m3_human_gate import ScriptedUI

PROD001_CANDIDATES = [
    {
        "category": "SCOPE",
        "question": "修复范围档位？",
        "why": "影响修复规模与上线风险，业务语义由人决定。",
        "options": [
            {
                "key": "full_doc5",
                "label": "按问题单§5全量实施（阻止新增+在营查询精确匹配兼容+展示统计统一）",
                "impact": "覆盖§5.4展示/统计口径盘点",
            },
            {"key": "minimal", "label": "仅修复新增路径", "impact": "§5.4遗留"},
        ],
        "recommendation": "full_doc5",
        "source": "DISCOVER",
    },
    {
        "category": "FACT",
        "question": "上线前是否先核实残留？",
        "why": "依赖生产数据，仓库不可知。",
        "options": [
            {"key": "verify_before", "label": "先跑核查SQL留回执", "impact": "验收A08"},
            {"key": "verify_after", "label": "上线后抽查", "impact": "风险后置"},
        ],
        "recommendation": "verify_before",
        "source": "DISCOVER",
    },
    {
        "category": "TRADE_OFF",
        "question": "历史『DONE店+PENDING』行处置基调？",
        "why": "写入策略是业务取舍。",
        "options": [
            {"key": "compat_ignore", "label": "保留原始行，精确匹配忽略，零写入", "impact": "零迁移"},
            {"key": "rewrite", "label": "批量重写历史行", "impact": "批量写入风险"},
        ],
        "recommendation": "compat_ignore",
        "source": "DISCOVER",
    },
]


def prod001_discovery():
    return json.dumps(
        {
            "task_kind": "PROBLEM",
            "current_state": "同步任务将 DONE 店的行残留为 PENDING",
            "relevant_components": ["src/sync/", "src/report/"],
            "existing_constraints": ["不删除历史数据"],
            "change_surface": ["src/sync/task_runner.py", "src/report/daily.py"],
            "unknowns": [],
            "human_candidates": PROD001_CANDIDATES,
        }
    )


def prod001_supported_investigation():
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


def prod001_initial_review():
    """R001-R004 exactly as the real session raised them."""
    return json.dumps(
        {
            "issues": [
                {
                    "id": "R001",
                    "category": "REQUIREMENT",
                    "severity": "BLOCKING",
                    "title": "遗漏现有全量日报，§5.4 与 A07 未覆盖",
                    "problem": "proposal 未覆盖 DailySyncReportRenderer 链路的展示统计统一。",
                    "impact": "全量日报口径与修复口径不一致。",
                    "acceptance": ["设计覆盖 §5.4 展示/统计统一（A07）。"],
                    "evidence": ["proposal.md 无日报章节"],
                },
                {
                    "id": "R002",
                    "category": "DESIGN",
                    "severity": "BLOCKING",
                    "title": "兜底和修复口径绕开门禁",
                    "problem": "与 compat_ignore 决策冲突。",
                    "impact": "门禁失效。",
                    "acceptance": ["兜底与主口径一致。"],
                },
                {
                    "id": "R003",
                    "category": "REGRESSION",
                    "severity": "BLOCKING",
                    "title": "A06 未考虑非 initial 模式的查询谓词写入",
                    "problem": "验证计划缺口。",
                    "impact": "回归风险。",
                    "acceptance": ["A06 覆盖非 initial 模式。"],
                },
                {
                    "id": "R004",
                    "category": "FACT",
                    "severity": "NON_BLOCKING",
                    "title": "非阻塞事实备注",
                    "problem": "备注。",
                    "impact": "无。",
                    "acceptance": [],
                },
            ],
            "summary": "3 blocking",
        }
    )


def authority_covered():
    """The correct judgment the real session never got the chance to make."""
    return json.dumps(
        {
            "outcomes": [
                {
                    "issue_id": "R001",
                    "outcome": "COVERED_BY_ACTIVE_DECISION",
                    "referenced_decision_ids": ["D001"],
                    "rationale": (
                        "D001 (full_doc5) 的选项标签与 task scope 第3条已把"
                        "『展示/统计口径盘点（§5.4）』纳入已定范围；R001 是"
                        "设计未覆盖已定需求的实现缺口，而非缺失人类语义。"
                    ),
                }
            ]
        }
    )


def authority_needs_new():
    return json.dumps(
        {
            "outcomes": [
                {
                    "issue_id": "R001",
                    "outcome": "NEEDS_NEW_HUMAN_DECISION",
                    "rationale": "既有决策未定义全量日报的统计口径。",
                    "decision_candidate": {
                        "category": "REQUIREMENT",
                        "question": "现有全量日报在 full_doc5 口径下如何统一展示统计（§5.4/A07）？",
                        "why_human": "日报统计口径是业务语义，仓库与 D001-D003 均未定义。",
                        "options": [
                            {"key": "recompute", "label": "日报统计按精确匹配口径重算", "impact": "口径统一"},
                            {"key": "annotate", "label": "保持现状并注明历史分类", "impact": "零改动"},
                            {"key": "scope_out", "label": "日报移出本次范围", "impact": "§5.4 遗留"},
                        ],
                        "recommendation": "recompute",
                        "source_issue_ids": ["R001"],
                    },
                }
            ]
        }
    )


def make_replay(repo, authority_script, ui_answers):
    pi = FakePiAdapter(
        script={
            "discover": [prod001_discovery()],
            "investigate": [prod001_supported_investigation()],
            "human_authority_check": [authority_script],
        }
    )
    codex = FakeCodexAdapter(script={"initial_review": [prod001_initial_review()]})
    return Orchestrator.create(
        repository=repo,
        request="PROD-001全量DONE店残留PENDING根因与修复方案",
        task_kind_explicit="problem",
        config=Config(),
        pi=pi,
        codex=codex,
        ui=ScriptedUI(answers=ui_answers),
    )


def events_of(o) -> list[dict]:
    return [
        json.loads(line)
        for line in (o.store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]


# --- Replay 1: R001 covered by D001 -> Revision, not termination ------------------


def test_prod001_replay_covered_requirement_continues_to_done(repo):
    # First pass answers the 3-question intake gate with 都按推荐
    # (mirrors the real session's D001-D003 application).
    o = make_replay(repo, authority_covered(), ui_answers=["都按推荐"])
    code = o.run()

    # THE critical acceptance: no HUMAN_HANDOFF for R001's REQUIREMENT
    # category; revision/ablation budgets are usable again.
    assert code == int(ExitCode.DONE)
    assert o.state.phase == Phase.DONE
    assert o.state.status == SessionStatus.DONE

    events = events_of(o)
    assert any(e["event"] == "ISSUE_NEED_HUMAN" and e["issue_id"] == "R001" for e in events)
    covered = [e for e in events if e["event"] == "ISSUE_COVERED_BY_DECISION"]
    assert covered and covered[0]["decision_ids"] == ["D001"]
    assert not any(e["event"] == "CONVERGENCE_GATE_CREATED" for e in events)
    assert not any(e["event"] == "SESSION_HUMAN_HANDOFF" for e in events)

    # Intake gate decisions applied as in the real session.
    decisions = {d.decision_id: d for d in o.store.load_decisions().decisions}
    assert decisions["D001"].selected_option_key == "full_doc5"
    assert decisions["D003"].selected_option_key == "compat_ignore"

    # Reviewer provenance preserved (auditability), issue resolved via
    # the normal correction path.
    issues = {i.id: i for i in o.store.load_issues().issues}
    assert issues["R001"].category == IssueCategory.REQUIREMENT
    assert issues["R001"].provenance == "INITIAL_REVIEW"
    assert issues["R001"].status == IssueStatus.RESOLVED
    assert issues["R001"].covered_by_decisions == ["D001"]
    assert issues["R002"].status == IssueStatus.RESOLVED
    assert issues["R003"].status == IssueStatus.RESOLVED

    # Budget truth: budgets actually used, no gate burned on R001.
    assert o.state.budgets.revision_used == 1
    assert o.state.budgets.ablation_used == 0
    assert o.state.budgets.human_interruptions_used == 1
    assert o.store.read_text("final.md")


# --- Replay 2: genuinely new downstream decision -> Convergence Gate ---------------


def test_prod001_replay_new_decision_convergence_gate_resumes(repo):
    custom_text = "日报统计按精确匹配口径重算，历史保持现状并注明分类"
    o = make_replay(
        repo, authority_needs_new(), ui_answers=["都按推荐", "0", custom_text]
    )
    code = o.run()

    assert code == int(ExitCode.DONE)
    events = events_of(o)
    conv = [e for e in events if e["event"] == "CONVERGENCE_GATE_CREATED"]
    assert conv and conv[0]["source_issue_ids"] == ["R001"]
    assert conv[0]["gate_id"] == "HG002"  # HG001 was the intake gate

    # Human input stayed authoritative inside the SAME session — no
    # manual copy-paste into a new session (spec 15).
    decisions = o.store.load_decisions().decisions
    d004 = decisions[3]
    assert d004.decision_id == "D004"
    assert d004.source.value == "CUSTOM"
    assert d004.answer_text == custom_text

    # Same task-revision/invalidation semantics as offered options.
    assert o.state.task_revision == 3  # 1 -> intake gate -> convergence gate
    issues = {i.id: i for i in o.store.load_issues().issues}
    assert issues["R001"].status == IssueStatus.SUPERSEDED
    assert issues["R002"].status == IssueStatus.SUPERSEDED
    assert issues["R003"].status == IssueStatus.SUPERSEDED
    assert o.store.load_proposal().based_on_task_revision == 3
    assert o.state.budgets.human_interruptions_used == 2
    assert o.store.read_text("final.md")
    # The custom decision is a confirmed session fact in the rebuilt
    # contract and appears in the standalone final design.
    assert any(custom_text in line for line in o.store.load_contract().confirmed_decisions)
    assert custom_text in o.store.read_text("final.md")


def test_prod001_replay_convergence_budget_exhausted_hands_off_structured(repo):
    """Intake gate + convergence candidate would need a 3rd interruption:
    default budget 2 -> HG001 + HG002 both consumed in the real run, so
    here we burn both budgets before the review NEED_HUMAN."""
    # answers: 3 intake questions (都按推荐 answers all 3), then the
    # convergence gate (HG002) is answered, then a SECOND review raises
    # a new REQUIREMENT blocker -> authority check script exhausted ->
    # default CANNOT_DETERMINE -> structured handoff.
    pi_script_needs_new = authority_needs_new()
    pi = FakePiAdapter(
        script={
            "discover": [prod001_discovery()],
            "investigate": [prod001_supported_investigation()],
            # First check: NEEDS_NEW (opens HG002). Second check falls
            # back to the default CANNOT_DETERMINE.
            "human_authority_check": [pi_script_needs_new],
        }
    )
    second_review = json.dumps(
        {
            "issues": [
                {
                    "id": "R005",
                    "category": "REQUIREMENT",
                    "severity": "BLOCKING",
                    "title": "第二轮复审发现新的口径冲突",
                    "problem": "重算后的统计与既有报表冲突。",
                    "impact": "口径再次不一致。",
                    "acceptance": ["冲突解决。"],
                }
            ],
            "summary": "1 blocking",
        }
    )
    codex = FakeCodexAdapter(
        script={"initial_review": [prod001_initial_review(), second_review]}
    )
    o = Orchestrator.create(
        repository=repo,
        request="PROD-001全量DONE店残留PENDING根因与修复方案",
        task_kind_explicit="problem",
        config=Config(),
        pi=pi,
        codex=codex,
        ui=ScriptedUI(answers=["都按推荐", "1"]),
    )
    code = o.run()
    assert code == int(ExitCode.HUMAN_HANDOFF)
    assert o.state.budgets.human_interruptions_used == 2
    handoff = o.store.read_text("handoff.md")
    assert handoff and "R005" in handoff
    assert "Why the workflow stopped" in handoff
    # Resumability boundary is explicit (spec 8).
    assert "cannot be resumed" in handoff
