"""V0.2 Capability B + E + audit: Human Authority Check routing,
Convergence Gate, structured handoff and audit events.

Spec: docs/V0_2_HUMAN_DECISION_CONVERGENCE_SPEC.md sections 5, 8, 9, 10
and deterministic scenarios B8-B10, C11-C14, D15-D17, G25-G27.
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
    BudgetLimits,
    Decision,
    DecisionStatus,
    ExitCode,
    GateCategory,
    IssueCategory,
    IssueStatus,
    Phase,
    SessionStatus,
)
from agent_review.orchestrator import Orchestrator

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


def requirement_blocker(number=1, title="Missing existing full daily report coverage"):
    return make_blocking_issue(
        number,
        title=title,
        category=IssueCategory.REQUIREMENT,
        acceptance=["Design covers §5.4 display/statistics unification (A07)."],
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
                        "D001 full_doc5 already placed display/statistics "
                        "unification (§5.4) inside the decided scope; the issue "
                        "is an implementation gap, not missing human semantics."
                    ),
                }
            ]
        }
    )


def needs_new_result(issue_id="R001", options=None, recommendation="precise"):
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
                    "rationale": "No ACTIVE decision establishes daily-report semantics.",
                    "decision_candidate": {
                        "category": "REQUIREMENT",
                        "question": "现有全量日报在修复后如何统一展示统计（§5.4/A07）？",
                        "why_human": "统计口径属于业务语义，仓库与既有决策均未定义。",
                        "options": options,
                        "recommendation": recommendation,
                        "source_issue_ids": [issue_id],
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


def review_with_blocker(blocker):
    data = blocker.model_dump(mode="json") if hasattr(blocker, "model_dump") else blocker
    return json.dumps({"issues": [data], "summary": "blocked"})


def make_o(repo, pi=None, codex=None, ui=None, config=None):
    return Orchestrator.create(
        repository=repo,
        request="统一订单同步状态口径",
        config=config or Config(),
        pi=pi or FakePiAdapter(),
        codex=codex or FakeCodexAdapter(),
        ui=ui or ScriptedUI(interactive=False),
    )


def make_convergence_orchestrator(repo, authority_script, ui_answers, pi=None, config=None):
    pi = pi or FakePiAdapter(
        script={
            "initial_review:none": [],
            "human_authority_check": [authority_script],
        }
    )
    codex = FakeCodexAdapter(
        script={"initial_review": [review_with_blocker(requirement_blocker(1))]}
    )
    return Orchestrator.create(
        repository=repo,
        request="统一订单同步状态口径",
        config=config or Config(),
        pi=pi,
        codex=codex,
        ui=ScriptedUI(answers=ui_answers),
    )


# --- B8 + B10 + G26: covered REQUIREMENT blocker routes to REVISION --------------


def test_b8_covered_requirement_routes_to_revision_no_gate_no_handoff(repo):
    pi = FakePiAdapter(
        script={
            "discover": [discovery_with_candidates(
                [candidate(question="修复范围档位？",
                           options=[
                               {"key": "full_doc5", "label": "按问题单§5全量实施，含展示统计统一", "impact": "覆盖§5.4"},
                               {"key": "minimal", "label": "仅修复新增路径", "impact": "§5.4遗留"},
                           ],
                           recommendation="full_doc5")],
            )],
            "human_authority_check": [covered_result()],
        }
    )
    codex = FakeCodexAdapter(
        script={"initial_review": [review_with_blocker(requirement_blocker(1))]}
    )
    o = make_orchestrator(repo, pi=pi, codex=codex, ui=ScriptedUI(answers=["1"]))
    code = o.run()

    # The critical PROD-001 acceptance: the session must NOT terminate
    # merely because the reviewer used category REQUIREMENT.
    assert code == int(ExitCode.DONE)
    assert o.state.phase == Phase.DONE
    assert o.state.status == SessionStatus.DONE

    events = events_of(o)
    assert any(e["event"] == "ISSUE_NEED_HUMAN" and e["issue_id"] == "R001" for e in events)
    covered = [e for e in events if e["event"] == "ISSUE_COVERED_BY_DECISION"]
    assert covered and covered[0]["decision_ids"] == ["D001"]  # G26
    assert not any(e["event"] == "CONVERGENCE_GATE_CREATED" for e in events)
    assert not any(e["event"] == "SESSION_HUMAN_HANDOFF" for e in events)

    # R001: solved through the normal correction path; reviewer
    # provenance/category preserved (B10/G11.1); the durable coverage
    # marker survives on the issue even after closure overwrites the
    # transient resolution note.
    r001 = next(i for i in o.store.load_issues().issues if i.id == "R001")
    assert r001.status == IssueStatus.RESOLVED
    assert r001.category == IssueCategory.REQUIREMENT
    assert r001.provenance == "INITIAL_REVIEW"
    assert r001.covered_by_decisions == ["D001"]
    events_marked = [e for e in events if e["event"] == "ISSUE_COVERED_BY_DECISION"]
    assert events_marked and events_marked[0]["decision_ids"] == ["D001"]

    # Budget truth: revision consumed, no extra interruption.
    assert o.state.budgets.revision_used == 1
    assert o.state.budgets.human_interruptions_used == 1  # only the intake gate


# --- B9: coverage claims are mechanically validated ------------------------------


def test_b9a_nonexistent_decision_reference_fails_closed(repo):
    o = make_convergence_orchestrator(
        repo, covered_result(decision_ids=("D999",)), ui_answers=[]
    )
    assert o.run() == int(ExitCode.HUMAN_HANDOFF)
    assert "non-ACTIVE or nonexistent" in (o.state.handoff_reason or "")
    assert (o.store.dir / "handoff.md").is_file()


def test_b9b_superseded_decision_reference_fails_closed(repo):
    from agent_review.models import DecisionLog
    from agent_review.phases.human_gate import resolve_need_human_issues
    from agent_review.phases.review import _need_human_ids, ingest_new_issues

    o = make_orchestrator(repo)
    # D001 superseded by D002 on the same key; only D002 is ACTIVE.
    log = DecisionLog(
        decisions=[
            Decision(
                decision_id="D001", decision_key="SCOP-aaaa1111", gate_id="HG001",
                question="范围?", answer_text="old", status=DecisionStatus.SUPERSEDED,
                superseded_by="D002",
            ),
            Decision(
                decision_id="D002", decision_key="SCOP-aaaa1111", gate_id="HG002",
                question="范围?", answer_text="new", status=DecisionStatus.ACTIVE,
            ),
        ],
        next_decision_number=3,
    )
    o.store.save_decisions(log)
    ingest_new_issues(o, [requirement_blocker(1)], provenance="INITIAL_REVIEW")
    _need_human_ids(o)
    pi = FakePiAdapter(script={"human_authority_check": [covered_result(decision_ids=("D001",))]})
    o.pi = pi
    code = resolve_need_human_issues(o, ["R001"])
    assert code == int(ExitCode.HUMAN_HANDOFF)
    assert "non-ACTIVE" in (o.state.handoff_reason or "")
    # The issue was NOT downgraded or reverted by an invalid claim.
    assert o.store.load_issues().issues[0].status == IssueStatus.NEED_HUMAN


# --- C11 + C12: new Human decision -> Convergence Gate -> resume -----------------


def test_c11_c12_convergence_gate_offered_option_continues(repo):
    o = make_convergence_orchestrator(repo, needs_new_result(), ui_answers=["1"])
    code = o.run()

    assert code == int(ExitCode.DONE)
    events = events_of(o)
    conv = [e for e in events if e["event"] == "CONVERGENCE_GATE_CREATED"]
    assert conv and conv[0]["source_issue_ids"] == ["R001"]
    assert conv[0]["gate_id"] == "HG001"

    gate_log = o.store.load_gate_log()
    gate = gate_log.current
    assert gate.category == GateCategory.CONVERGENCE
    assert gate.source_issue_ids == ["R001"]
    assert gate.created_in_phase == "INITIAL_REVIEW"

    # The gate consumed one interruption; its decision rebuilt the basis.
    assert o.state.budgets.human_interruptions_used == 1
    assert o.state.task_revision == 2
    decisions = o.store.load_decisions().decisions
    assert decisions[0].selected_option_key == "precise"
    assert decisions[0].source.value == "OPTION"

    # The original review issue was superseded by the task revision and
    # the redesigned proposal passed review.
    r001 = next(i for i in o.store.load_issues().issues if i.id == "R001")
    assert r001.status == IssueStatus.SUPERSEDED
    assert o.store.load_proposal().based_on_task_revision == 2
    assert o.store.read_text("final.md")


def test_c13_convergence_gate_custom_decision_continues(repo):
    custom_text = "日报统计按精确匹配口径重算，历史保持现状并注明分类"
    o = make_convergence_orchestrator(repo, needs_new_result(), ui_answers=["0", custom_text])
    code = o.run()

    assert code == int(ExitCode.DONE)
    decisions = o.store.load_decisions().decisions
    assert decisions[0].source.value == "CUSTOM"
    assert decisions[0].answer_text == custom_text
    assert o.state.task_revision == 2
    # Custom decision is a session fact in the rebuilt contract.
    contract = o.store.load_contract()
    assert any(custom_text in line for line in contract.confirmed_decisions)


# --- C14: invalid decision candidates never open a malformed gate -----------------


def test_c14a_single_option_candidate_rejected(repo):
    one_option = [
        {"key": "only", "label": "唯一选项", "impact": "无选择余地"},
    ]
    o = make_convergence_orchestrator(
        repo, needs_new_result(options=one_option), ui_answers=["1"]
    )
    assert o.run() == int(ExitCode.HUMAN_HANDOFF)
    assert "invalid decision candidate" in (o.state.handoff_reason or "")
    # No gate was created and no interruption consumed.
    assert o.store.load_gate_log().current is None
    assert o.state.budgets.human_interruptions_used == 0
    events = events_of(o)
    assert not any(e["event"] == "CONVERGENCE_GATE_CREATED" for e in events)


def test_c14b_unknown_recommendation_candidate_rejected(repo):
    bad_rec = [
        {"key": "a", "label": "A", "impact": "x"},
        {"key": "b", "label": "B", "impact": "y"},
    ]
    o = make_convergence_orchestrator(
        repo, needs_new_result(options=bad_rec, recommendation="zzz"), ui_answers=["1"]
    )
    assert o.run() == int(ExitCode.HUMAN_HANDOFF)
    assert "recommendation" in (o.state.handoff_reason or "")


def test_c14c_unknown_issue_in_outcome_rejected(repo):
    bogus = json.dumps(
        {"outcomes": [
            {"issue_id": "R999", "outcome": "CANNOT_DETERMINE", "rationale": "x"}
        ]}
    )
    o = make_convergence_orchestrator(repo, bogus, ui_answers=[])
    assert o.run() == int(ExitCode.HUMAN_HANDOFF)
    assert "unknown" in (o.state.handoff_reason or "")


# --- D15 + D16 + G27: budget exhaustion and CANNOT_DETERMINE fail closed ----------


def test_d15_convergence_needed_but_budget_exhausted_hands_off(repo):
    config = Config(budgets=BudgetLimits(max_human_interruptions=1))
    pi = FakePiAdapter(
        script={
            "discover": [discovery_with_candidates([candidate()])],
            "human_authority_check": [needs_new_result()],
        }
    )
    codex = FakeCodexAdapter(
        script={"initial_review": [review_with_blocker(requirement_blocker(1))]}
    )
    o = make_o(repo, pi=pi, codex=codex, ui=ScriptedUI(answers=["1"]), config=config)
    code = o.run()
    assert code == int(ExitCode.HUMAN_HANDOFF)
    assert "interruption budget exhausted" in (o.state.handoff_reason or "")

    # The handoff package carries the derivable decision packet.
    handoff = o.store.read_text("handoff.md")
    assert handoff and "# Human Handoff" in handoff
    assert "现有全量日报在修复后如何统一展示统计" in handoff
    assert "precise" in handoff
    assert "R001" in handoff
    events = events_of(o)
    assert any(e["event"] == "HANDOFF_WRITTEN" for e in events)


def test_d16_cannot_determine_hands_off_with_package(repo):
    o = make_convergence_orchestrator(repo, cannot_determine_result(), ui_answers=[])
    code = o.run()
    assert code == int(ExitCode.HUMAN_HANDOFF)
    assert "could not be determined" in (o.state.handoff_reason or "")
    handoff = o.store.read_text("handoff.md")
    assert handoff
    # G27: reason + blocking issue reconstructable from the package.
    assert o.state.handoff_reason in handoff
    assert "R001" in handoff
    assert "Missing existing full daily report coverage" in handoff
    assert "a Human-owned decision or fact is required" in handoff
    events = events_of(o)
    assert any(e["event"] == "ISSUE_NEED_HUMAN" for e in events)
    assert any(e["event"] == "SESSION_HUMAN_HANDOFF" for e in events)


def test_d16b_default_fake_adapter_fails_closed(repo):
    """No scripted authority check: CANNOT_DETERMINE default hands off."""
    pi = FakePiAdapter()  # default authority check = CANNOT_DETERMINE
    codex = FakeCodexAdapter(
        script={"initial_review": [review_with_blocker(requirement_blocker(1))]}
    )
    o = make_orchestrator(repo, pi=pi, codex=codex, ui=ScriptedUI(answers=[]))
    assert o.run() == int(ExitCode.HUMAN_HANDOFF)
    # The issue was never handed to the author for revision.
    assert not any(c[0] in ("revise", "ablate") for c in pi.calls)
    assert o.store.load_issues().issues[0].status == IssueStatus.NEED_HUMAN


def test_d17_show_handoff_cli(repo, monkeypatch):
    import agent_review.agents as agents_pkg
    from typer.testing import CliRunner

    from agent_review.cli import app

    runner = CliRunner()
    monkeypatch.setattr(
        agents_pkg,
        "build_adapters",
        lambda cfg, repository=None, store=None: (
            FakePiAdapter(),
            FakeCodexAdapter(
                script={"initial_review": [review_with_blocker(requirement_blocker(1))]}
            ),
        ),
    )
    result = runner.invoke(app, ["run", "统一订单口径", "--repo", str(repo)])
    assert result.exit_code == int(ExitCode.HUMAN_HANDOFF)

    sid = next(
        line.split(":")[1].strip()
        for line in result.output.splitlines()
        if line.startswith("Session:")
    )
    show = runner.invoke(app, ["show", "handoff", sid, "--repo", str(repo)])
    assert show.exit_code == 0
    assert "# Human Handoff" in show.output
    assert "R001" in show.output
    assert "Why the workflow stopped" in show.output
    assert "Recommended next action" in show.output


# --- G25: OPEN -> NEED_HUMAN is never silent --------------------------------------


def test_g25_need_human_flip_emits_event(repo):
    o = make_convergence_orchestrator(repo, cannot_determine_result(), ui_answers=[])
    o.run()
    events = events_of(o)
    flips = [e for e in events if e["event"] == "ISSUE_NEED_HUMAN"]
    assert flips and flips[0]["issue_id"] == "R001"
    assert flips[0]["category"] == "REQUIREMENT"
    # Ordering is reconstructable: flip happens between review completion
    # and the authority check.
    names = [e["event"] for e in events]
    assert names.index("ISSUE_NEED_HUMAN") < names.index("ISSUE_HUMAN_AUTHORITY_CHECK_STARTED")


def test_authority_check_not_called_for_design_blockers(repo):
    pi = FakePiAdapter()
    codex = FakeCodexAdapter(
        script={"initial_review": [review_with_blocker(make_blocking_issue(1))]}
    )
    o = make_orchestrator(repo, pi=pi, codex=codex, ui=ScriptedUI(answers=[]))
    assert o.run() == int(ExitCode.DONE)
    assert not any(c[0] == "human_authority_check" for c in pi.calls)


def test_mixed_covered_and_new_opens_gate_for_new_only(repo):
    """One covered REQUIREMENT blocker + one new-decision blocker."""
    pi = FakePiAdapter(
        script={
            "discover": [discovery_with_candidates(
                [candidate(question="范围档位？",
                           options=[
                               {"key": "full", "label": "全量", "impact": "大"},
                               {"key": "min", "label": "最小", "impact": "小"},
                           ])]
            )],
            "human_authority_check": [json.dumps({
                "outcomes": [
                    {
                        "issue_id": "R001",
                        "outcome": "COVERED_BY_ACTIVE_DECISION",
                        "referenced_decision_ids": ["D001"],
                        "rationale": "already inside the decided scope",
                    },
                    {
                        "issue_id": "R002",
                        "outcome": "NEEDS_NEW_HUMAN_DECISION",
                        "rationale": "no decision covers it",
                        "decision_candidate": {
                            "category": "TRADE_OFF",
                            "question": "历史行如何处置？",
                            "why_human": "写入策略是业务取舍",
                            "options": [
                                {"key": "keep", "label": "保留", "impact": "零写入"},
                                {"key": "rewrite", "label": "重写", "impact": "批量写"},
                            ],
                            "recommendation": "keep",
                            "source_issue_ids": ["R002"],
                        },
                    },
                ]
            })],
        }
    )
    r2 = make_blocking_issue(
        2, title="兜底绕开门禁", category=IssueCategory.REQUIREMENT,
        acceptance=["兜底与主口径一致"],
    )
    codex = FakeCodexAdapter(
        script={"initial_review": [json.dumps({
            "issues": [requirement_blocker(1).model_dump(mode="json"),
                       r2.model_dump(mode="json")],
            "summary": "blocked",
        })]}
    )
    o = make_orchestrator(repo, pi=pi, codex=codex, ui=ScriptedUI(answers=["1", "1"]))
    assert o.run() == int(ExitCode.DONE)
    events = events_of(o)
    assert any(e["event"] == "ISSUE_COVERED_BY_DECISION" and e["issue_id"] == "R001" for e in events)
    conv = [e for e in events if e["event"] == "CONVERGENCE_GATE_CREATED"]
    assert conv and conv[0]["source_issue_ids"] == ["R002"]
    # Both original issues were superseded by the task revision from the
    # convergence decision.
    statuses = {i.id: i.status for i in o.store.load_issues().issues}
    assert statuses["R001"] == IssueStatus.SUPERSEDED
    assert statuses["R002"] == IssueStatus.SUPERSEDED
