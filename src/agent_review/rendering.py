"""Markdown projections of structured session state.

Markdown is human-readable only; the authoritative data lives in the
JSON files written by StateStore.
"""

from __future__ import annotations

from agent_review.models import (
    AblationResult,
    ChangeContract,
    Decision,
    DesignResult,
    DiscoveryResult,
    FinalReviewResult,
    HumanGate,
    InvestigationResult,
    Issue,
    IssueSeverity,
    IssueStatus,
    SessionState,
)


def _bullets(items: list[str], empty: str = "- (none)") -> list[str]:
    return [f"- {item}" for item in items] or [empty]


def _section(title: str, body: str | list[str]) -> str:
    if isinstance(body, list):
        body = "\n".join(body) if body else "(none)"
    body = body.strip() or "(none)"
    return f"## {title}\n\n{body}\n"


def render_discovery(result: DiscoveryResult) -> str:
    parts = [
        "# Repository Discovery",
        "",
        _section("Task Kind", result.task_kind.value),
        _section("Current State", result.current_state),
        _section("Relevant Components", _bullets(result.relevant_components)),
        _section("Existing Constraints", _bullets(result.existing_constraints)),
        _section("Likely Change Surface", _bullets(result.change_surface)),
        _section("Unknowns", _bullets(result.unknowns)),
    ]
    if result.human_candidates:
        lines = []
        for candidate in result.human_candidates:
            lines.append(f"- [{candidate.category}] {candidate.question}")
            if candidate.why:
                lines.append(f"  - why human: {candidate.why}")
        parts.append(_section("Human-Decision Candidates", lines))
    return "\n".join(parts)


def render_investigation(result: InvestigationResult) -> str:
    parts = [
        "# Problem Investigation",
        "",
        _section("Root Cause Status", result.root_cause_status.value),
        _section("Root Cause", result.root_cause),
    ]
    evidence = [
        f"- {e.description}" + (f" (`{e.location}`)" if e.location else "")
        for e in result.evidence
    ]
    parts.append(_section("Evidence", evidence or ["- (none)"]))
    hypotheses = [
        f"- [{h.status}] {h.statement}" for h in result.hypotheses
    ]
    parts.append(_section("Hypotheses", hypotheses or ["- (none)"]))
    parts.append(_section("Causal Chain", _bullets(result.causal_chain)))
    parts.append(_section("Missing Evidence", _bullets(result.missing_evidence)))
    return "\n".join(parts)


def render_task(contract: ChangeContract) -> str:
    parts = [
        "# Change Contract (task)",
        "",
        _section("User Intent", contract.user_intent),
        _section("Current Behavior", contract.current_behavior),
        _section("Desired Behavior", contract.desired_behavior),
        _section("Must Preserve", _bullets(contract.must_preserve)),
        _section("Scope", _bullets(contract.scope)),
        _section("Known Constraints", _bullets(contract.known_constraints)),
    ]
    if contract.root_cause:
        parts.append(_section("Confirmed Root Cause", contract.root_cause))
    if contract.assumptions:
        lines = []
        for idx, a in enumerate(contract.assumptions, 1):
            lines.append(f"### A{idx}")
            lines.append(f"- value: {a.value}")
            lines.append(f"- reason: {a.reason}")
            lines.append(f"- impact_if_wrong: {a.impact_if_wrong}")
        parts.append(_section("Assumptions", lines))
    parts.append(_section("Confirmed Decisions", _bullets(contract.confirmed_decisions)))
    parts.append(_section("Open Questions", _bullets(contract.open_questions)))
    parts.append(_section("Out of Scope", _bullets(contract.out_of_scope)))
    parts.append(f"\n> based_on_task_revision: {contract.based_on_task_revision}\n")
    return "\n".join(parts)


