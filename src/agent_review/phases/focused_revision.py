"""FOCUSED_REVISION phase (V0.3 C3).

Corrects a narrow part of an otherwise valid design (validation
evidence, a specific behavior, a transaction boundary, an API detail,
an operability control — any FocusArea). It is a generic mechanism,
NOT validation-specific, and NOT a sequential life after a failed full
revision: it routes only when the reviewer explicitly recommends
FOCUSED_REVISION for the unresolved blockers.

Focused contract (design §35), mechanically enforced where possible:

- preserve ACTIVE Human Decisions — decisions.json is not touched and
  the task revision does NOT change (no basis invalidation happens
  here; a Human Decision change always goes through the gate path);
- preserve explicitly listed invariants — the Author echoes them in
  ``preserved_invariants`` and receives them in the prompt;
- modify only the allowed scope — when the target issues declare an
  explicit ``change_scope``, reported ``changed_sections`` must stay
  within it (admitted out-of-scope changes fail closed);
- respond issue by issue — every target issue needs an
  ``issue_responses`` entry explaining how each close condition is
  satisfied (model-validated);
- no rediscovery — exactly one pi.focused_revise call; DISCOVER is
  never re-run from here.

The reviewer verifies closure afterwards (CLOSURE_REVIEW); the Author
can only mark issues ADDRESSED, exactly like full REVISION.
"""

from __future__ import annotations

from agent_review.agents.base import AgentError
from agent_review.models import (
    ExitCode,
    IssueSeverity,
    IssueStatus,
    Phase,
    design_actual_changed_sections,
    section_within_scope,
)
from agent_review.rendering import render_proposal


def _unresolved_blockers(o) -> list:
    log = o.store.load_issues()
    return [
        i
        for i in log.issues
        if i.severity == IssueSeverity.BLOCKING
        and i.status in (IssueStatus.OPEN, IssueStatus.ADDRESSED)
    ]


