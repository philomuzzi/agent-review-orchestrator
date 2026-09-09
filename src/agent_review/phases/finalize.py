"""FINALIZE phase: render the standalone final.md and close the session."""

from __future__ import annotations

from agent_review.models import ExitCode, Phase, SessionStatus
from agent_review.rendering import render_final


def run(o) -> ExitCode | None:
    o.event("FINALIZE_STARTED")
    contract = o.store.load_contract()
    proposal = o.store.load_proposal()
    if contract is None or proposal is None:
        o.fail("FINALIZE reached without contract/proposal")
        return int(ExitCode.FAILED)
    issues = o.store.load_issues().issues
    decisions = o.store.load_decisions().decisions
    final_md = render_final(o.state, contract, proposal, issues, decisions)
    o.store.write_text("final.md", final_md)
    o.event("FINAL_MD_WRITTEN")
    o.transition(Phase.DONE, status=SessionStatus.DONE)
    o.event("SESSION_DONE")
    return int(ExitCode.DONE)
