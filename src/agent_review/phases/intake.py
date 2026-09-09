"""INTAKE phase: assemble the Change Contract (task.md).

Requirement semantics come from the user's request; current-state facts
come from repository investigation. Intake is deterministic composition,
not an agent call.
"""

from __future__ import annotations

from agent_review.models import (
    ChangeContract,
    DecisionStatus,
    ExitCode,
    HumanCandidate,
    Phase,
)
from agent_review.rendering import render_task


def build_contract(o) -> ChangeContract:
    discovery = o.store.load_discovery()
    investigation = o.store.load_investigation()
    decisions = o.store.load_decisions().decisions
    active = [d for d in decisions if d.status == DecisionStatus.ACTIVE]

    constraints = list(discovery.existing_constraints) if discovery else []
    confirmed = [
        f"[{d.decision_key}] {d.question} -> {d.selected_option_key or d.answer_text}"
        for d in active
    ]
    unknowns = list(discovery.unknowns) if discovery else []

    contract = ChangeContract(
        user_intent=o.state.request,
        current_behavior=(discovery.current_state if discovery else "(pending discovery)"),
        desired_behavior=o.state.request,
        must_preserve=constraints,
        scope=list(discovery.change_surface) if discovery else [],
        known_constraints=constraints,
        assumptions=[],
        confirmed_decisions=confirmed,
        open_questions=unknowns,
        out_of_scope=[
            "Anything not listed in Scope",
            "Refactors not required by this change",
        ],
        root_cause=(
            investigation.root_cause
            if investigation and investigation.root_cause
            else ""
        ),
        based_on_task_revision=o.state.task_revision,
    )
    return contract


def collect_human_candidates(o) -> list[HumanCandidate]:
    """Aggregate gate candidates from discovery and investigation."""
    candidates: list[HumanCandidate] = []
    discovery = o.store.load_discovery()
    investigation = o.store.load_investigation()
    for source, result in (("DISCOVER", discovery), ("INVESTIGATE", investigation)):
        if result is None:
            continue
        for candidate in result.human_candidates:
            candidate = candidate.model_copy(deep=True)
            candidate.source = candidate.source or source
            candidates.append(candidate)
    return candidates


def run(o) -> ExitCode | None:
    o.event("INTAKE_STARTED")
    contract = build_contract(o)
    o.store.save_contract(contract)
    o.store.write_text("task.md", render_task(contract))
    o.event("TASK_CONTRACT_CREATED", task_revision=o.state.task_revision)

    # Human gate evaluation (categories, suppression, budget).
    from agent_review.phases import human_gate

    code = human_gate.evaluate_intake_gate(o)
    if code is not None:
        return code
    if o.state.phase != Phase.INTAKE:
        # A gate was created (phase moved to WAITING_FOR_HUMAN); the
        # orchestrator loop will ask it.
        return None
    o.transition(Phase.DESIGN)
    return None