def run(o) -> ExitCode | None:
    from agent_review.phases.review import _need_human_ids
    from agent_review.phases.human_gate import try_gate_for_need_human_issues

    human_ids = _need_human_ids(o)
    if human_ids:
        # Same defensive authority-check routing as REVISION/ABLATION: a
        # covered issue reverts to OPEN and this phase's body proceeds; a
        # new Human decision opens a Convergence Gate.
        return try_gate_for_need_human_issues(o, human_ids, continue_routing=False)
    if o.state.budgets.focused_revision_used >= o.state.limits.max_focused_revision_rounds:
        o.fail("FOCUSED_REVISION reached with focused revision budget exhausted")
        return int(ExitCode.FAILED)
    o.state.budgets.focused_revision_used += 1
    o.state.last_correction_action = "FOCUSED_REVISION"

    contract = o.store.load_contract()
    proposal = o.store.load_proposal()
    blockers = _unresolved_blockers(o)
    if contract is None or proposal is None:
        o.fail("FOCUSED_REVISION reached without contract/proposal")
        return int(ExitCode.FAILED)
    if not blockers:
        o.fail("FOCUSED_REVISION reached without unresolved blockers")
        return int(ExitCode.FAILED)

    target_ids = [i.id for i in blockers]
    allowed_scope: list[str] = []
    for issue in blockers:
        for section in issue.change_scope:
            if section not in allowed_scope:
                allowed_scope.append(section)
    # Preserved invariants (design §34/§35): ACTIVE Human Decisions +
    # contract must-preserve entries + the proposal's explicitly
    # unchanged sections — everything the focused fix must not touch.
    from agent_review.models import DecisionStatus

    preserved_invariants: list[str] = [
        f"Human decision [{d.decision_key}] {d.question} -> "
        f"{d.selected_option_key or d.answer_text}"
        for d in o.store.load_decisions().decisions
        if d.status == DecisionStatus.ACTIVE
    ]
    preserved_invariants.extend(contract.must_preserve)
    preserved_invariants.extend(proposal.explicitly_unchanged)
    o.event(
        "FOCUSED_REVISION_STARTED",
        targets=target_ids,
        allowed_scope=allowed_scope or None,
        scope_mode=("explicit" if allowed_scope else "semantic"),
    )

    result = o.agent_call(
        "pi",
        "focused_revise",
        lambda: o.pi.focused_revise(
            o.state, contract, proposal, blockers, allowed_scope, preserved_invariants
        ),
    )

    # ---- mechanical focused-contract checks (fail closed) -------------------
    if sorted(result.target_issue_ids) != sorted(target_ids):
        raise AgentError(
            "focused revision must respond to exactly the routed target "
            f"issues {target_ids}, got {sorted(result.target_issue_ids)}"
        )
    if allowed_scope and result.changed_sections:
        outside = [s for s in result.changed_sections if s not in allowed_scope]
        if outside:
            raise AgentError(
                "focused revision reported changed sections outside the "
                f"allowed change scope {allowed_scope}: {outside}; the "
                "focused contract forbids unrelated redesign"
            )

    # V0.3-RC1 B404: containment validates the ACTUAL serialized proposal
    # delta — Orchestrator-owned truth. The Agent's self-reported
    # changed_sections is explanation/audit only and can NEVER bypass
    # this check (an omitted section is still a violation).
    actual_changed_sections = design_actual_changed_sections(
        proposal, result.proposal
    )
    if allowed_scope:
        outside_actual = [
            section
            for section in actual_changed_sections
            if not section_within_scope(section, allowed_scope)
        ]
        if outside_actual:
            raise AgentError(
                "focused revision actual proposal delta is outside the "
                f"allowed change scope {allowed_scope}: {outside_actual}; "
                "agent-reported changed_sections are not the containment "
                "source of truth (B404)"
            )
    else:
        # Explicitly distinguished from an empty explicit scope: a
        # semantic scope means no mechanical containment exists.
        o.event(
            "FOCUSED_REVISION_SEMANTIC_SCOPE",
            actual_changed_sections=actual_changed_sections,
        )

    # Persist the focused proposal; keep the previous one in history/.
    archived_path = o.store.archive_proposal("superseded by focused revision")
    result.proposal.based_on_task_revision = o.state.task_revision
    o.store.save_proposal(result.proposal)
    o.store.write_text("proposal.md", render_proposal(result.proposal))
    # B404: deterministic correction-delta evidence for Closure Review.
    from agent_review.phases.review import save_correction_delta

    save_correction_delta(
        o,
        {
            "mechanism": "FOCUSED_REVISION",
            "target_issue_ids": list(result.target_issue_ids),
            "previous_proposal_snapshot": str(archived_path)
            if archived_path
            else None,
            "actual_changed_sections": actual_changed_sections,
            "reported_changed_sections": list(result.changed_sections),
            "allowed_change_scope": list(allowed_scope),
            "preserved_invariants": list(result.preserved_invariants),
            "containment": "explicit" if allowed_scope else "semantic",
        },
    )
    o.store.write_text(
        "focused-revision.md",
        (
            "# Focused Revision\n\n"
            f"- target issues: {', '.join(result.target_issue_ids)}\n"
            f"- allowed change scope: "
            f"{'; '.join(result.allowed_change_scope) or '(semantic scope)'}\n"
            "- preserved invariants:\n"
            + "".join(f"  - {p}\n" for p in result.preserved_invariants)
            + "- changed sections:\n"
            + "".join(f"  - {s}\n" for s in result.changed_sections)
            + "- issue responses:\n"
            + "".join(
                f"  - {r.issue_id}: {r.how_addressed}\n"
                for r in result.issue_responses
            )
        ),
    )

    # Pi may mark issues ADDRESSED; it can never mark them RESOLVED.
    log = o.store.load_issues()
    by_id = {i.id: i for i in log.issues}
    for response in result.issue_responses:
        issue = by_id.get(response.issue_id)
        if issue is None or issue.severity != IssueSeverity.BLOCKING:
            continue
        if issue.status not in (IssueStatus.OPEN, IssueStatus.ADDRESSED):
            continue
        issue.status = IssueStatus.ADDRESSED
        issue.addressed_by = response.how_addressed
        o.event("ISSUE_ADDRESSED", issue_id=issue.id)
    o.store.save_issues(log)

    o.event(
        "FOCUSED_REVISION_COMPLETED",
        targets=len(result.target_issue_ids),
        changed_sections=len(result.changed_sections),
        actual_changed_sections=len(actual_changed_sections),
    )
    o.transition(Phase.CLOSURE_REVIEW)
    return None
