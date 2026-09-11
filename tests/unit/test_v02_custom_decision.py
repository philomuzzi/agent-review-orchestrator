"""V0.2 Capability A + D: explicit custom Human decisions and effective
answer validation.

Spec: docs/V0_2_HUMAN_DECISION_CONVERGENCE_SPEC.md sections 4, 7 and
deterministic scenarios A1-A7, F22-F24.
"""

from __future__ import annotations

import json

from agent_review.agents.fakes import FakeCodexAdapter, FakePiAdapter
from agent_review.config import Config
from agent_review.models import (
    AnswerType,
    AnswerValidation,
    DecisionSource,
    ExitCode,
    GateStatus,
    Phase,
)
from agent_review.orchestrator import Orchestrator
from agent_review.phases.human_gate import validate_answers

from tests.unit.test_m3_human_gate import (
    ScriptedUI,
    candidate,
    discovery_with_candidates,
    make_orchestrator,
)


def gate_events(o) -> list[dict]:
    return [
        json.loads(line)
        for line in (o.store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]


# --- A1: offered option answer keeps existing behavior -------------------------


def test_a1_offered_option_answer_unchanged(repo):
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates([candidate()])]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=["1"]))
    assert o.run() == int(ExitCode.DONE)
    decisions = o.store.load_decisions().decisions
    assert len(decisions) == 1
    assert decisions[0].selected_option_key == "cooperative"
    assert decisions[0].source == DecisionSource.OPTION
    assert decisions[0].answer_text == "Cooperative pause between steps"


# --- A2 + A3 + A7: custom decision captured, active, authoritative --------------


def test_a2_custom_decision_persisted_active_cjk(repo):
    custom_text = "允许重跑一轮修复，但只修复当前 PROD-001 受影响店铺，历史其他数据保持不变"
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates([candidate()])]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=["0", custom_text]))
    assert o.run() == int(ExitCode.DONE)

    decisions = o.store.load_decisions().decisions
    assert len(decisions) == 1
    d = decisions[0]
    assert d.source == DecisionSource.CUSTOM
    assert d.selected_option_key is None
    assert d.status.value == "ACTIVE"
    assert d.answer_text == custom_text  # CJK preserved verbatim (A7)

    # A3: the question closed and the design basis changed.
    gate = o.store.load_gate_log().current
    assert gate.status == GateStatus.CLOSED
    assert o.state.task_revision == 2

    # Custom decisions participate as authoritative session facts: the
    # rebuilt contract carries the custom text, and final.md shows it.
    contract = o.store.load_contract()
    assert any(custom_text in line for line in contract.confirmed_decisions)
    final = o.store.read_text("final.md")
    assert custom_text in final
    # Presented as a Human-defined decision, never as an Agent option.
    gate_md = o.store.read_text("human-gate.md")
    assert f"**Human-defined decision: {custom_text}**" in gate_md

    events = gate_events(o)
    assert any(e["event"] == "CUSTOM_DECISION_CAPTURED" for e in events)
    applied = [e for e in events if e["event"] == "DECISION_APPLIED"]
    assert applied and applied[0]["source"] == "CUSTOM"


def test_a2b_custom_via_keyword_selector(repo):
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates([candidate()])]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=["自定义", "按选项二执行"]))
    assert o.run() == int(ExitCode.DONE)
    decisions = o.store.load_decisions().decisions
    assert decisions[0].source == DecisionSource.CUSTOM
    assert decisions[0].answer_text == "按选项二执行"


# --- A4: custom answer does not consume an extra interruption -------------------


def test_a4_custom_answer_no_extra_interruption(repo):
    candidates = [candidate(question="Q1?"), candidate(question="Q2?", category="TRADE_OFF")]
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates(candidates)]})
    # One gate, two questions; one answered by option, one by custom.
    o = make_orchestrator(
        repo, pi=pi, ui=ScriptedUI(answers=["1", "0", "全部保持现状，仅新增路径生效"])
    )
    assert o.run() == int(ExitCode.DONE)
    assert o.state.budgets.human_interruptions_used == 1  # one gate only
    decisions = {d.decision_key: d for d in o.store.load_decisions().decisions}
    assert sum(1 for d in decisions.values() if d.source == DecisionSource.CUSTOM) == 1
    assert sum(1 for d in decisions.values() if d.source == DecisionSource.OPTION) == 1


