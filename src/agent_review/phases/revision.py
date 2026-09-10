"""REVISION phase: Pi performs a targeted revision of blocked blockers only."""

from __future__ import annotations

from agent_review.models import (
    ExitCode,
    IssueSeverity,
    IssueStatus,
    Phase,
)
from agent_review.rendering import render_proposal


def run(o) -> ExitCode | None:
    from agent_review.phases.review import _need_human_ids
    from agent_review.phases.human_gate import try_gate_for_need_human_issues

    human_ids = _need_human_ids(o)
    if human_ids:
        return try_gate_for_need_human_issues(o, human_ids)
    if o.state.budgets.revision_used >= o.state.limits.max_revision_rounds:
        o.fail("REVISION reached with revision budget exhausted")
        return int(ExitCode.FAILED)
    o.state.budgets.revision_used += 1
    o.event("REVISION_STARTED", round=o.state.round)

    contract = o.store.load_contract()
    proposal = o.store.load_proposal()
    log = o.store.load_issues()
    open_blockers = [
        i
        for i in log.issues
        if i.severity == IssueSeverity.BLOCKING
        and i.status in (IssueStatus.OPEN, IssueStatus.ADDRESSED)
    ]
    if contract is None or proposal is None:
        o.fail("REVISION reached without contract/proposal")
        return int(ExitCode.FAILED)

    result = o.pi.revise(o.state, contract, proposal, open_blockers)

    # Persist the revised proposal; keep the previous one in history/.
    o.store.archive_proposal(f"superseded by revision round {o.state.round}")
    result.proposal.based_on_task_revision = o.state.task_revision
    o.store.save_proposal(result.proposal)
    o.store.write_text("proposal.md", render_proposal(result.proposal))

    # Pi may mark issues ADDRESSED; it can never mark them RESOLVED.
    by_id = {i.id: i for i in log.issues}
    for addressed in result.addressed_issues:
        issue = by_id.get(addressed.issue_id)
        if issue is None:
            continue
        if issue.severity != IssueSeverity.BLOCKING:
            continue
        if issue.status not in (IssueStatus.OPEN, IssueStatus.ADDRESSED):
            continue
        issue.status = IssueStatus.ADDRESSED
        issue.addressed_by = addressed.how_addressed
        o.event("ISSUE_ADDRESSED", issue_id=issue.id)
    o.store.save_issues(log)

    o.event("REVISION_COMPLETED", addressed=len(result.addressed_issues))
    o.transition(Phase.CLOSURE_REVIEW)
    return None
