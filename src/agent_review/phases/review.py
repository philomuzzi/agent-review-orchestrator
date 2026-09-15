"""Review phases: INITIAL_REVIEW, CLOSURE_REVIEW, FINAL_REVIEW.

Codex creates Issues and verifies RESOLVED; the orchestrator computes
PASS mechanically and routes by the generic correction-action contract.

V0.3 changes (design §24–§49):

- C2 — routing is driven by reviewer-RECOMMENDED generic correction
  actions (FULL_REVISION / FOCUSED_REVISION / ABLATION / HUMAN_DECISION
  / STOP + descriptive focus_area). ABLATION is never a default
  fallback: it routes only on an explicit recommendation.
- C4 — the three review phases have differentiated primary
  responsibilities (comprehensive / differential / readiness) while
  late serious blockers stay reportable WITH recorded provenance
  (``origin``); INITIAL_REVIEW accounts for every acceptance criterion
  (``acceptance_coverage``), FINAL_REVIEW re-accounts all of them
  (criteria may not silently disappear); persistent blockers are
  assessed for MATERIAL progress — repeating substantially the same
  failed work stops as DESIGN_NOT_APPROVED instead of burning the
  ladder.
"""

from __future__ import annotations

from agent_review.agents.base import AgentError
from agent_review.models import (
    CorrectionAction,
    CorrectionRecommendation,
    ExitCode,
    Issue,
    IssueCategory,
    IssueSeverity,
    IssueStatus,
    MaterialProgress,
    NewIssueOrigin,
    PassResult,
    Phase,
    ResultStatus,
)


