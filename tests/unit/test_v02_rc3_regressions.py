"""V0.2-RC3 regressions: Human Answer Alias Space (B301) and Intake
option cardinality (N301).

Spec: docs/V0_2_RC3_FIX_SPEC.md section 4 — RC3 regression items 1-23
are implemented here; preservation items 24-30 (custom decisions,
PROD-001 replay, RC2 FINAL_REVIEW/FACT/provenance regressions, gate
consistency, session presentation) are the unchanged existing suites,
which must remain green alongside this file.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent_review.agents.fakes import FakeCodexAdapter, FakePiAdapter
from agent_review.config import Config
from agent_review.models import (
    ExitCode,
    GateCategory,
    GateOption,
    GateQuestion,
    HumanGate,
    IssueCategory,
    IssueStatus,
    normalize_answer_text,
    normalized_option_aliases,
    normalized_protocol_control_aliases,
    option_alias_violation,
)
from agent_review.orchestrator import Orchestrator
from agent_review.phases import human_gate
from agent_review.phases.human_gate import (
    is_custom_request,
    is_global_recommend,
    match_option,
)

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


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def make_question(options, decision_key="REQ-aaaaaaaa", recommendation=None):
    return GateQuestion(
        decision_key=decision_key,
        category="REQUIREMENT",
        question="历史行如何处理？",
        options=[GateOption(key=k, label=lbl) for k, lbl in options],
        recommendation=recommendation,
    )


def valid_options():
    """A packet whose alias space is unambiguous (item 10 baseline)."""
    return [
        GateOption(key="keep", label="保留历史行", impact="零写入"),
        GateOption(key="rewrite", label="批量重写历史行", impact="批量写"),
        GateOption(key="hybrid", label="新按新口径历史逐步修复", impact="渐进"),
    ]


def needs_new_result(
    issue_id="R001",
    category="REQUIREMENT",
    question="历史行如何处理？",
    options=None,
    recommendation=None,
    source_issue_ids=None,
):
    options = options or [
        {"key": "keep", "label": "保留历史行", "impact": "x"},
        {"key": "rewrite", "label": "批量重写历史行", "impact": "y"},
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
                        "why_human": "业务语义。",
                        "options": options,
                        "recommendation": recommendation,
                        "source_issue_ids": source_issue_ids or [issue_id],
                    },
                }
            ]
        }
    )


def requirement_blocker(number=1, title="Disputed semantics need a Human decision"):
    from agent_review.agents.fakes import make_blocking_issue

    return make_blocking_issue(
        number,
        title=title,
        category=IssueCategory.REQUIREMENT,
        acceptance=["The authoritative semantics are established."],
    )


def review_with_issues(*issues):
    return json.dumps(
        {
            "issues": [
                i.model_dump(mode="json") if hasattr(i, "model_dump") else i
                for i in issues
            ],
            "summary": "blocked",
        }
    )


def make_convergence_flow(repo, authority_script, ui_answers):
    pi = FakePiAdapter(script={"human_authority_check": [authority_script]})
    codex = FakeCodexAdapter(
        script={"initial_review": [review_with_issues(requirement_blocker(1))]}
    )
    return Orchestrator.create(
        repository=repo,
        request="统一订单同步状态口径",
        config=Config(),
        pi=pi,
        codex=codex,
        ui=ScriptedUI(answers=ui_answers),
    )


# ---------------------------------------------------------------------------
# Single source of truth (B301 §2.6)
# ---------------------------------------------------------------------------


def test_b301_shared_alias_helpers_are_the_single_source_of_truth():
    # The option-owned alias forms are exactly the spec's §2.5 list.
    option = GateOption(key="keep", label="保留历史行")
    aliases = normalized_option_aliases(option, 2)
    assert set(aliases) == {
        normalize_answer_text("keep"),
        normalize_answer_text("保留历史行"),
        normalize_answer_text("keep 保留历史行"),
        normalize_answer_text("2"),
        normalize_answer_text("选项2"),
        normalize_answer_text("option 2"),
    }
    # The protocol-control namespace is CUSTOM ∪ GLOBAL_RECOMMEND through
    # the same normalization.
    control = normalized_protocol_control_aliases()
    assert normalize_answer_text("0") in control
    assert normalize_answer_text("custom") in control
    assert normalize_answer_text("自定义") in control
    assert normalize_answer_text("都按推荐") in control
    assert normalize_answer_text("all recommended") in control
    # Clean packet: no violation.
    assert option_alias_violation(valid_options()) is None


# ---------------------------------------------------------------------------
# B301 items 1-6: cross-option ambiguity
# ---------------------------------------------------------------------------


def test_b301_item1_same_normalized_label_rejected():
    with pytest.raises(ValidationError, match="exactly one interpretation"):
        make_question([("keep", "保持现状"), ("legacy", "保持现状")])


def test_b301_item2_labels_differing_only_by_normalization_rejected():
    # "保持现状" vs "保持现状。" normalize to the same alias.
    with pytest.raises(ValidationError, match="exactly one interpretation"):
        make_question([("keep", "保持现状"), ("legacy", "保持现状。")])
    with pytest.raises(ValidationError, match="exactly one interpretation"):
        make_question([("keep", "Safe Fix"), ("legacy", "safe fix")])


def test_b301_item3_key_of_one_option_collides_with_label_of_another():
    with pytest.raises(ValidationError, match="exactly one interpretation"):
        make_question([("safe", "安全修复"), ("danger", "safe")])


def test_b301_item4_composite_alias_collides_with_another_option_alias():
    # option1's "key + label" composite equals option2's label.
    with pytest.raises(ValidationError, match="exactly one interpretation"):
        make_question([("safe", "安全修复"), ("other", "safe 安全修复")])


def test_b301_item5_alias_collides_with_numeric_index_alias():
    # option 2's KEY is "1": collides with option 1's numeric selector.
    with pytest.raises(ValidationError, match="exactly one interpretation"):
        make_question([("safe", "安全修复"), ("1", "兼容修复")])
    # option 1's LABEL is "2": collides with option 2's numeric selector.
    with pytest.raises(ValidationError, match="exactly one interpretation"):
        make_question([("safe", "2"), ("alt", "兼容修复")])


def test_b301_item6_collision_with_xuanxiang_and_option_word_aliases():
    # option 2's label is "选项1": collides with option 1's 选项1 alias.
    with pytest.raises(ValidationError, match="exactly one interpretation"):
        make_question([("safe", "安全修复"), ("alt", "选项1")])
    # option 3's label is "Option 1": collides with option 1's alias
    # after normalization ("option 1").
    with pytest.raises(ValidationError, match="exactly one interpretation"):
        make_question(
            [("safe", "安全修复"), ("alt", "兼容修复"), ("third", "Option 1")]
        )


def test_b301_intake_duplicate_label_candidate_is_suppressed_before_gate(repo):
    dup_label = candidate(
        question="历史行如何处理？",
        options=[
            {"key": "keep", "label": "保持现状", "impact": "x"},
            {"key": "legacy", "label": "保持现状", "impact": "y"},
        ],
    )
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates([dup_label])]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=[]))
    assert o.run() == int(ExitCode.DONE)
    suppressed = [
        e
        for e in events_of(o)
        if e["event"] == "HUMAN_CANDIDATE_SUPPRESSED"
        and "exactly one interpretation" in e.get("reason", "")
    ]
    assert suppressed
    assert o.store.load_gate_log().current is None
    assert o.state.budgets.human_interruptions_used == 0


def test_b301_intake_numeric_collision_candidate_is_suppressed_before_gate(repo):
    numeric_key = candidate(
        question="历史行如何处理？",
        options=[
            {"key": "safe", "label": "安全修复", "impact": "x"},
            {"key": "1", "label": "兼容修复", "impact": "y"},
        ],
    )
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates([numeric_key])]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=[]))
    assert o.run() == int(ExitCode.DONE)
    suppressed = [
        e
        for e in events_of(o)
        if e["event"] == "HUMAN_CANDIDATE_SUPPRESSED"
        and "exactly one interpretation" in e.get("reason", "")
    ]
    assert suppressed
    assert o.store.load_gate_log().current is None


def test_b301_convergence_duplicate_label_packet_fails_closed(repo):
    options = [
        {"key": "keep", "label": "保持现状", "impact": "x"},
        {"key": "legacy", "label": "保持现状", "impact": "y"},
    ]
    o = make_convergence_flow(
        repo, needs_new_result(options=options), ui_answers=[]
    )
    assert o.run() == int(ExitCode.HUMAN_HANDOFF)
    assert "exactly one interpretation" in (o.state.handoff_reason or "")
    # Fail closed BEFORE gate creation and interruption consumption.
    assert o.store.load_gate_log().current is None
    assert o.state.budgets.human_interruptions_used == 0
    r001 = next(i for i in o.store.load_issues().issues if i.id == "R001")
    assert r001.status == IssueStatus.NEED_HUMAN
    assert r001.category == IssueCategory.REQUIREMENT  # provenance intact


# ---------------------------------------------------------------------------
# B301 items 7-8: protocol-control ambiguity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key,label",
    [
        ("zero", "0"),            # label vs the numeric custom selector
        ("num", "自定义"),          # label vs a custom selector
        ("num", "Custom."),        # normalizes to "custom"
        ("num", "自己决定"),
        ("custom", "正常标签"),      # option KEY vs a custom selector
    ],
)
def test_b301_item7_option_alias_colliding_with_custom_selectors_rejected(key, label):
    with pytest.raises(ValidationError, match="reserved protocol control command"):
        make_question([(key, label), ("real", "真实选项")])


@pytest.mark.parametrize(
    "label",
    ["按推荐", "都按推荐", "全部按推荐", "all recommended", "All Recommended."],
)
def test_b301_item8_option_alias_colliding_with_recommend_selectors_rejected(label):
    with pytest.raises(ValidationError, match="reserved protocol control command"):
        make_question([("a", label), ("b", "另一选项")])


def test_b301_control_collision_only_after_normalization_is_still_rejected():
    # "按推荐。" and "Custom" only collide after the shared normalization.
    assert normalize_answer_text("按推荐。") == normalize_answer_text("按推荐")
    with pytest.raises(ValidationError, match="reserved protocol control command"):
        make_question([("a", "按推荐。"), ("b", "另一选项")])


def test_b301_convergence_control_collision_packet_fails_closed(repo):
    options = [
        {"key": "normal", "label": "custom", "impact": "x"},
        {"key": "other", "label": "其他方案", "impact": "y"},
    ]
    o = make_convergence_flow(repo, needs_new_result(options=options), ui_answers=[])
    assert o.run() == int(ExitCode.HUMAN_HANDOFF)
    assert "reserved protocol control command" in (o.state.handoff_reason or "")
    assert o.store.load_gate_log().current is None
    assert o.state.budgets.human_interruptions_used == 0


# ---------------------------------------------------------------------------
# B301 item 9: validation and runtime share one normalization
# ---------------------------------------------------------------------------


def test_b301_item9_validation_uses_the_runtime_normalization():
    # A label that only becomes a control token AFTER normalization is
    # rejected by the validator...
    with pytest.raises(ValidationError, match="reserved protocol control command"):
        make_question([("a", "Custom."), ("b", "另一选项")])
    # ...and runtime matching accepts a normalization variant of a VALID
    # alias through the same function (e.g. " SAFE。 " answers key "safe").
    question = make_question([("safe", "安全修复"), ("alt", "兼容修复")])
    assert match_option(question, " SAFE。 ") is question.options[0]
    assert match_option(question, "兼容修复!") is question.options[1]


def test_b301_match_option_uses_the_shared_alias_forms():
    question = make_question(
        [("safe", "安全修复"), ("alt", "兼容修复"), ("third", "第三方案")]
    )
    # Runtime resolves every advertised answer form (items 11-14).
    assert match_option(question, "1") is question.options[0]
    assert match_option(question, "3") is question.options[2]
    assert match_option(question, "选项2") is question.options[1]
    assert match_option(question, "option 3") is question.options[2]
    assert match_option(question, "safe") is question.options[0]
    assert match_option(question, "安全修复") is question.options[0]
    assert match_option(question, "safe 安全修复") is question.options[0]
    assert match_option(question, "SAFE  安全修复") is question.options[0]
    assert match_option(question, "banana") is None
    assert match_option(question, "") is None


# ---------------------------------------------------------------------------
# B301 items 10-16: valid behavior preserved
# ---------------------------------------------------------------------------


def test_b301_item10_normal_packet_with_distinct_aliases_remains_valid():
    question = make_question(
        [("keep", "保留历史行"), ("rewrite", "批量重写"), ("hybrid", "混合修复")],
        recommendation="keep",
    )
    assert len(question.options) == 3
    assert option_alias_violation(question.options) is None


def test_b301_items_11_to_14_answer_forms_select_intended_options(repo):
    """Numeric / key / label / key+label answers each create the intended
    OPTION decision through the full interactive gate."""
    # The shared candidate() fixture offers:
    #   1. [cooperative] Cooperative pause between steps
    #   2. [immediate]  Immediate abort of current step
    forms = [
        ("2", "immediate"),  # item 11: numeric index
        ("cooperative", "cooperative"),  # item 12: option key
        ("Immediate abort of current step", "immediate"),  # item 13: label
        ("cooperative Cooperative pause between steps", "cooperative"),  # item 14: key + label
    ]
    for answer, expected_key in forms:
        pi = FakePiAdapter(
            script={"discover": [discovery_with_candidates([candidate()])]}
        )
        o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=[answer]))
        assert o.run() == int(ExitCode.DONE), f"answer {answer!r} failed"
        decisions = o.store.load_decisions().decisions
        assert decisions, f"answer {answer!r} created no decision"
        assert decisions[0].selected_option_key == expected_key
        assert decisions[0].source.value == "OPTION"


def test_b301_item15_custom_selectors_still_enter_custom_mode(repo):
    custom_text = "历史行保留，仅新数据按新口径写入"
    for selector in ("0", "custom", "自定义"):
        pi = FakePiAdapter(
            script={"discover": [discovery_with_candidates([candidate()])]}
        )
        o = make_orchestrator(
            repo, pi=pi, ui=ScriptedUI(answers=[selector, custom_text])
        )
        assert o.run() == int(ExitCode.DONE), f"selector {selector!r} failed"
        decisions = o.store.load_decisions().decisions
        assert decisions and decisions[0].source.value == "CUSTOM"
        assert decisions[0].answer_text == custom_text
    # Selector detection itself (including normalization variants).
    assert is_custom_request("0")
    assert is_custom_request("Custom")
    assert is_custom_request("自定义。")
    assert not is_custom_request("保持现状")


def test_b301_item16_global_recommend_selectors_preserve_behavior(repo):
    candidates = [
        candidate(question="Q1?", recommendation="cooperative"),
        candidate(question="Q2?", category="TRADE_OFF", recommendation="immediate"),
    ]
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates(candidates)]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=["都按推荐"]))
    assert o.run() == int(ExitCode.DONE)
    decisions = o.store.load_decisions().decisions
    assert {d.selected_option_key for d in decisions} == {"cooperative", "immediate"}
    # Detection uses the shared normalized control set.
    assert is_global_recommend("按推荐")
    assert is_global_recommend("都按推荐。")
    assert is_global_recommend("ALL RECOMMENDED")
    assert not is_global_recommend("推荐")


# ---------------------------------------------------------------------------
# B301 item 17: defense in depth — runtime never first-match-wins
# ---------------------------------------------------------------------------


def ambiguous_question():
    """A GateQuestion that BYPASSES validation (model_construct), as a
    malformed/corrupt historical artifact would (§2.7)."""
    return GateQuestion.model_construct(
        decision_key="REQ-deadbeef",
        category="REQUIREMENT",
        question="历史行如何处理？",
        why_human="",
        options=[
            GateOption(key="keep", label="保持现状"),
            GateOption(key="legacy", label="保持现状"),
        ],
        recommendation=None,
    )


def test_b301_item17_match_option_fails_closed_on_ambiguity():
    question = ambiguous_question()
    # The shared label matches BOTH options: runtime must NOT silently
    # choose the first option.
    assert match_option(question, "保持现状") is None
    # Unambiguous forms still resolve.
    assert match_option(question, "keep") is question.options[0]
    assert match_option(question, "legacy") is question.options[1]


def test_b301_item17_ambiguous_answer_never_becomes_an_active_decision(repo):
    """End-to-end defense in depth: even if an ambiguous GateQuestion
    somehow reached the answering pass (malformed/corrupt artifact,
    future validator regression), the ambiguous answer stays unresolved
    and never persists a Decision."""
    o = make_orchestrator(
        repo,
        pi=FakePiAdapter(),
        ui=ScriptedUI(interactive=True, answers=["保持现状"]),
    )
    question = ambiguous_question()
    # In-memory corrupt gate (no persistence round-trip; see the test
    # below for the persisted-artifact boundary).
    gate = HumanGate(
        gate_id="HG001",
        category=GateCategory.REQUIREMENT,
        created_in_phase="INTAKE",
        questions=[],
    )
    gate.questions = [question]  # bypass revalidation, like a raw artifact

    o.event("HUMAN_GATE_ASKING", gate_id=gate.gate_id)
    human_gate._ask_pass(o, gate)

    # The ambiguous answer was recorded as an UNMATCHED attempt...
    attempts = [a for a in gate.answers if a.raw == "保持现状"]
    assert attempts and not attempts[0].matched
    # ...validation is not COMPLETE...
    from agent_review.models import AnswerValidation

    assert human_gate.validate_answers(gate.answers) != AnswerValidation.COMPLETE
    # ...and applying answers creates NO Decision from it.
    applied = human_gate.apply_gate_answers(o, gate)
    assert applied == []
    assert o.store.load_decisions().decisions == []


def test_b301_item17_persisted_ambiguous_gate_fails_at_the_load_boundary(repo):
    """A corrupt persisted human-gate.json with an ambiguous question is
    rejected when parsed — the corruption can never silently re-enter
    the workflow through storage."""
    question = ambiguous_question()
    gate = HumanGate.model_construct(
        gate_id="HG001",
        category=GateCategory.REQUIREMENT,
        created_in_phase="INTAKE",
        questions=[question],
    )
    payload = json.dumps(
        {"current": json.loads(gate.model_dump_json()), "gates": [], "next_gate_number": 2},
        ensure_ascii=False,
    )
    from agent_review.models import GateLog

    with pytest.raises(ValidationError, match="exactly one interpretation"):
        GateLog.model_validate_json(payload)


# ---------------------------------------------------------------------------
# N301 items 18-23: intake option cardinality is strictly 2-4
# ---------------------------------------------------------------------------


def suppressed_reasons(o, decision_key=None):
    return [
        e.get("reason", "")
        for e in events_of(o)
        if e["event"] == "HUMAN_CANDIDATE_SUPPRESSED"
        and (decision_key is None or e.get("decision_key") == decision_key)
    ]


def test_n301_item18_intake_candidate_with_one_option_is_suppressed(repo):
    one_option = candidate(
        question="单选项问题？",
        options=[{"key": "only", "label": "唯一选项", "impact": "x"}],
    )
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates([one_option])]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=[]))
    assert o.run() == int(ExitCode.DONE)
    assert any("got 1" in r for r in suppressed_reasons(o))
    assert o.store.load_gate_log().current is None
    assert o.state.budgets.human_interruptions_used == 0


def test_n301_item19_intake_candidate_with_five_options_is_suppressed_not_truncated(repo):
    five_options = candidate(
        question="五选项问题？",
        options=[
            {"key": f"opt{i}", "label": f"选项方案{i}", "impact": "x"}
            for i in range(1, 6)
        ],
        recommendation="opt5",  # points at the option truncation would drop
    )
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates([five_options])]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=[]))
    assert o.run() == int(ExitCode.DONE)
    assert any("got 5" in r for r in suppressed_reasons(o))
    # No gate was created — nothing was silently truncated to four.
    assert o.store.load_gate_log().current is None
    assert not o.store.load_gate_log().gates
    assert o.state.budgets.human_interruptions_used == 0


def test_n301_gate_question_rejects_five_options():
    with pytest.raises(ValidationError, match="requires 2-4 options, got 5"):
        GateQuestion(
            decision_key="K",
            category="REQUIREMENT",
            question="Q?",
            options=[GateOption(key=f"opt{i}", label=f"方案{i}") for i in range(5)],
        )


def test_n301_convergence_candidate_with_five_options_fails_closed(repo):
    options = [
        {"key": f"opt{i}", "label": f"选项方案{i}", "impact": "x"}
        for i in range(1, 6)
    ]
    o = make_convergence_flow(
        repo, needs_new_result(options=options), ui_answers=[]
    )
    assert o.run() == int(ExitCode.HUMAN_HANDOFF)
    assert "requires 2-4 options, got 5" in (o.state.handoff_reason or "")
    assert o.store.load_gate_log().current is None
    assert o.state.budgets.human_interruptions_used == 0


def test_n301_item20_exactly_two_options_works(repo):
    two = candidate(
        question="两选项问题？",
        options=[
            {"key": "a", "label": "方案甲", "impact": "x"},
            {"key": "b", "label": "方案乙", "impact": "y"},
        ],
    )
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates([two])]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=["2"]))
    assert o.run() == int(ExitCode.DONE)
    decisions = o.store.load_decisions().decisions
    assert decisions and decisions[0].selected_option_key == "b"
    assert o.state.budgets.human_interruptions_used == 1


def test_n301_item21_exactly_four_options_works(repo):
    four = candidate(
        question="四选项问题？",
        options=[
            {"key": f"opt{i}", "label": f"方案{i}", "impact": "x"}
            for i in range(1, 5)
        ],
        recommendation="opt4",
    )
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates([four])]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=["4"]))
    assert o.run() == int(ExitCode.DONE)
    # Numeric alias 4 resolves — the fourth option was NOT dropped.
    decisions = o.store.load_decisions().decisions
    assert decisions and decisions[0].selected_option_key == "opt4"
    gate = o.store.load_gate_log().gates[0]
    assert len(gate.questions[0].options) == 4


def test_n301_item23_suppression_reason_is_deterministic_and_auditable(repo):
    five_options = candidate(
        question="审计原因问题？",
        options=[
            {"key": f"opt{i}", "label": f"方案{i}", "impact": "x"}
            for i in range(1, 6)
        ],
    )
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates([five_options])]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=[]))
    assert o.run() == int(ExitCode.DONE)
    reasons = suppressed_reasons(o)
    assert "requires 2-4 meaningful options, got 5" in reasons
    # The same deterministic reason reappears on intake re-runs (stable
    # across revisions), never a truncation artifact.
    assert all("truncat" not in r.lower() for r in reasons)