def render_proposal(proposal: DesignResult) -> str:
    parts = [
        "# Design Proposal",
        "",
        _section("Summary", proposal.summary),
        _section("Current Flow", proposal.current_flow),
        _section("Proposed Flow", proposal.proposed_flow),
        _section("Changes", _bullets(proposal.changes)),
        _section("Data Model Changes", _bullets(proposal.data_model_changes)),
        _section("Interface Changes", _bullets(proposal.interface_changes)),
        _section("State / Lifecycle Changes", _bullets(proposal.state_lifecycle_changes)),
        _section("Failure Handling", _bullets(proposal.failure_handling)),
        _section("Compatibility", _bullets(proposal.compatibility)),
        _section("Risks", _bullets(proposal.risks)),
        _section("Alternatives Considered", _bullets(proposal.alternatives_considered)),
        _section("Verification Plan", _bullets(proposal.verification_plan)),
        _section("Explicitly Unchanged", _bullets(proposal.explicitly_unchanged)),
    ]
    cm = proposal.change_map
    parts.append(
        _section(
            "Change Map",
            [
                "### Affected Components",
                *_bullets(cm.affected_components),
                "### Data Changes",
                *_bullets(cm.data_changes),
                "### API Changes",
                *_bullets(cm.api_changes),
                "### Config Changes",
                *_bullets(cm.config_changes),
                "### Behavior Changes",
                *_bullets(cm.behavior_changes),
                "### Unchanged Behaviors",
                *_bullets(cm.unchanged_behaviors),
            ],
        )
    )
    parts.append(
        f"\n> based_on_task_revision: {proposal.based_on_task_revision}\n"
    )
    return "\n".join(parts)


def render_ablation(result: AblationResult) -> str:
    parts = [
        "# Ablation",
        "",
        _section("Rationale", result.rationale),
        _section("Removed", _bullets(result.removed)),
        _section("Addressed Issues", _bullets([a.issue_id for a in result.addressed_issues])),
        _section("Ablated Proposal Summary", result.proposal.summary),
    ]
    return "\n".join(parts)


def render_gate(gate: HumanGate) -> str:
    parts = [
        "# Human Gate",
        "",
        f"- gate id: {gate.gate_id}",
        f"- category: {gate.category.value}",
        f"- created in phase: {gate.created_in_phase}",
        f"- status: {gate.status.value}",
    ]
    if gate.source_issue_ids:
        parts.append(
            f"- derived from review issues: {', '.join(gate.source_issue_ids)}"
        )
    if gate.answered_at is not None:
        parts.append(f"- answered at: {gate.answered_at.isoformat()}")
    parts.append("")
    effective = {a.decision_key: a for a in gate.effective_answers()}
    for q in gate.questions:
        answer = effective.get(q.decision_key)
        category = f" [{q.category}]" if q.category else ""
        parts.append(f"## {q.decision_key}{category}: {q.question}")
        parts.append("")
        if q.why_human:
            parts.append(f"Why human authority is required: {q.why_human}")
            parts.append("")
        for idx, opt in enumerate(q.options, 1):
            marker = " (recommended)" if q.recommendation == opt.key else ""
            parts.append(f"{idx}. [{opt.key}] {opt.label}{marker}")
            if opt.impact:
                parts.append(f"   impact: {opt.impact}")
        parts.append("0. [custom] none of the above — define your own decision")
        if answer is not None and answer.matched:
            parts.append("")
            if answer.answer_type.value == "CUSTOM":
                # Human-defined decision — never presented as an Agent
                # recommendation (V0.2 spec 12).
                parts.append(
                    f"**Human-defined decision: {answer.custom_text}**"
                )
            else:
                parts.append(
                    f"**Answered: {answer.option_key}** (raw: {answer.raw})"
                )
        attempts = [
            a for a in gate.answers if a.decision_key == q.decision_key
        ]
        failed = [a for a in attempts if not a.matched]
        if failed:
            parts.append("")
            parts.append(
                f"- unanswered attempts (superseded, kept for audit): "
                + "; ".join(a.raw or "(empty)" for a in failed)
            )
        parts.append("")
    parts.append(
        "Answer options by number or key; 0/custom enters custom-decision "
        "mode where your own text becomes an authoritative session "
        "decision; '都按推荐' applies recommended options where present."
    )
    return "\n".join(parts)


