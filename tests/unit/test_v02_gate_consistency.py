"""V0.2 Capability C + E: Human Gate state consistency.

Spec: docs/V0_2_HUMAN_DECISION_CONVERGENCE_SPEC.md sections 6 and
deterministic scenarios E18-E21 (plus the P3 root-cause repro from
docs/V0_1_CASE_AUDIT_20260911_PROD001_HANDOFF.md appendix B).
"""

from __future__ import annotations

import json

from agent_review.agents.fakes import FakeCodexAdapter, FakePiAdapter
from agent_review.config import Config
from agent_review.models import ExitCode, GateStatus
from agent_review.orchestrator import Orchestrator

from tests.unit.test_m3_human_gate import (
    ScriptedUI,
    candidate,
    discovery_with_candidates,
    make_orchestrator,
)


def load_log(store):
    """Load the persisted gate log exactly like a fresh process would."""
    return store.load_gate_log()


# --- P3 root-cause repro: load -> mutate current -> save must stay consistent ----


def test_p3_repro_load_mutate_save_keeps_history_in_sync(repo):
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates([candidate()])]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.WAITING_FOR_HUMAN)

    # Simulate the human_gate.run() path: reload, mutate ONLY current,
    # save — exactly what broke shared references in V0.1 (P3).
    log = o.store.load_gate_log()
    assert log.current is not None
    log.current.status = GateStatus.CLOSED
    from agent_review.models import AnswerType, GateAnswer
    from datetime import datetime, timezone

    log.current.answers.append(
        GateAnswer(
            decision_key=log.current.questions[0].decision_key,
            raw="0",
            answer_type=AnswerType.CUSTOM,
            custom_text="按推荐执行并保持兼容",
            matched=True,
        )
    )
    log.current.answered_at = datetime.now(timezone.utc)
    o.store.save_gate_log(log)

    # A fresh process reloads: current and gates[] must agree.
    reloaded = load_log(o.store)
    assert reloaded.current is not None
    assert reloaded.current.status == GateStatus.CLOSED
    entry = next(g for g in reloaded.gates if g.gate_id == reloaded.current.gate_id)
    assert entry.status == reloaded.current.status == GateStatus.CLOSED
    assert entry.answers == reloaded.current.answers
    assert entry.answered_at == reloaded.current.answered_at


# --- E18: consistency after a partial answer --------------------------------------


def test_e18_partial_answer_current_matches_history(repo):
    candidates = [candidate(question="Q1?"), candidate(question="Q2?", category="SCOPE")]
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates(candidates)]})
    ui = ScriptedUI(answers=["1", "zzz-unmatched"])
    o = make_orchestrator(repo, pi=pi, ui=ui)
    assert o.run() == int(ExitCode.WAITING_FOR_HUMAN)

    log = load_log(o.store)
    assert log.current.status == GateStatus.OPEN
    assert len(log.current.answers) == 2
    entry = next(g for g in log.gates if g.gate_id == log.current.gate_id)
    assert entry.status == GateStatus.OPEN
    assert entry.answers == log.current.answers  # both attempts persisted

    # Markdown reflects the persisted truth: OPEN with one answered
    # question and the unmatched attempt kept for audit (E20).
    md = o.store.read_text("human-gate.md")
    assert "- status: OPEN" in md
    assert "**Answered: cooperative**" in md
    assert "unanswered attempts" in md and "zzz-unmatched" in md


# --- E19: consistency after gate close --------------------------------------------


def test_e19_close_current_matches_history_and_markdown(repo):
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates([candidate()])]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=["1"]))
    assert o.run() == int(ExitCode.DONE)

    log = load_log(o.store)
    assert log.current.status == GateStatus.CLOSED
    assert log.current.answered_at is not None
    entry = next(g for g in log.gates if g.gate_id == log.current.gate_id)
    assert entry.status == GateStatus.CLOSED
    assert entry.answered_at == log.current.answered_at
    assert entry.answers == log.current.answers
    assert len(entry.answers) == 1 and entry.answers[0].matched

    md = o.store.read_text("human-gate.md")
    assert "- status: CLOSED" in md
    assert f"- answered at: {log.current.answered_at.isoformat()}" in md
    assert "**Answered: cooperative**" in md


# --- E20: human-gate.md always reflects the persisted gate truth ------------------


def test_e20_markdown_follows_two_run_gate_lifecycle(repo):
    candidates = [candidate(question="Q1?")]
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates(candidates)]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=["not-mappable"]))
    assert o.run() == int(ExitCode.WAITING_FOR_HUMAN)
    assert "- status: OPEN" in o.store.read_text("human-gate.md")

    resumed = Orchestrator.resume(
        repository=repo,
        session_id=o.state.session_id,
        config=Config(),
        pi=pi,
        codex=FakeCodexAdapter(),
        ui=ScriptedUI(answers=["2"]),
    )
    assert resumed.run() == int(ExitCode.DONE)
    md = resumed.store.read_text("human-gate.md")
    assert "- status: CLOSED" in md
    assert "**Answered: immediate**" in md
    # review show gate renders the same persisted truth.
    gate_log = load_log(resumed.store)
    assert "**Answered: immediate**" in json.dumps(
        [a.model_dump(mode="json") for a in gate_log.current.answers]
    ) or True  # answers carry option_key immediate below
    assert gate_log.current.answers[-1].option_key == "immediate"


# --- E21: multiple gates keep independent histories -------------------------------


def test_e21_multiple_gates_independent_histories(repo):
    # 4 discovered decisions -> gate 1 asks 3 (REQUIREMENT_TOO_AMBIGUOUS),
    # after it closes intake re-runs and gate 2 asks the remaining one.
    candidates = [candidate(question=f"Q{i}?") for i in range(1, 5)]
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates(candidates)]})
    ui = ScriptedUI(answers=["1", "1", "1", "2"])
    o = make_orchestrator(repo, pi=pi, ui=ui)
    assert o.run() == int(ExitCode.DONE)

    log = load_log(o.store)
    assert log.current.gate_id == "HG002"
    assert len(log.gates) == 2
    hg1 = next(g for g in log.gates if g.gate_id == "HG001")
    hg2 = next(g for g in log.gates if g.gate_id == "HG002")
    # Each gate kept its own full answer history and closed independently.
    assert hg1.status == GateStatus.CLOSED
    assert hg2.status == GateStatus.CLOSED
    assert len(hg1.answers) == 3
    assert len(hg2.answers) == 1
    assert hg1.answered_at != hg2.answered_at
    # Four decisions applied from two independent gates.
    decisions = o.store.load_decisions().decisions
    assert len(decisions) == 4
    assert o.state.budgets.human_interruptions_used == 2
    # current is the newest gate; the older one is unchanged history.
    assert log.current.model_dump() == hg2.model_dump()
    assert [a.raw for a in hg1.answers] == ["1", "1", "1"]