# Deterministic action preference when several actions are recommended
# for different unresolved blockers (design §32): the broadest available
# correction handles all of them in one round. This is a PREFERENCE over
# explicitly recommended actions with remaining budget — never a
# fallback to a mechanism nobody recommended.
ACTION_PRIORITY: tuple[CorrectionAction, ...] = (
    CorrectionAction.FULL_REVISION,
    CorrectionAction.FOCUSED_REVISION,
    CorrectionAction.ABLATION,
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
        reasons.append(f"NEEDS_HUMAN issues: {', '.join(need_human)}")
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


def _apply_late_new_issue_restrictions(o, issue: Issue) -> Issue:
    """Enforce the late-phase new-blocker provenance contract (C4 §43/§45).

    A new BLOCKING issue from CLOSURE/FINAL review must record WHY it
    appeared now (``origin``). Serious late problems are never
    suppressed — the reviewer merely has to carry provenance, which is
    also its quality signal. Anything unexplained is downgraded to
    NON_BLOCKING exactly like the V0 closure restriction did.

    Backward-compatible default: a REGRESSION-categorized issue is the
    canonical ``INTRODUCED_BY_CORRECTION`` case, so the origin is
    filled deterministically when the reviewer omitted it.
    """
    if issue.severity != IssueSeverity.BLOCKING:
        return issue
    if issue.origin is None and issue.category == IssueCategory.REGRESSION:
        issue.origin = NewIssueOrigin.INTRODUCED_BY_CORRECTION
    if issue.origin is None:
        issue.severity = IssueSeverity.NON_BLOCKING
        issue.resolution = (
            "downgraded to NON_BLOCKING: a new BLOCKING issue in a later "
            "review phase must record origin "
            "(INTRODUCED_BY_CORRECTION | PREVIOUS_REVIEW_MISS | NEW_EVIDENCE | "
            "DIRECTLY_REQUIRED_FOR_CLOSURE)"
        )
    elif (
        issue.origin == NewIssueOrigin.PREVIOUS_REVIEW_MISS
        and not (issue.why_not_detected_initially or "").strip()
    ):
        issue.severity = IssueSeverity.NON_BLOCKING
        issue.resolution = (
            "downgraded to NON_BLOCKING: PREVIOUS_REVIEW_MISS blockers must "
            "explain why the issue was not detected in the initial review"
        )
    return issue


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
            issue = _apply_late_new_issue_restrictions(o, issue)
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
            origin=issue.origin.value if issue.origin else None,
            correction_action=issue.correction_action.value
            if issue.correction_action
            else None,
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
    """Flip blockers needing Human authority to NEED_HUMAN — audited.

    V0.2 category rule: a BLOCKING REQUIREMENT/FACT issue must run the
    Human Authority Check before anything terminal. V0.3 adds the
    generic-correction dimension: a reviewer may also RECOMMEND
    ``HUMAN_DECISION`` on an engineering-categorized issue — the same
    authority check resolves it (design §29), where existing ACTIVE
    decisions may still convert the issue back into an engineering
    correction.
    """
    log = o.store.load_issues()
    flipped: list[str] = []
    for issue in log.issues:
        if issue.severity != IssueSeverity.BLOCKING:
            continue
        if issue.status not in (IssueStatus.OPEN, IssueStatus.ADDRESSED):
            continue
        if issue.covered_by_decisions:
            # Issues already proven covered by ACTIVE decisions keep their
            # blocker status but never re-enter the Human authority path.
            continue
        category_driven = issue.category in (IssueCategory.REQUIREMENT, IssueCategory.FACT)
        recommended = issue.correction_action == CorrectionAction.HUMAN_DECISION
        if not (category_driven or recommended):
            continue
        issue.status = IssueStatus.NEED_HUMAN
        flipped.append(issue.id)
        o.event(
            "ISSUE_NEED_HUMAN",
            issue_id=issue.id,
            category=issue.category.value,
            reason=(
                "blocking REQUIREMENT/FACT issue pending human authority check"
                if category_driven
                else "reviewer recommends HUMAN_DECISION; pending human authority check"
            ),
        )
    if flipped:
        o.store.save_issues(log)
    return [i.id for i in log.issues if i.status == IssueStatus.NEED_HUMAN]


# ---------------------------------------------------------------------------
# C2: generic correction routing (design §32)
# ---------------------------------------------------------------------------


def _default_recommendation(issue: Issue) -> CorrectionRecommendation:
    action = issue.correction_action
    if action is None or action == CorrectionAction.HUMAN_DECISION:
        # No explicit recommendation -> conservative default FULL_REVISION
        # (pre-V0.3 behavior for unresolved engineering blockers). A
        # HUMAN_DECISION recommendation that still reaches this engine
        # has already been through the Human Authority Check and been
        # proven covered (or routed) — the remaining work is an
        # engineering gap, so the default applies there too.
        action = CorrectionAction.FULL_REVISION
    return CorrectionRecommendation(
        issue_id=issue.id,
        correction_action=action,
        focus_area=issue.focus_area,
    )


def recommendations_for_unresolved_blockers(o) -> list[CorrectionRecommendation]:
    """Collect current recommendations from persisted unresolved blockers."""
    log = o.store.load_issues()
    return [
        _default_recommendation(i)
        for i in log.issues
        if i.severity == IssueSeverity.BLOCKING
        and i.status in (IssueStatus.OPEN, IssueStatus.ADDRESSED)
    ]


def _budget_remaining(o, action: CorrectionAction) -> bool:
    if action == CorrectionAction.FULL_REVISION:
        return o.state.budgets.revision_used < o.state.limits.max_revision_rounds
    if action == CorrectionAction.FOCUSED_REVISION:
        return (
            o.state.budgets.focused_revision_used
            < o.state.limits.max_focused_revision_rounds
        )
    if action == CorrectionAction.ABLATION:
        return o.state.budgets.ablation_used < o.state.limits.max_ablation_rounds
    return False


def route_engineering_correction(
    o,
    recommendations: list[CorrectionRecommendation] | None = None,
    attempted_action: CorrectionAction | None = None,
) -> ExitCode | None:
    """Deterministic execution of the recommended correction action.

    Agents recommend; this function controls (design §32). Stop
    conditions (design §30/§48):

    - any unresolved blocker recommends STOP;
    - a blocker shows NO material progress and the next proposed action
      would repeat substantially the same work;
    - no recommended action has remaining budget (mechanisms are not
      sequential lives — ABLATION in particular never fires without an
      explicit recommendation).

    Every stop lands as a precise DESIGN_NOT_APPROVED terminal result,
    never as an ambiguous handoff and never as NEEDS_HUMAN_DECISION
    (Agent convergence failure is not a Human decision need).
    """
    if not recommendations:
        recommendations = recommendations_for_unresolved_blockers(o)
    if not recommendations:
        # No unresolved blockers left (e.g. everything flipped NEED_HUMAN
        # and was routed): nothing to correct here.
        o.handoff(
            "correction routing reached without correctable blockers",
            result_status=ResultStatus.DESIGN_NOT_APPROVED.value,
        )
        return int(ExitCode.HUMAN_HANDOFF)

    stop_reasons: list[str] = []
    stop_ids = [
        r.issue_id for r in recommendations
        if r.correction_action == CorrectionAction.STOP
    ]
    if stop_ids:
        stop_reasons.append(
            "reviewer recommends STOP for " + ", ".join(stop_ids)
        )
    if attempted_action is not None:
        repeat_ids = [
            r.issue_id
            for r in recommendations
            if r.material_progress == MaterialProgress.NO_PROGRESS
            and r.correction_action == attempted_action
        ]
        if repeat_ids:
            stop_reasons.append(
                "no material progress on "
                + ", ".join(repeat_ids)
                + f" and the next proposed action ({attempted_action.value}) "
                "would repeat substantially the same work"
            )
            o.event(
                "NO_MATERIAL_PROGRESS_STOP",
                issue_ids=repeat_ids,
                attempted_action=attempted_action.value,
            )

    executable = [
        action
        for action in ACTION_PRIORITY
        if any(r.correction_action == action for r in recommendations)
        and _budget_remaining(o, action)
    ]
    if not executable:
        recommended = sorted(
            {
                r.correction_action.value
                for r in recommendations
                if r.correction_action in ACTION_PRIORITY
            }
        )
        stop_reasons.append(
            "no recommended corrective action has remaining budget "
            f"(recommended: {recommended or ['FULL_REVISION (default)']}; "
            f"full_revision {o.state.budgets.revision_used}/"
            f"{o.state.limits.max_revision_rounds}, focused_revision "
            f"{o.state.budgets.focused_revision_used}/"
            f"{o.state.limits.max_focused_revision_rounds}, ablation "
            f"{o.state.budgets.ablation_used}/{o.state.limits.max_ablation_rounds})"
        )

    if stop_reasons:
        o.event("CORRECTION_STOPPED", reasons=stop_reasons)
        o.handoff(
            "correction stopped: " + "; ".join(stop_reasons),
            result_status=ResultStatus.DESIGN_NOT_APPROVED.value,
        )
        return int(ExitCode.HUMAN_HANDOFF)

    action = executable[0]
    o.event(
        "CORRECTION_ROUTED",
        action=action.value,
        issue_ids=[r.issue_id for r in recommendations],
    )
    if action == CorrectionAction.FULL_REVISION:
        o.transition(Phase.REVISION)
        return None
    if action == CorrectionAction.FOCUSED_REVISION:
        o.transition(Phase.FOCUSED_REVISION)
        return None
    o.event(
        "ABLATION_TRIGGERED",
        reason="explicit reviewer recommendation: remove/simplify to satisfy "
        "the requirement (never the default fallback)",
    )
    o.transition(Phase.ABLATION)
    return None


def route_after_failed_pass(
    o,
    recommendations: list[CorrectionRecommendation] | None = None,
    attempted_action: CorrectionAction | None = None,
) -> ExitCode | None:
    """Route when the mechanical PASS rule failed after a review phase.

    Human-authority candidates run the V0.2 Human Authority Check first
    (category REQUIREMENT/FACT, or an explicit HUMAN_DECISION
    recommendation): already-decided semantics route back into the
    correction ladder; genuinely new Human decisions open a bounded
    Convergence Gate; undeterminable cases fail closed to a
    NEEDS_HUMAN_DECISION-classified handoff. Remaining engineering
    blockers route through the generic correction engine.
    """
    need_human = _need_human_ids(o)
    if need_human:
        from agent_review.phases import human_gate

        return human_gate.try_gate_for_need_human_issues(o, need_human)

    return route_engineering_correction(
        o, recommendations, attempted_action=attempted_action
    )


# ---------------------------------------------------------------------------
# C4: acceptance coverage accounting (design §40/§44)
# ---------------------------------------------------------------------------


def _validate_acceptance_coverage(result) -> None:
    """Mechanical FAIL-linkage and duplicate checks; fail closed."""
    seen: set[str] = set()
    blocking_titles = {
        i.title for i in result.issues if i.severity == IssueSeverity.BLOCKING
    }
    for entry in result.acceptance_coverage:
        if entry.criterion in seen:
            raise AgentError(
                f"acceptance coverage lists duplicate criterion "
                f"{entry.criterion!r}"
            )
        seen.add(entry.criterion)
        if entry.status == "FAIL" and entry.issue_title not in blocking_titles:
            raise AgentError(
                f"acceptance criterion {entry.criterion!r} marked FAIL must "
                "reference the exact title of a BLOCKING issue in the same "
                f"review result; {entry.issue_title!r} is not one"
            )


def _validate_final_coverage_completeness(o, result) -> None:
    """FINAL_REVIEW may not let criteria silently disappear (§44)."""
    initial = o.store.load_acceptance_coverage()
    if not initial:
        return  # initial review recorded no coverage (legacy/default adapters)
    final_criteria = {e.criterion for e in result.acceptance_coverage}
    missing = [e.criterion for e in initial if e.criterion not in final_criteria]
    if missing or not final_criteria:
        raise AgentError(
            "final review acceptance coverage must re-account every "
            "criterion from the initial review; missing: "
            + ", ".join(missing or ["(no coverage provided)"])
        )


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
    _validate_acceptance_coverage(result)
    ingested = ingest_new_issues(o, result.issues, provenance="INITIAL_REVIEW")
    blocking = sum(1 for i in ingested if i.severity == IssueSeverity.BLOCKING)
    non_blocking = sum(1 for i in ingested if i.severity == IssueSeverity.NON_BLOCKING)
    if result.acceptance_coverage:
        o.store.save_acceptance_coverage(result.acceptance_coverage)
        o.event(
            "ACCEPTANCE_COVERAGE_RECORDED",
            criteria=len(result.acceptance_coverage),
            failed=[
                e.criterion
                for e in result.acceptance_coverage
                if e.status == "FAIL"
            ],
        )
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
    return route_after_failed_pass(
        o,
        recommendations=[
            _default_recommendation(i)
            for i in ingested
            if i.severity == IssueSeverity.BLOCKING
        ]
        or None,
    )


# ---------------------------------------------------------------------------
# CLOSURE_REVIEW
# ---------------------------------------------------------------------------


def _remaining_blocker_count(pass_result: PassResult) -> int:
    """Blockers that still prevent mechanical PASS after a review phase."""
    return (
        len(pass_result.open_blocking)
        + len(pass_result.addressed_blocking)
        + len(pass_result.need_human)
    )


def _closure_recommendations(o, result, ingested) -> list[CorrectionRecommendation]:
    """Merge outcome recommendations with new-issue recommendations."""
    recommendations: list[CorrectionRecommendation] = []
    recommended_ids: set[str] = set()
    for outcome in result.issue_outcomes:
        if outcome.resolution != "UNRESOLVED" or outcome.correction_action is None:
            continue
        recommendations.append(
            CorrectionRecommendation(
                issue_id=outcome.issue_id,
                correction_action=outcome.correction_action,
                focus_area=outcome.focus_area,
                material_progress=outcome.material_progress,
                note=outcome.note,
            )
        )
        recommended_ids.add(outcome.issue_id)
    for issue in ingested:
        if issue.severity == IssueSeverity.BLOCKING and issue.id not in recommended_ids:
            recommendations.append(_default_recommendation(issue))
    # Any other unresolved blocker without an outcome recommendation
    # (e.g. an issue that stayed OPEN while others were attempted).
    for rec in recommendations_for_unresolved_blockers(o):
        if all(r.issue_id != rec.issue_id for r in recommendations):
            recommendations.append(rec)
    return recommendations


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
    attempted = (
        CorrectionAction(o.state.last_correction_action)
        if o.state.last_correction_action
        else None
    )
    return route_after_failed_pass(
        o,
        recommendations=_closure_recommendations(o, result, ingested),
        attempted_action=attempted,
    )


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
        lambda: o.codex.final_review(
            o.state,
            contract,
            proposal,
            blocking,
            acceptance_coverage=o.store.load_acceptance_coverage(),
        ),
    )
    _validate_acceptance_coverage(result)
    _validate_final_coverage_completeness(o, result)

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
    # V0.2-RC2 (B201) + V0.3 C2: blocking REQUIREMENT/FACT issues (and
    # explicit HUMAN_DECISION recommendations) still run the audited
    # Human Authority Check first — covered semantics re-enter the
    # correction ladder, genuine new decisions open a bounded
    # Convergence Gate. Remaining engineering blockers route through the
    # generic correction engine (explicit FOCUSED_REVISION after a late
    # blocker is the c454-P2 remedy: one targeted correction instead of
    # a dead end at zero budget). Codex still never decides PASS: the
    # verdict above only mattered when it passed.
    need_human = _need_human_ids(o)
    if need_human:
        from agent_review.phases import human_gate

        return human_gate.try_gate_for_need_human_issues(o, need_human)
    recommendations = list(result.correction_recommendations)
    covered_ids = {r.issue_id for r in recommendations}
    for rec in recommendations_for_unresolved_blockers(o):
        if rec.issue_id not in covered_ids:
            recommendations.append(rec)
    return route_engineering_correction(
        o,
        recommendations,
        attempted_action=CorrectionAction.ABLATION,
    )