def render_handoff(
    state,
    issues: list[Issue],
    decisions: list[Decision],
    gate: HumanGate | None,
    reason: str,
    pending_questions: list = None,
) -> str:
    """Structured HUMAN_HANDOFF package (V0.2 spec 8).

    Composed only from persisted artifacts: it reconstructs what the
    Human needs to decide without inventing decisions for them.
    """
    pending_questions = list(pending_questions or [])
    blocking = [
        i
        for i in issues
        if i.severity == IssueSeverity.BLOCKING
        and i.status in (IssueStatus.OPEN, IssueStatus.ADDRESSED, IssueStatus.NEED_HUMAN)
    ]
    active = [d for d in decisions if d.status.value == "ACTIVE"]

    parts = ["# Human Handoff", "", _section("Why the workflow stopped", reason)]

    decide_lines: list[str] = []
    for i in blocking:
        if i.status == IssueStatus.NEED_HUMAN:
            decide_lines.append(
                f"- {i.id} [{i.category.value}]: {i.title} — a Human-owned "
                "decision or fact is required before the design can converge"
            )
    for q in pending_questions:
        decide_lines.append(f"- pending gate question {q.decision_key}: {q.question}")
    if gate is not None and gate.status.value == "OPEN":
        for q in gate.unresolved_questions():
            decide_lines.append(
                f"- open gate question {q.decision_key}: {q.question}"
            )
    if not decide_lines:
        decide_lines = ["- (no explicit decision packet derivable — see blocking issues)"]
    parts.append(_section("What the Human needs to decide / provide", decide_lines))

    issue_lines: list[str] = []
    for i in blocking:
        issue_lines.append(f"### {i.id} [{i.category.value} / {i.status.value}] {i.title}")
        if i.problem:
            issue_lines.append(f"- problem: {i.problem}")
        if i.impact:
            issue_lines.append(f"- impact: {i.impact}")
        if i.acceptance:
            issue_lines.append("- acceptance: " + "; ".join(i.acceptance))
        if i.evidence:
            issue_lines.append("- evidence: " + "; ".join(i.evidence))
        if i.resolution:
            issue_lines.append(f"- note: {i.resolution}")
        issue_lines.append("")
    parts.append(_section("Blocking Issues", issue_lines or ["- (none)"]))

    decision_lines = [
        f"- {d.decision_id} [{d.decision_key}] {d.question} -> "
        f"**{d.selected_option_key or d.answer_text}**"
        + (" (human-defined)" if d.source.value == "CUSTOM" else "")
        for d in active
    ]
    parts.append(_section("Relevant Active Decisions", decision_lines or ["- (none)"]))

    option_lines: list[str] = []
    for q in pending_questions:
        option_lines.append(f"### {q.decision_key}: {q.question}")
        for idx, opt in enumerate(q.options, 1):
            marker = " (recommended)" if q.recommendation == opt.key else ""
            option_lines.append(f"{idx}. [{opt.key}] {opt.label}{marker}")
            if opt.impact:
                option_lines.append(f"   impact: {opt.impact}")
        option_lines.append("")
    if gate is not None and gate.status.value == "OPEN":
        for q in gate.unresolved_questions():
            option_lines.append(f"### {q.decision_key}: {q.question}")
            for idx, opt in enumerate(q.options, 1):
                marker = " (recommended)" if q.recommendation == opt.key else ""
                option_lines.append(f"{idx}. [{opt.key}] {opt.label}{marker}")
                if opt.impact:
                    option_lines.append(f"   impact: {opt.impact}")
            option_lines.append("")
    if not option_lines:
        option_lines = ["- none — no trustworthy decision packet was derivable"]
    parts.append(_section("Suggested Options", option_lines))

    parts.append(
        _section(
            "Relevant Artifacts",
            [
                "- task.md",
                "- proposal.md",
                "- issues.json",
                "- decisions.json",
                "- human-gate.md",
                "- events.jsonl",
            ],
        )
    )

    next_action: list[str] = [
        "This session is terminal and cannot be resumed in place. To continue "
        "the work, start a new session and state the Human conclusions "
        "directly in the request (they become session facts), or supersede "
        "the relevant decisions there."
    ]
    if gate is not None and gate.status.value == "OPEN":
        next_action.insert(
            0,
            "An open Human Gate exists: answer it via 'review resume' only if "
            "the session has not terminated.",
        )
    parts.append(_section("Recommended next action", next_action))
    return "\n".join(parts)


