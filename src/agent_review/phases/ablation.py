"""ABLATION phase: stop patching; find the minimum sufficient design."""

from __future__ import annotations

from agent_review.models import (
    ExitCode,
    IssueSeverity,
    IssueStatus,
    Phase,
)
from agent_review.rendering import render_ablation, render_proposal


def run(o) -> ExitCode | None:
    if o.state.budgets.ablation_used >= o.state.limits.max_ablation_rounds:
        o.fail("ABLATION reached with ablation budget exhausted")
        return int(ExitCode.FAILED)
    o.state.budgets.ablation_used += 1
    o.event("ABLATION_STARTED", round=o.state.round)

    contract = o.store.load_contract()
    proposal = o.store.load_proposal()
    log = o.store.load_issues()
    unresolved = [
        i
        for i in log.issues
        if i.severity == IssueSeverity.BLOCKING
        and i.status in (IssueStatus.OPEN, IssueStatus.ADDRESSED)
    ]
    if contract is None or proposal is None:
        o.fail("ABLATION reached without contract/proposal")
        return int(ExitCode.FAILED)

    result = o.pi.ablate(o.state, contract, proposal, unresolved)

    o.store.archive_proposal(f"superseded by ablation round {o.state.round}")
    result.proposal.based_on_task_revision = o.state.task_revision
    o.store.save_proposal(result.proposal)
    o.store.write_text("proposal.md", render_proposal(result.proposal))
    o.store.write_text("ablation.md", render_ablation(result))

    by_id = {i.id: i for i in log.issues}
    for addressed in result.addressed_issues:
        issue = by_id.get(addressed.issue_id)
        if issue is None or issue.severity != IssueSeverity.BLOCKING:
            continue
        if issue.status not in (IssueStatus.OPEN, IssueStatus.ADDRESSED):
            continue
        issue.status = IssueStatus.ADDRESSED
        issue.addressed_by = addressed.how_addressed
        o.event("ISSUE_ADDRESSED", issue_id=issue.id)
    o.store.save_issues(log)

    o.event("ABLATION_COMPLETED", removed=len(result.removed))
    o.transition(Phase.FINAL_REVIEW)
    return None