# --- A5 + A6: unmatched free text never silently becomes a decision --------------


def test_a5_unmatched_free_text_stays_unresolved(repo):
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates([candidate()])]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=["是否可以重跑一轮进行修复？"]))
    code = o.run()
    assert code == int(ExitCode.WAITING_FOR_HUMAN)
    # No decision was granted authority from a question-like answer.
    assert o.store.load_decisions().decisions == []
    gate = o.store.load_gate_log().current
    assert gate.status == GateStatus.OPEN
    attempts = [a for a in gate.answers if a.decision_key == gate.questions[0].decision_key]
    assert attempts and attempts[-1].answer_type == AnswerType.OPTION
    assert not attempts[-1].matched
    # QUESTION_ONLY classification (A6)
    assert validate_answers(gate.answers) == AnswerValidation.QUESTION_ONLY


def test_a5b_prose_answer_is_not_custom(repo):
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates([candidate()])]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=["我觉得还是修一下比较好"]))
    assert o.run() == int(ExitCode.WAITING_FOR_HUMAN)
    assert o.store.load_decisions().decisions == []


def test_a5c_empty_custom_text_keeps_question_unresolved(repo):
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates([candidate()])]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=["0", "   "]))
    assert o.run() == int(ExitCode.WAITING_FOR_HUMAN)
    assert o.store.load_decisions().decisions == []


# --- F22 + F24: later valid answers supersede earlier failed attempts -----------


def test_f22_unmatched_then_custom_reaches_complete_and_done(repo):
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates([candidate()])]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=["banana prose"]))
    assert o.run() == int(ExitCode.WAITING_FOR_HUMAN)

    resumed = Orchestrator.resume(
        repository=repo,
        session_id=o.state.session_id,
        config=Config(),
        pi=pi,
        codex=FakeCodexAdapter(),
        ui=ScriptedUI(answers=["0", "按精确匹配口径重算统计"]),
    )
    assert resumed.run() == int(ExitCode.DONE)
    gate_log = resumed.store.load_gate_log()
    gate = gate_log.current
    assert gate.status == GateStatus.CLOSED

    # Historical failed attempt remains auditable (F23) ...
    key = gate.questions[0].decision_key
    attempts = [a for a in gate.answers if a.decision_key == key]
    assert len(attempts) == 2
    assert attempts[0].raw == "banana prose" and not attempts[0].matched
    # ... but effective validation is COMPLETE (F22): the latest custom
    # answer is the effective one (F24).
    assert validate_answers(gate.answers) == AnswerValidation.COMPLETE
    decisions = resumed.store.load_decisions().decisions
    assert decisions[0].source == DecisionSource.CUSTOM
    assert decisions[0].answer_text == "按精确匹配口径重算统计"
    events = gate_events(resumed)
    validated = [e for e in events if e["event"] == "HUMAN_GATE_ANSWERS_VALIDATED"]
    assert validated[-1]["result"] == "COMPLETE"


def test_f23_unmatched_history_does_not_poison_validation(repo):
    from agent_review.models import GateAnswer

    key = "REQ-deadbeef"
    answers = [
        GateAnswer(decision_key=key, raw="是否可以重跑？", matched=False),
        GateAnswer(decision_key=key, raw="2", option_key="immediate", matched=True),
    ]
    assert validate_answers(answers) == AnswerValidation.COMPLETE
    # Latest unmatched attempt after a valid one keeps it unresolved:
    # the latest effective answer per key is the truth (any unresolved
    # classification — AMBIGUOUS or QUESTION_ONLY — never COMPLETE).
    answers.append(GateAnswer(decision_key=key, raw="嗯？", matched=False))
    assert validate_answers(answers) != AnswerValidation.COMPLETE


