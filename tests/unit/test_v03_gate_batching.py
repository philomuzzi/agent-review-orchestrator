"""V0.3 C5 — Human Gate Batching (design §50–§52).

Independent candidates batch into one gate; deferral is allowed ONLY
for candidates whose question/options depend on the current gate's
answers. All V0.2 gate safety constraints (alias space, 2–4 options,
custom decisions, latest-effective answers, per-gate interruption
budget) are preserved.
"""

from __future__ import annotations

import json

from agent_review.agents.fakes import FakePiAdapter
from agent_review.models import GateStatus

from tests.unit.test_m3_human_gate import (
    ScriptedUI,
    candidate,
    discovery_with_candidates,
    make_orchestrator,
)
from tests.unit.test_v02_gate_consistency import load_log


def events_of(o) -> list[dict]:
    return [
        json.loads(line)
        for line in (o.store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def dependent_candidate(question, depends_on, candidate_id="C2"):
    base = candidate(question=question)
    base["candidate_id"] = candidate_id
    base["depends_on"] = depends_on
    return base


def independent_candidate(question, candidate_id="C1"):
    base = candidate(question=question)
    base["candidate_id"] = candidate_id
    base["depends_on"] = []
    return base


def test_six_independent_candidates_one_gate_one_interruption(repo):
    candidates = [candidate(question=f"Q{i}?") for i in range(1, 7)]
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates(candidates)]})
    ui = ScriptedUI(answers=["1"] * 6)
    o = make_orchestrator(repo, pi=pi, ui=ui)
    assert o.run() == 0
    log = load_log(o.store)
    assert len(log.gates) == 1
    assert len(log.gates[0].questions) == 6
    assert o.state.budgets.human_interruptions_used == 1
    assert "REQUIREMENT_TOO_AMBIGUOUS" not in [e["event"] for e in events_of(o)]


def test_seven_independent_candidates_defer_overflow_only(repo):
    candidates = [candidate(question=f"Q{i}?") for i in range(1, 8)]
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates(candidates)]})
    ui = ScriptedUI(answers=["1"] * 7)
    o = make_orchestrator(repo, pi=pi, ui=ui)
    assert o.run() == 0
    log = load_log(o.store)
    assert len(log.gates) == 2
    assert len(log.gates[0].questions) == 6
    assert len(log.gates[1].questions) == 1
    assert o.state.budgets.human_interruptions_used == 2
    events = [e["event"] for e in events_of(o)]
    assert "REQUIREMENT_TOO_AMBIGUOUS" in events


def test_dependent_candidate_defers_to_second_gate(repo):
    """A candidate whose options depend on the current gate's answers is
    the ONLY legitimate deferral (design §51). RC1 B402: the dependency
    is expressed through the PUBLIC packet-local candidate_id protocol —
    no internal decision-key hash is involved."""
    independent = independent_candidate("Storage engine?", "C1")
    dependent = dependent_candidate(
        "Retention window given engine?", depends_on=["C1"], candidate_id="C2"
    )
    pi = FakePiAdapter(
        script={"discover": [discovery_with_candidates([independent, dependent])]}
    )
    ui = ScriptedUI(answers=["1", "1"])
    o = make_orchestrator(repo, pi=pi, ui=ui)
    assert o.run() == 0
    log = load_log(o.store)
    assert len(log.gates) == 2
    assert len(log.gates[0].questions) == 1  # only the independent one
    assert len(log.gates[1].questions) == 1  # the dependent one, after close
    # The internal decision_key identity stays hash-derived and stable.
    from agent_review.phases.human_gate import candidate_decision_key

    assert log.gates[0].questions[0].decision_key == candidate_decision_key(
        "REQUIREMENT", "Storage engine?"
    )
    assert log.gates[1].questions[0].decision_key == candidate_decision_key(
        "REQUIREMENT", "Retention window given engine?"
    )
    deferred = [e for e in events_of(o) if e["event"] == "GATE_CANDIDATE_DEFERRED"]
    assert deferred and deferred[0]["reason"].startswith("question or options depend")
    assert deferred[0]["candidate_ids"] == ["C2"]


