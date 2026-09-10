"""DESIGN phase: Pi produces the minimum implementable design."""

from __future__ import annotations

from agent_review.models import ExitCode, Phase
from agent_review.rendering import render_proposal


def run(o) -> ExitCode | None:
    o.event("DESIGN_STARTED")
    contract = o.store.load_contract()
    if contract is None:
        o.fail("DESIGN reached without a Change Contract")
        return int(ExitCode.FAILED)
    result = o.agent_call(
        "pi",
        "design",
        lambda: o.pi.design(o.state, contract, discovery=o.store.load_discovery()),
    )
    # The orchestrator (not the agent) owns revision bookkeeping.
    result.based_on_task_revision = o.state.task_revision
    o.store.save_proposal(result)
    o.store.write_text("proposal.md", render_proposal(result))
    o.event(
        "PROPOSAL_CREATED",
        based_on_task_revision=result.based_on_task_revision,
    )
    o.transition(Phase.INITIAL_REVIEW)
    return None
