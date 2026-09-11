"""Review phases: INITIAL_REVIEW, CLOSURE_REVIEW, FINAL_REVIEW.

Codex creates Issues and verifies RESOLVED; the orchestrator computes
PASS mechanically and routes by budget.
"""

from __future__ import annotations

from agent_review.agents.base import AgentError
from agent_review.models import (
    ExitCode,
    Issue,
    IssueCategory,
    IssueSeverity,
    IssueStatus,
    PassResult,
    Phase,
)


# ---------------------------------------------------------------------------
# PASS rule
# ---------------------------------------------------------------------------


def compute_pass(
    issues: list[Issue],
    active_gate: str | None,
    proposal_revision: int,
    task_revision: int,
) -> PassResult:
    """Mechanical PASS rule (spec 20). Codex never decides PASS."""
    open_blocking = [
        i.id
        for i in issues
        if i.severity == IssueSeverity.BLOCKING and i.status == IssueStatus.OPEN
    ]
    addressed_blocking = [
        i.id
        for i in issues
        if i.severity == IssueSeverity.BLOCKING and i.status == IssueStatus.ADDRESSED
    ]
    need_human = [i.id for i in issues if i.status == IssueStatus.NEED_HUMAN]
    reasons: list[str] = []
    if open_blocking:
        reasons.append(f"OPEN BLOCKING issues: {', '.join(open_blocking)}")
    if addressed_blocking:
        reasons.append(
            f"ADDRESSED BLOCKING issues awaiting verification: {', '.join(addressed_blocking)}"
        )
    if need_human:
        reasons.append(f"NEED_HUMAN issues: {', '.join(need_human)}")
    if active_gate:
        reasons.append(f"active Human Gate: {active_gate}")
    if proposal_revision != task_revision:
        reasons.append(
            f"proposal is stale (based_on_task_revision={proposal_revision} != {task_revision})"
        )
    return PassResult(
        passed=not reasons,
        open_blocking=open_blocking,
        addressed_blocking=addressed_blocking,
        need_human=need_human,
        active_gate=active_gate is not None,
        stale=proposal_revision != task_revision,
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------


def ingest_new_issues(o, new_issues: list[Issue], provenance: str) -> list[Issue]:
    """Assign stable IDs and persist issues from a review result."""
    log = o.store.load_issues()
    ingested: list[Issue] = []
    for issue in new_issues:
        issue = issue.model_copy(deep=True)
        issue.status = IssueStatus.OPEN
        issue.addressed_by = None
        issue.resolution = None
        issue.covered_by_decisions = []  # reviewer can never forge coverage
        if provenance != "INITIAL_REVIEW":
            issue = _apply_closure_new_issues(o, [issue])[0]
        issue.id = f"R{log.next_issue_number:03d}"
        log.next_issue_number += 1
        issue.provenance = provenance
        issue.based_on_task_revision = o.state.task_revision
        issue.introduced_round = o.state.round
        log.issues.append(issue)
        ingested.append(issue)
        o.event(
            "ISSUE_CREATED",
            issue_id=issue.id,
            severity=issue.severity.value,
            category=issue.category.value,
            provenance=provenance,
        )
    o.store.save_issues(log)
    o.event(
        "ISSUES_INGESTED",
        provenance=provenance,
        total=len(ingested),
        blocking=sum(
            1 for i in ingested if i.severity == IssueSeverity.BLOCKING
        ),
        non_blocking=sum(
            1 for i in ingested if i.severity == IssueSeverity.NON_BLOCKING
        ),
        issue_ids=[i.id for i in ingested],
    )
    return ingested


def current_pass(o) -> PassResult:
    log = o.store.load_issues()
    proposal = o.store.load_proposal()
    return compute_pass(
        log.issues,
        o.state.active_gate,
        proposal.based_on_task_revision if proposal else -1,
        o.state.task_revision,
    )


def _need_human_ids(o) -> list[str]:
    """Flip BLOCKING REQUIREMENT/FACT issues to NEED_HUMAN — audited.

    The flip itself is a routing state change: since V0.2 every
    OPEN -> NEED_HUMAN transition emits an explicit ``ISSUE_NEED_HUMAN``
    event so the audit stream can reconstruct when and why Human
    authority was invoked for an issue (spec V0.2 9).
    """
    log = o.store.load_issues()
    flipped: list[str] = []
    for issue in log.issues:
        if (issue.severity == IssueSeverity.BLOCKING
                and issue.category in (IssueCategory.REQUIREMENT, IssueCategory.FACT)
                and issue.status in (IssueStatus.OPEN, IssueStatus.ADDRESSED)
                and not issue.covered_by_decisions):
            # Issues already proven covered by ACTIVE decisions keep their
            # blocker status but never re-enter the Human authority path.
            issue.status = IssueStatus.NEED_HUMAN
            flipped.append(issue.id)
            o.event(
                "ISSUE_NEED_HUMAN",
                issue_id=issue.id,
                category=issue.category.value,
                reason="blocking REQUIREMENT/FACT issue pending human authority check",
            )
    if flipped:
        o.store.save_issues(log)
    return [i.id for i in log.issues if i.status == IssueStatus.NEED_HUMAN]


def continue_blocker_routing(o, allow_revision: bool) -> ExitCode | None:
    """Normal solution-correction ladder for unresolved blockers.

    Shared by ``route_after_failed_pass`` and the V0.2 authority-check
    routing (issues proven covered by ACTIVE decisions re-enter here
    instead of terminating the session).
    """
    if allow_revision and o.state.budgets.revision_used < o.state.limits.max_revision_rounds:
        o.transition(Phase.REVISION)
        return None
    if o.state.budgets.ablation_used < o.state.limits.max_ablation_rounds:
        o.event("ABLATION_TRIGGERED", reason="blockers unresolved after normal revision/closure")
        o.transition(Phase.ABLATION)
        return None
    o.handoff(
        "convergence budget exhausted: blocking issues remain unresolved "
        f"after revision ({o.state.budgets.revision_used}/"
        f"{o.state.limits.max_revision_rounds}) and ablation "
        f"({o.state.budgets.ablation_used}/{o.state.limits.max_ablation_rounds})"
    )
    return int(ExitCode.HUMAN_HANDOFF)


def route_after_failed_pass(o, allow_revision: bool) -> ExitCode | None:
    """Route when the mechanical PASS rule failed after a review phase.

    V0.2: blocking REQUIREMENT/FACT issues run the Human Authority
    Check before anything terminal happens — already-decided semantics
    route back into the correction ladder; genuinely new Human decisions
    open a bounded Convergence Gate; undeterminable cases fail closed
    to HUMAN_HANDOFF. Otherwise unresolved blockers consume REVISION
    (when allowed and not yet used) or ABLATION budget; exhausted
    budgets are a HUMAN_HANDOFF.
    """
    need_human = _need_human_ids(o)
    if need_human:
        from agent_review.phases import human_gate

        return human_gate.try_gate_for_need_human_issues(
            o, need_human, allow_revision=allow_revision
        )

    return continue_blocker_routing(o, allow_revision)


# ---------------------------------------------------------------------------
# INITIAL_REVIEW
# ---------------------------------------------------------------------------


def run_initial(o) -> ExitCode | None:
    o.state.round += 1
    o.event("INITIAL_REVIEW_STARTED", round=o.state.round)
    contract = o.store.load_contract()
    proposal = o.store.load_proposal()
    if contract is None or proposal is None:
        o.fail("INITIAL_REVIEW reached without contract/proposal")
        return int(ExitCode.FAILED)
    result = o.agent_call(
        "codex",
        "initial_review",
        lambda: o.codex.initial_review(o.state, contract, proposal),
    )
    ingested = ingest_new_issues(o, result.issues, provenance="INITIAL_REVIEW")
    blocking = sum(1 for i in ingested if i.severity == IssueSeverity.BLOCKING)
    non_blocking = sum(1 for i in ingested if i.severity == IssueSeverity.NON_BLOCKING)
    o.event(
        "INITIAL_REVIEW_COMPLETED",
        issues=len(result.issues),
        blocking=blocking,
        non_blocking=non_blocking,
        issue_ids=[i.id for i in ingested],
    )
    pass_result = current_pass(o)
    o.event("PASS_COMPUTED", passed=pass_result.passed, reasons=pass_result.reasons)
    if pass_result.passed:
        o.transition(Phase.FINALIZE)
        return None
    return route_after_failed_pass(o, allow_revision=True)


# ---------------------------------------------------------------------------
# CLOSURE_REVIEW
# ---------------------------------------------------------------------------


def _apply_closure_new_issues(o, new_issues: list[Issue]) -> list[Issue]:
    """Enforce the closure new-blocker restrictions (spec 19).

    A new BLOCKING issue is allowed only as REGRESSION or a truly severe
    MISSED_BLOCKER (why_not_detected_initially present); anything else is
    downgraded to NON_BLOCKING.
    """
    processed: list[Issue] = []
    for issue in new_issues:
        if issue.severity == IssueSeverity.BLOCKING:
            allowed = (
                issue.category == IssueCategory.REGRESSION
                or bool((issue.why_not_detected_initially or "").strip())
            )
            if not allowed:
                issue.severity = IssueSeverity.NON_BLOCKING
                issue.resolution = (
                    "downgraded to NON_BLOCKING: closure review may not raise "
                    "new BLOCKING issues that are neither REGRESSION nor a "
                    "severe missed blocker"
                )
        processed.append(issue)
    return processed


def _remaining_blocker_count(pass_result: PassResult) -> int:
    """Blockers that still prevent mechanical PASS after a review phase."""
    return (
        len(pass_result.open_blocking)
        + len(pass_result.addressed_blocking)
        + len(pass_result.need_human)
    )


def run_closure(o) -> ExitCode | None:
    o.state.round += 1
    o.event("CLOSURE_REVIEW_STARTED", round=o.state.round)
    contract = o.store.load_contract()
    proposal = o.store.load_proposal()
    if contract is None or proposal is None:
        o.fail("CLOSURE_REVIEW reached without contract/proposal")
        return int(ExitCode.FAILED)
    log = o.store.load_issues()
    addressed = [
        i for i in log.issues
        if i.severity == IssueSeverity.BLOCKING and i.status == IssueStatus.ADDRESSED
    ]

    result = o.agent_call(
        "codex",
        "closure_review",
        lambda: o.codex.closure_review(o.state, contract, proposal, addressed),
    )

    by_id = {i.id: i for i in log.issues}
    resolved_here = 0
    for outcome in result.issue_outcomes:
        issue = by_id.get(outcome.issue_id)
        if issue is None or issue.status != IssueStatus.ADDRESSED:
            continue  # unknown or already-terminal issues are not mutated
        if outcome.resolution == "RESOLVED":
            issue.status = IssueStatus.RESOLVED
            issue.resolution = outcome.note or "verified against acceptance criteria"
            resolved_here += 1
            o.event("ISSUE_RESOLVED", issue_id=issue.id)
        else:
            issue.status = IssueStatus.OPEN
            issue.resolution = outcome.note or "acceptance criteria not satisfied"

    o.store.save_issues(log)
    ingested = ingest_new_issues(
        o, result.new_issues, provenance="CLOSURE_REVIEW"
    )
    # Progress truth = post-ingestion, post-lifecycle, post-PASS state:
    # a closure that resolves every addressed blocker but introduces a new
    # blocking regression must never render as an unqualified success.
    pass_result = current_pass(o)
    o.event(
        "CLOSURE_REVIEW_COMPLETED",
        outcomes=len(result.issue_outcomes),
        resolved=resolved_here,
        new_blocking=sum(
            1 for i in ingested if i.severity == IssueSeverity.BLOCKING
        ),
        remaining=_remaining_blocker_count(pass_result),
    )
    o.event("PASS_COMPUTED", passed=pass_result.passed, reasons=pass_result.reasons)
    if pass_result.passed:
        o.transition(Phase.FINALIZE)
        return None
    return route_after_failed_pass(o, allow_revision=False)


# ---------------------------------------------------------------------------
# FINAL_REVIEW (after ABLATION)
# ---------------------------------------------------------------------------


def run_final(o) -> ExitCode | None:
    o.state.round += 1
    o.event("FINAL_REVIEW_STARTED", round=o.state.round)
    contract = o.store.load_contract()
    proposal = o.store.load_proposal()
    if contract is None or proposal is None:
        o.fail("FINAL_REVIEW reached without contract/proposal")
        return int(ExitCode.FAILED)
    log = o.store.load_issues()
    blocking = [
        i for i in log.issues
        if i.severity == IssueSeverity.BLOCKING
        and i.status in (IssueStatus.OPEN, IssueStatus.ADDRESSED)
    ]

    result = o.agent_call(
        "codex",
        "final_review",
        lambda: o.codex.final_review(o.state, contract, proposal, blocking),
    )

    ingest_new_issues(o, result.issues, provenance="FINAL_REVIEW")

    # Apply the reviewer verdict mechanically: blockers verified by the
    # final review are RESOLVED; listed unresolved ones stay unresolved.
    unresolved = set(result.unresolved_issue_ids)
    log = o.store.load_issues()
    for issue in log.issues:
        if (
            issue.severity == IssueSeverity.BLOCKING
            and issue.status == IssueStatus.ADDRESSED
            and issue.id not in unresolved
        ):
            issue.status = IssueStatus.RESOLVED
            issue.resolution = "verified in final review"
            o.event("ISSUE_RESOLVED", issue_id=issue.id)
    o.store.save_issues(log)

    # Progress truth: the reviewer verdict alone is never "requirement
    # satisfied". Emit the orchestrator's combined result (verdict AND
    # mechanical PASS) so rendering can never overstate workflow state.
    pass_result = current_pass(o)
    passed = result.satisfies_requirement and pass_result.passed
    o.event(
        "FINAL_REVIEW_COMPLETED",
        satisfies_requirement=result.satisfies_requirement,
        passed=passed,
        remaining=_remaining_blocker_count(pass_result),
    )
    o.event("PASS_COMPUTED", passed=passed, reasons=pass_result.reasons)
    if passed:
        o.transition(Phase.FINALIZE)
        return None
    # V0.2-RC2 (B201): Final Review obeys the same Human Authority
    # semantics as Initial/Closure Review. A blocking REQUIREMENT/FACT
    # issue no longer terminates the session by category alone: an
    # audited NEED_HUMAN flip runs the Human Authority Check; semantics
    # already covered by an ACTIVE decision route into the correction
    # ladder allowed by the remaining budgets; a genuine new Human
    # decision opens a bounded Convergence Gate
    # (FINAL_REVIEW -> WAITING_FOR_HUMAN) and the workflow rebuilds from
    # the new task revision — it never "continues Final Review in
    # place". Undeterminable packets and exhausted Human budget fail
    # closed to a structured HUMAN_HANDOFF. Codex still never decides
    # PASS: the verdict above only mattered when it passed.
    need_human = _need_human_ids(o)
    if need_human:
        from agent_review.phases import human_gate

        return human_gate.try_gate_for_need_human_issues(
            o, need_human, allow_revision=True
        )
    o.handoff(
        "ablation budget exhausted: design still fails requirement or blockers "
        "remain unresolved after final review"
    )
    return int(ExitCode.HUMAN_HANDOFF)


def run_closure_unimplemented(o) -> ExitCode | None:  # pragma: no cover
    raise AgentError("closure review lands in M2")
