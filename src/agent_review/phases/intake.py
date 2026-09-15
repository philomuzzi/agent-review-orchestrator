"""INTAKE phase: assemble the Change Contract (task.md).

Requirement semantics come from the user's request; current-state facts
come from repository investigation. Intake is deterministic composition,
not an agent call.
"""

from __future__ import annotations

from agent_review.models import (
    AcceptanceCriterion,
    ChangeContract,
    DecisionStatus,
    ExitCode,
    HumanCandidate,
    Phase,
)
from agent_review.phases.human_gate import candidate_key_of
from agent_review.rendering import render_task


def synthesize_acceptance_criteria(o) -> list[AcceptanceCriterion]:
    """B403: deterministically build the current effective Acceptance
    Baseline from persisted current-authority data.

    The orchestrator (never an Agent) owns the baseline:

    - A001 always traces to the original user REQUEST;
    - one criterion per ACTIVE Human Decision, tracing to its decision
      id — every frozen Human Decision is acceptance-relevant;
    - repository constraints / assumptions / open questions never enter
      the authoritative set (they are not Requirement authority).

    INTAKE re-runs after every task-revision bump, so a new Human
    Decision legitimately produces a NEW baseline for the new revision
    (the old audit history stays persisted).
    """
    criteria = [
        AcceptanceCriterion(
            id="A001",
            criterion=f"原始请求的期望行为已交付：{o.state.request.strip()}",
            authority_refs=["REQUEST"],
        )
    ]
    for decision in o.store.load_decisions().decisions:
        if decision.status != DecisionStatus.ACTIVE:
            continue
        criteria.append(
            AcceptanceCriterion(
                id=f"A{len(criteria) + 1:03d}",
                criterion=(
                    f"Human Decision {decision.decision_id}: "
                    f"{decision.question} -> "
                    f"{decision.selected_option_key or decision.answer_text}"
                ),
                authority_refs=[decision.decision_id],
            )
        )
    return criteria


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
        acceptance_criteria=synthesize_acceptance_criteria(o),
    )
    return contract


def collect_human_candidates(o) -> list[HumanCandidate]:
    """Aggregate gate candidates from discovery and investigation.

    B402: ``depends_on`` references are packet-local candidate ids; they
    are resolved to internal decision keys HERE (per source packet) so
    the batching logic never depends on the internal hash.
    """
    candidates: list[HumanCandidate] = []
    discovery = o.store.load_discovery()
    investigation = o.store.load_investigation()
    for source, result in (("DISCOVER", discovery), ("INVESTIGATE", investigation)):
        if result is None:
            continue
        packet = list(result.human_candidates)
        id_keys = {
            (c.candidate_id or "").strip(): candidate_key_of(c)
            for c in packet
            if (c.candidate_id or "").strip()
        }
        for candidate in packet:
            candidate = candidate.model_copy(deep=True)
            candidate.source = candidate.source or source
            candidate.depends_on_keys = [
                id_keys[ref.strip()]
                for ref in candidate.depends_on
                if ref.strip() in id_keys
            ]
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