def test_dependency_on_already_decided_key_batches_immediately(repo):
    """A depends_on referencing a candidate whose decision is already
    ACTIVE is satisfied — the candidate is NOT deferred."""
    from agent_review.phases.human_gate import candidate_decision_key

    decided_key = candidate_decision_key("REQUIREMENT", "Storage engine?")
    first = independent_candidate("Storage engine?", "C1")
    # Second round of candidates: the dependent question now coexists
    # with an ACTIVE decision satisfying its dependency.
    later = dependent_candidate("Retention policy?", depends_on=["C1"])
    unrelated = candidate(question="Alert threshold?")
    pi = FakePiAdapter(
        script={
            "discover": [
                discovery_with_candidates([first]),
                # a second discover call happens only in problem-mode
                # re-investigation; here the rerun comes from intake
            ]
        }
    )
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=["1"]))
    assert o.run() == 0
    decisions = o.store.load_decisions().decisions
    assert any(d.decision_key == decided_key and d.status.value == "ACTIVE" for d in decisions)
    # Directly exercise the batching logic on a fresh orchestrator whose
    # decisions log already contains the ACTIVE decision.
    from agent_review.models import HumanCandidate, Decision, DecisionStatus
    from agent_review.phases import human_gate

    o2 = make_orchestrator(repo, ui=ScriptedUI(interactive=False))
    while o2.state.phase.value != "INTAKE":
        o2.step()
    log = o2.store.load_decisions()
    log.decisions.append(
        Decision(
            decision_id="D900",
            decision_key=decided_key,
            gate_id="HG000",
            question="Storage engine?",
            selected_option_key="x",
            answer_text="x",
            status=DecisionStatus.ACTIVE,
        )
    )
    o2.store.save_decisions(log)
    later_model = HumanCandidate.model_validate(later)
    unrelated_model = HumanCandidate.model_validate(unrelated)
    # Resolve the packet-local ids the way collect_human_candidates does.
    id_keys = {
        (c.candidate_id or "").strip(): candidate_decision_key(c.category, c.question)
        for c in (later_model, unrelated_model)
        if (c.candidate_id or "").strip()
    }
    later_model.depends_on_keys = [
        id_keys[ref] for ref in later_model.depends_on if ref in id_keys
    ]
    created, code = human_gate._gate_from_candidates(o2, [later_model, unrelated_model])
    assert code is None and created
    log2 = load_log(o2.store)
    assert log2.current is not None
    keys = {q.decision_key for q in log2.current.questions}
    from agent_review.phases.human_gate import candidate_decision_key as cdk

    assert cdk("REQUIREMENT", "Retention policy?") in keys  # batched, not deferred
    assert cdk("REQUIREMENT", "Alert threshold?") in keys
    deferred_events = [
        e for e in events_of(o2) if e["event"] == "GATE_CANDIDATE_DEFERRED"
    ]
    assert not deferred_events


def test_independent_and_dependent_mixed_batching(repo):
    from agent_review.phases.human_gate import candidate_decision_key

    anchor = independent_candidate("Output format?", "C1")
    anchor_key = candidate_decision_key("REQUIREMENT", "Output format?")
    unrelated = candidate(question="Retry budget?")
    dependent = dependent_candidate(
        "Notification channel given format?", depends_on=["C1"], candidate_id="C2"
    )
    pi = FakePiAdapter(
        script={
            "discover": [
                discovery_with_candidates([anchor, unrelated, dependent])
            ]
        }
    )
    ui = ScriptedUI(answers=["1", "1", "1"])
    o = make_orchestrator(repo, pi=pi, ui=ui)
    assert o.run() == 0
    log = load_log(o.store)
    assert len(log.gates) == 2
    hg1_keys = {q.decision_key for q in log.gates[0].questions}
    hg2_keys = {q.decision_key for q in log.gates[1].questions}
    assert anchor_key in hg1_keys
    assert anchor_key not in hg2_keys
    # The unrelated candidate batched with the anchor, not deferred.
    assert len(hg1_keys) == 2
    assert len(hg2_keys) == 1


def test_gate_constraints_preserved_under_batching(repo):
    """V0.2 safety constraints survive the batching change: alias space
    (ambiguous options suppressed, no gate), 2–4 options, custom path."""
    ambiguous = candidate(
        question="Ambiguous options?",
        options=[
            {"key": "a", "label": "same label", "impact": "x"},
            {"key": "b", "label": "same label", "impact": "y"},
        ],
    )
    good = candidate(question="Good question?")
    pi = FakePiAdapter(
        script={"discover": [discovery_with_candidates([ambiguous, good])]}
    )
    ui = ScriptedUI(answers=["0", "use my own judgment here"])
    o = make_orchestrator(repo, pi=pi, ui=ui)
    assert o.run() == 0
    log = load_log(o.store)
    assert len(log.gates) == 1
    gate = log.gates[0]
    assert len(gate.questions) == 1  # ambiguous candidate suppressed
    assert gate.status == GateStatus.CLOSED
    decisions = o.store.load_decisions().decisions
    assert decisions[0].source.value == "CUSTOM"  # custom path still works
    suppressed = [e for e in events_of(o) if e["event"] == "HUMAN_CANDIDATE_SUPPRESSED"]
    assert suppressed
