"""V0.3 deterministic case replays of the two 20260914 real sessions.

Both fixtures are ABSTRACTED from the real audits: they keep the
structural failure pattern that motivated V0.3 and strip all
domain-specific business terms (no platform names, no product codes).
The replays verify the GENERIC abstractions, not the original wording.

Case 1 — Composite (source: 20260914-094512-84fb,
docs/V0_2_CASE_AUDIT_20260914_RECONCILE_HANDOFF.md):
    a request mixing several independently decidable and independently
    deliverable concerns entered normal design convergence and died in
    HUMAN_HANDOFF after burning the interruption budget on chained
    gates. V0.3 must stop it at the Scope Guard, before DESIGN, with
    actionable decomposition guidance.

Case 2 — Bounded convergence (source: 20260914-165600-c454,
docs/V0_2_CASE_AUDIT_20260914_PROD005_HANDOFF.md):
    a bounded defect-fix design whose Human decisions were settled, but
    one persistent engineering blocker (evidence quality) burned the
    whole revision+ablation ladder and a late review blocker arrived at
    zero budget -> ambiguous HUMAN_HANDOFF. V0.3 must:
      - batch the independent intake questions into ONE gate;
      - route the local blocker through FOCUSED_REVISION;
      - never auto-trigger ABLATION;
      - keep the authority check classifying the blocker as covered
        (engineering gap, Human authority settled);
      - terminate as DESIGN_NOT_APPROVED — not NEEDS_HUMAN_DECISION —
        with the residual close conditions as hard inputs.
"""

from __future__ import annotations

import json

from agent_review.agents.fakes import FakeCodexAdapter, FakePiAdapter, make_blocking_issue
from agent_review.models import (
    CorrectionAction,
    ExitCode,
    FocusArea,
    IssueCategory,
    IssueSeverity,
    IssueStatus,
    Phase,
    SessionStatus,
)