def render_final(
    state: SessionState,
    contract: ChangeContract,
    proposal: DesignResult,
    issues: list[Issue],
    decisions: list[Decision],
    final_review: FinalReviewResult | None = None,
) -> str:
    resolved = [i for i in issues if i.status == IssueStatus.RESOLVED and i.severity == IssueSeverity.BLOCKING]
    accepted_risks = [i for i in issues if i.status == IssueStatus.ACCEPTED_RISK]
    non_blocking = [
        i
        for i in issues
        if i.severity == IssueSeverity.NON_BLOCKING
        and i.status not in (IssueStatus.SUPERSEDED,)
    ]
    active_decisions = [d for d in decisions if d.status.value == "ACTIVE"]

    parts = [
        "# Final Design",
        "",
        _section("Change Goal", f"{contract.user_intent}\n\n{contract.desired_behavior}"),
        _section("Current Behavior", contract.current_behavior),
        _section(
            "Final Design",
            [
                proposal.summary,
                "",
                "### Proposed Flow",
                proposal.proposed_flow or "(as described in summary)",
                "",
                "### Changes",
                *_bullets(proposal.changes),
            ],
        ),
        _section(
            "Affected Components",
            _bullets(proposal.change_map.affected_components),
        ),
        _section("Explicitly Unchanged", _bullets(proposal.explicitly_unchanged)),
        _section("Current Flow", proposal.current_flow),
        _section("Data Model Changes", _bullets(proposal.data_model_changes)),
        _section("Interface Changes", _bullets(proposal.interface_changes)),
        _section("State / Lifecycle Changes", _bullets(proposal.state_lifecycle_changes)),
        _section("Compatibility", _bullets(proposal.compatibility)),
        _section("Data Changes", _bullets(proposal.change_map.data_changes)),
        _section("API Changes", _bullets(proposal.change_map.api_changes)),
        _section("Config Changes", _bullets(proposal.change_map.config_changes)),
        _section("Behavior Changes", _bullets(proposal.change_map.behavior_changes)),
        _section("Unchanged Behaviors", _bullets(proposal.change_map.unchanged_behaviors)),
        _section("Alternatives Considered", _bullets(proposal.alternatives_considered)),
        _section("Must Preserve", _bullets(contract.must_preserve)),
        _section("Scope", _bullets(contract.scope)),
        _section("Known Constraints", _bullets(contract.known_constraints)),
        _section("Out of Scope", _bullets(contract.out_of_scope)),
    ]

    decision_lines = []
    for d in active_decisions:
        if d.source.value == "CUSTOM":
            # Human-defined decision — labeled as such, never presented
            # as an Agent-selected option (V0.2 spec 12).
            decision_lines.append(
                f"- [{d.decision_key}] {d.question} -> **(human-defined)** {d.answer_text}"
            )
        else:
            decision_lines.append(
                f"- [{d.decision_key}] {d.question} -> **{d.selected_option_key or '-'}** ({d.answer_text})"
            )
    parts.append(_section("Confirmed Human Decisions", decision_lines or ["- (none)"]))

    resolved_lines = [
        f"- {i.id}: {i.title} — {i.resolution or 'verified against acceptance criteria'}"
        for i in resolved
    ]
    parts.append(_section("Resolved Blocking Issues", resolved_lines or ["- (none)"]))

    risk_lines = [f"- {i.id}: {i.title}" for i in accepted_risks]
    risk_lines.extend(f"- design risk: {r}" for r in proposal.risks)
    parts.append(_section("Accepted Risks", risk_lines or ["- (none)"]))

    suggestion_lines = [
        f"- {i.id} [{i.status.value}]: {i.title} — {i.problem}" for i in non_blocking
    ]
    parts.append(_section("Non-blocking Suggestions", suggestion_lines or ["- (none)"]))

    parts.append(_section("Verification Plan", _bullets(proposal.verification_plan)))

    notes = [f"- Task kind: {state.task_kind.value}", f"- Task revision: {state.task_revision}"]
    if contract.assumptions:
        for a in contract.assumptions:
            notes.append(f"- Assumption: {a.value} (wrong-impact: {a.impact_if_wrong})")
    for line in proposal.failure_handling:
        notes.append(f"- Failure handling: {line}")
    if contract.root_cause:
        notes.append(f"- Root cause: {contract.root_cause}")
    if final_review is not None:
        notes.append(f"- Final review: {final_review.summary or 'ablated design verified'}")
    parts.append(_section("Implementation Notes", notes))

    parts.append("\n---\n")
    parts.append(
        "This document is implementation-ready: a separate coding agent "
        "with repository access should not need the review history to "
        "implement the change."
    )
    return "\n".join(parts)