# --- Custom prompt surfaces (spec 12) -------------------------------------------


def test_custom_path_advertised_in_question_output(repo):
    class AskCapturingUI(ScriptedUI):
        def __init__(self, answers):
            super().__init__(answers=answers)
            self.ask_prompts: list[str] = []

        def ask(self, prompt: str) -> str:
            self.ask_prompts.append(prompt)
            return super().ask(prompt)

    pi = FakePiAdapter(script={"discover": [discovery_with_candidates([candidate()])]})
    ui = AskCapturingUI(answers=["1"])
    o = make_orchestrator(repo, pi=pi, ui=ui)
    assert o.run() == int(ExitCode.DONE)
    question_block = "\n".join(ui.prompts + ui.ask_prompts)
    assert "0. [custom]" in question_block
    assert "0=custom" in question_block
    # Unmatched feedback mentions the custom path.
    pi2 = FakePiAdapter(script={"discover": [discovery_with_candidates([candidate()])]})
    ui2 = ScriptedUI(answers=["zzz", "1"])
    o2 = make_orchestrator(repo, pi=pi2, ui=ui2)
    assert o2.run() == int(ExitCode.DONE)
    assert any("use 0/custom" in p for p in ui2.prompts)


def test_custom_decision_supersedes_prior_active_decision(repo):
    """A custom re-decision supersedes an earlier ACTIVE decision (11.2)."""
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates([candidate()])]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=["1"]))
    assert o.run() == int(ExitCode.DONE)

    # Re-open the same question via a direct second gate (test harness).
    from agent_review.models import GateAnswer, GateQuestion, GateOption

    log = o.store.load_gate_log()
    question = GateQuestion(
        decision_key=o.store.load_decisions().decisions[0].decision_key,
        category="REQUIREMENT",
        question="Which pause semantics are required?",
        options=[
            GateOption(key="cooperative", label="Cooperative pause between steps"),
            GateOption(key="immediate", label="Immediate abort of current step"),
        ],
    )
    from agent_review.phases.human_gate import apply_gate_answers

    gate2 = HumanGateFake(question, [GateAnswer(
        decision_key=question.decision_key,
        raw="0",
        answer_type=AnswerType.CUSTOM,
        custom_text="直接停掉整个任务，不做渐进暂停",
        matched=True,
    )])
    apply_gate_answers(o, gate2)
    decisions = o.store.load_decisions().decisions
    assert len(decisions) == 2  # append-only
    assert decisions[0].status.value == "SUPERSEDED"
    assert decisions[1].status.value == "ACTIVE"
    assert decisions[1].source == DecisionSource.CUSTOM
    assert decisions[1].answer_text == "直接停掉整个任务，不做渐进暂停"


def HumanGateFake(question, answers):
    from agent_review.models import GateCategory, HumanGate

    return HumanGate(
        gate_id="HG002",
        category=GateCategory.REQUIREMENT,
        created_in_phase="INTAKE",
        questions=[question],
        answers=answers,
    )


def test_custom_answer_effective_validation_unit():
    from agent_review.models import GateAnswer

    answers = [
        GateAnswer(decision_key="K1", raw="帮我看看", matched=False),
        GateAnswer(
            decision_key="K1",
            raw="0",
            answer_type=AnswerType.CUSTOM,
            custom_text="维持现状不动",
            matched=True,
        ),
    ]
    assert validate_answers(answers) == AnswerValidation.COMPLETE


def test_custom_decision_labeled_human_defined_in_final(repo):
    custom_text = "按精确匹配口径重算统计并保留原始行"
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates([candidate()])]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=["0", custom_text]))
    assert o.run() == int(ExitCode.DONE)
    final = o.store.read_text("final.md")
    # Labeled as a Human-defined decision, never as an Agent option key.
    assert f"**(human-defined)** {custom_text}" in final
    assert "**cooperative**" not in final