from tests.unit.test_m3_human_gate import (
    ScriptedUI,
    default_proposal_dict,
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


# ===========================================================================
# Case 1 — Composite: DECOMPOSITION_REQUIRED before DESIGN
# ===========================================================================

COMPOSITE_REQUEST = (
    "为数据同步链路建设双源比对能力：确定比对口径语义、实现比对引擎、"
    "设计定时调度与发布回滚、配置凭证与紧急开关、输出报表并通知"
)

COMPOSITE_SCOPE_VERDICT = json.dumps(
    {
        "verdict": "DECOMPOSITION_REQUIRED",
        "independent_outcomes": [
            "双源比对口径契约（语义、时间模型、边界口径）",
            "比对引擎实现（输入适配、执行、结果表示）",
            "运维化（调度、发布、凭证、告警、紧急开关）",
        ],
        "decision_clusters": ["业务语义", "引擎结构", "运维边界"],
        "change_surfaces": ["对比工具（新建）", "调度配置（新建）", "通知渠道（新建）"],
        "external_unknowns": ["对端数据口径证明材料"],
        "rationale": (
            "请求包含三个可独立收敛、独立验收的工程产出（口径契约、"
            "引擎实现、运维化），决策簇互相独立，单会话无法在有限"
            "预算内收敛为一个可实施设计"
        ),
        "decomposition": [
            {
                "title": "比对口径契约",
                "goal": "确定双源比对语义、时间模型与无法证明时的处置规则，产出数据契约",
                "inputs": ["原始请求", "双端表结构与口径说明"],
                "non_goals": ["引擎实现", "调度与发布"],
                "dependencies": [],
            },
            {
                "title": "比对引擎",
                "goal": "按契约实现比对引擎（取数、执行、差异表示）",
                "inputs": ["比对口径契约会话的结论"],
                "non_goals": ["口径语义变更", "运维化"],
                "dependencies": ["比对口径契约"],
            },
            {
                "title": "运维化",
                "goal": "调度、发布回滚、凭证注入、告警与紧急开关设计",
                "inputs": ["比对引擎会话的结论"],
                "non_goals": ["引擎重设计"],
                "dependencies": ["比对引擎"],
            },
        ],
    }
)


def test_composite_case_stops_before_design_with_decomposition(repo):
    """84fb replay: the composite request must die at the Scope Guard —
    no chained intake gates, no design budget, actionable split."""
    # The discovery would have produced several independent human
    # candidates under V0.2 (the chained-gate pattern); V0.3 never asks
    # them because the scope verdict terminates first.
    discovery_with_gates_would_have_asked = discovery_with_candidates(
        [
            {
                "category": "SCOPE",
                "question": "比对结果的输出载体？",
                "why": "交付形态影响后续所有设计",
                "options": [
                    {"key": "file_export", "label": "文件导出", "impact": "轻量"},
                    {"key": "service_api", "label": "服务接口", "impact": "重"},
                ],
                "recommendation": "file_export",
                "source": "DISCOVER",
            },
            {
                "category": "FACT",
                "question": "对端数据源的直接访问方式？",
                "why": "连接形态决定引擎结构",
                "options": [
                    {"key": "direct", "label": "直连", "impact": "需凭证"},
                    {"key": "export_file", "label": "导出文件", "impact": "延迟"},
                ],
                "recommendation": "direct",
                "source": "DISCOVER",
            },
            {
                "category": "TRADE_OFF",
                "question": "全历史比对的取数策略？",
                "why": "成本与完整性权衡",
                "options": [
                    {"key": "single", "label": "单次全量", "impact": "受接口限制"},
                    {"key": "windowed", "label": "分窗口", "impact": "慢"},
                ],
                "recommendation": "single",
                "source": "DISCOVER",
            },
            {
                "category": "SCOPE",
                "question": "实现载体与部署形态？",
                "why": "独立于前三问",
                "options": [
                    {"key": "standalone", "label": "独立程序", "impact": "先跑通"},
                    {"key": "scheduled", "label": "接入调度平台", "impact": "重运维"},
                ],
                "recommendation": "standalone",
                "source": "DISCOVER",
            },
        ]
    )
    pi = FakePiAdapter(
        script={
            "discover": [discovery_with_gates_would_have_asked],
            "scope_guard": [COMPOSITE_SCOPE_VERDICT],
        }
    )
    o = make_orchestrator(
        repo,
        pi=pi,
        ui=ScriptedUI(interactive=False),
    )
    o.state.request = COMPOSITE_REQUEST
    o.store.write_text("input.md", f"# Review Request\n\n{COMPOSITE_REQUEST}\n")

    code = o.run()

    # Terminal DECOMPOSITION_REQUIRED, before DESIGN.
    assert code == int(ExitCode.HUMAN_HANDOFF)
    assert o.state.result_status == "DECOMPOSITION_REQUIRED"
    assert o.state.phase == Phase.HUMAN_HANDOFF
    # Nothing expensive was spent: the 84fb budget-burn pattern is gone.
    assert o.state.budgets.human_interruptions_used == 0
    assert o.state.budgets.revision_used == 0
    assert o.state.budgets.focused_revision_used == 0
    assert o.state.budgets.ablation_used == 0
    assert o.state.round == 0
    names = event_names(o)
    assert "DESIGN_STARTED" not in names
    assert "INITIAL_REVIEW_STARTED" not in names
    assert "HUMAN_GATE_CREATED" not in names  # no chained gates at all
    assert "SCOPE_GUARD_STOPPED" in names

    # Actionable decomposition guidance is the primary artifact.
    result = o.store.read_text("session-result.md")
    assert result
    assert "**DECOMPOSITION_REQUIRED**" in result
    for title in ("比对口径契约", "比对引擎", "运维化"):
        assert title in result
    assert "dependencies" in result or "depends on" in result
    assert "NOT executed automatically" in result
    # Splitting follows outcome boundaries, not mechanical folders.
    assessment = json.loads(
        (o.store.dir / "scope-assessment.json").read_text(encoding="utf-8")
    )
    assert len(assessment["decomposition"]) == 3
    assert assessment["decomposition"][1]["dependencies"] == ["比对口径契约"]


# ===========================================================================
# Case 2 — Bounded convergence: focused revision, no auto-ablation,
#          DESIGN_NOT_APPROVED instead of NEEDS_HUMAN_DECISION
# ===========================================================================

BOUNDED_REQUEST = (
    "为线上缺陷修复设计方案：分类器把服务端内部错误归为语义失败，"
    "不进入瞬时重试通道，导致当轮中断且水位不前移"
)


def intake_candidates_c454_shape():
    """The four independent intake questions the real session asked
    (retry budget / fix scope / legacy handling / mixed-error priority)."""
    def q(category, question, options, recommendation):
        return {
            "category": category,
            "question": question,
            "why": "业务语义，仓库无法自决",
            "options": [
                {"key": key, "label": label, "impact": impact}
                for key, label, impact in options
            ],
            "recommendation": recommendation,
            "source": "DISCOVER",
        }

    return [
        q(
            "TRADE_OFF",
            "内部错误复用哪条重试通道与预算？",
            [("reuse", "复用既有瞬时通道", "零新增"), ("new", "新建通道", "独立预算")],
            "reuse",
        ),
        q(
            "SCOPE",
            "分类失真是否随本次单一并修复？",
            [("together", "一并修复", "范围大"), ("split", "另行处理", "范围小")],
            "together",
        ),
        q(
            "SCOPE",
            "存量失败数据的处置是否纳入本次交付？",
            [("ops_later", "代码先行，处置后置", "交付快"), ("include", "纳入本次", "交付慢")],
            "ops_later",
        ),
        q(
            "REQUIREMENT",
            "混合错误且部分数据可用时以谁优先？",
            [("retry_first", "可重试优先", "保守"), ("data_first", "可用数据优先", "激进")],
            "retry_first",
        ),
    ]


def validation_blocker():
    """The persistent engineering blocker: evidence quality (the real
    R001 shape — validation evidence without discrimination power).
    RC1 B404: change_scope uses the proposal's canonical section name."""
    issue = make_blocking_issue(
        1,
        title="验证证据不具备区分力：重试用例在旧分类下同样通过",
        acceptance=[
            "重试用例必须先实际进入重试通道（断言重试事件已发生）再触发预算耗尽",
            "断言耗尽后及时退出且不再发起调用",
        ],
    )
    return issue.model_copy(
        update={
            "problem": "提交的验证计划只证明调用成功，不证明重试语义被区分",
            "impact": "需求满足与违反的实现都可通过验证，缺陷可能带病上线",
            "category": IssueCategory.REQUIREMENT,
            "correction_action": CorrectionAction.FOCUSED_REVISION,
            "focus_area": FocusArea.VALIDATION,
            "change_scope": ["verification_plan"],
        }
    )


def covered_by_active_decisions():
    """The real authority-check outcome: the blocker's semantics are
    already decided by the ACTIVE intake decisions — an engineering
    gap, not a missing Human decision."""
    return json.dumps(
        {
            "outcomes": [
                {
                    "issue_id": "R001",
                    "outcome": "COVERED_BY_ACTIVE_DECISION",
                    "referenced_decision_ids": ["D003"],
                    "rationale": (
                        "D003 已裁决代码先行、处置后置；本问题关闭条件要求的"
                        "是代码回归证据，属方案缺口而非缺失的人工决策"
                    ),
                }
            ]
        }
    )


def baseline_coverage_c454(blocker_title):
    """RC1 B403: the exact baseline for the c454 session after the four
    intake decisions became ACTIVE — A001 ← REQUEST, A002..A005 ← the
    four decisions D001..D004 (answered in gate order)."""
    decision_labels = [
        "内部错误复用哪条重试通道与预算？",
        "分类失真是否随本次单一并修复？",
        "存量失败数据的处置是否纳入本次交付？",
        "混合错误且部分数据可用时以谁优先？",
    ]
    answers = ["reuse", "together", "ops_later", "retry_first"]
    entries = [
        {
            "acceptance_id": "A001",
            "criterion": f"原始请求的期望行为已交付：{BOUNDED_REQUEST}",
            "status": "FAIL",
            "issue_title": blocker_title,
        }
    ]
    for index, (question, answer) in enumerate(zip(decision_labels, answers), 2):
        entries.append(
            {
                "acceptance_id": f"A{index:03d}",
                "criterion": f"Human Decision D{index - 1:03d}: {question} -> {answer}",
                "status": "PASS",
            }
        )
    return entries


def focused_revision_result(request=None):
    """RC1 B404: the focused proposal echoes the current design verbatim
    and changes ONLY the in-scope canonical section."""
    proposal = default_proposal_dict(request or BOUNDED_REQUEST)
    proposal["verification_plan"] = [
        "重试用例先断言重试事件发生，再驱动预算耗尽并断言退出",
        "混合错误部分可用用例优先断言可重试通道",
    ]
    return json.dumps(
        {
            "proposal": proposal,
            "target_issue_ids": ["R001"],
            "allowed_change_scope": ["verification_plan"],
            "preserved_invariants": [
                "ACTIVE Human Decisions 全部保持不变",
                "分类器整体结构保持不变",
            ],
            "changed_sections": ["verification_plan"],
            "issue_responses": [
                {
                    "issue_id": "R001",
                    "how_addressed": "用例改为断言重试事件先发生，再驱动预算耗尽并断言退出",
                }
            ],
            "acceptance_changes": [],
            "notes": "focused",
        }
    )


def closure_no_progress():
    """The focused attempt did not materially narrow the close
    condition; recommending the same mechanism again would repeat the
    same work (design §48)."""
    return json.dumps(
        {
            "issue_outcomes": [
                {
                    "issue_id": "R001",
                    "resolution": "UNRESOLVED",
                    "note": "关闭条件未收窄：用例仍在旧分类下通过，无区分力",
                    "correction_action": "FOCUSED_REVISION",
                    "material_progress": "NO_PROGRESS",
                }
            ],
            "new_issues": [],
            "summary": "closure",
        }
    )


def test_bounded_case_design_not_approved_not_needs_human(repo):
    """c454 replay: settled authority + persistent engineering blocker +
    no material progress -> precise DESIGN_NOT_APPROVED; ABLATION never
    fires automatically; no convergence gate is opened."""
    pi = FakePiAdapter(
        script={
            "discover": [discovery_with_candidates(intake_candidates_c454_shape())],
            "human_authority_check": [covered_by_active_decisions()],
            "focused_revise": [focused_revision_result()],
        }
    )
    codex = FakeCodexAdapter(
        script={
            "initial_review": [
                json.dumps(
                    {
                        "issues": [validation_blocker().model_dump()],
                        "acceptance_coverage": baseline_coverage_c454(
                            "验证证据不具备区分力：重试用例在旧分类下同样通过"
                        ),
                        "summary": "initial",
                    }
                )
            ],
            "closure_review": [closure_no_progress()],
        }
    )
    o = make_orchestrator(
        repo,
        pi=pi,
        codex=codex,
        ui=ScriptedUI(answers=["1", "1", "1", "1"]),
    )
    o.state.request = BOUNDED_REQUEST
    o.store.write_text("input.md", f"# Review Request\n\n{BOUNDED_REQUEST}\n")

    code = o.run()

    names = event_names(o)

    # --- C5: the four independent questions batched into ONE gate.
    assert o.state.budgets.human_interruptions_used == 1
    gates = [e for e in events_of(o) if e["event"] == "HUMAN_GATE_CREATED"]
    assert len(gates) == 1
    assert len(gates[0]["questions"]) == 4  # no same-second HG002

    # --- Scope guard allowed continuation.
    assert o.state.scope_verdict == "BOUNDED"

    # --- Authority settled: covered, no convergence gate, no re-asking.
    covered = [e for e in events_of(o) if e["event"] == "ISSUE_COVERED_BY_DECISION"]
    assert covered and covered[0]["decision_ids"] == ["D003"]
    assert "CONVERGENCE_GATE_CREATED" not in names

    # --- C2/C3: the local blocker went through FOCUSED_REVISION.
    assert o.state.budgets.focused_revision_used == 1
    assert "FOCUSED_REVISION_STARTED" in names
    assert "CORRECTION_ROUTED" in names
    routed = [e for e in events_of(o) if e["event"] == "CORRECTION_ROUTED"]
    assert routed[0]["action"] == "FOCUSED_REVISION"

    # --- C4: no-material-progress stop after the repeat recommendation.
    assert "NO_MATERIAL_PROGRESS_STOP" in names
    assert "CORRECTION_STOPPED" in names

    # --- ABLATION never auto-triggered (the c454 ladder burn is gone).
    assert o.state.budgets.ablation_used == 0
    assert o.state.budgets.revision_used == 0
    assert "ABLATION_TRIGGERED" not in names

    # --- C1: precise terminal classification. Agent convergence
    # failure is NOT mislabeled as a Human decision need.
    assert code == int(ExitCode.HUMAN_HANDOFF)
    assert o.state.phase == Phase.HUMAN_HANDOFF
    assert o.state.status == SessionStatus.HUMAN_HANDOFF
    assert o.state.result_status == "DESIGN_NOT_APPROVED"

    result = o.store.read_text("session-result.md")
    assert "**DESIGN_NOT_APPROVED**" in result
    assert "## Frozen Human Decisions" in result  # authority is settled
    assert "reuse" in result  # the four decisions survive as facts
    assert "## Remaining Blocking Issues" in result
    # The residual close conditions are hard inputs for the next session.
    assert "重试用例必须先实际进入重试通道" in result
    assert "engineering gaps" in result  # next-action is engineering-shaped

    telemetry = json.loads((o.store.dir / "telemetry.json").read_text(encoding="utf-8"))
    assert telemetry["terminal_result_status"] == "DESIGN_NOT_APPROVED"
    assert telemetry["focused_revision_count"] == 1
    assert telemetry["ablation_count"] == 0
    assert telemetry["no_material_progress_stop_count"] == 1
    assert telemetry["human_interruptions"] == 1


def test_bounded_case_focused_revision_closes_blocker_when_progress_holds(repo):
    """The companion path: the same local blocker closes after the
    focused revision -> APPROVED without touching revision/ablation."""
    pi = FakePiAdapter(
        script={
            "discover": [discovery_with_candidates(intake_candidates_c454_shape())],
            "focused_revise": [focused_revision_result()],
        }
    )
    variant_blocker = validation_blocker().model_copy(
        update={"category": IssueCategory.DESIGN}
    )
    # This companion session keeps the default harness request, so the
    # echoed proposal uses that request's summary.
    default_request = "给同步任务增加暂停能力"
    pi.script["focused_revise"] = [focused_revision_result(default_request)]
    codex = FakeCodexAdapter(
        script={
            "initial_review": [
                json.dumps({"issues": [variant_blocker.model_dump()], "summary": "initial"})
            ],
            "closure_review": [
                json.dumps(
                    {
                        "issue_outcomes": [
                            {"issue_id": "R001", "resolution": "RESOLVED", "note": "verified"}
                        ],
                        "new_issues": [],
                        "summary": "closure",
                    }
                )
            ],
        }
    )
    o = make_orchestrator(
        repo,
        pi=pi,
        codex=codex,
        ui=ScriptedUI(answers=["1", "1", "1", "1"]),
    )
    assert o.run() == int(ExitCode.DONE)
    assert o.state.result_status == "APPROVED"
    assert o.state.budgets.focused_revision_used == 1
    assert o.state.budgets.revision_used == 0
    assert o.state.budgets.ablation_used == 0
    r001 = next(i for i in o.store.load_issues().issues if i.id == "R001")
    assert r001.status == IssueStatus.RESOLVED
    result = o.store.read_text("session-result.md")
    assert "**APPROVED**" in result
    assert "**READY**" in result
