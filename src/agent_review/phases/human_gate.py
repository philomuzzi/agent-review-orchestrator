"""Human Gate protocol.

Agents emit candidates; only the Orchestrator may pause the workflow.
This module owns:

- candidate aggregation, category filtering and suppression;
- decision packets (max 3 blocking decisions) persisted as
  human-gate.json / human-gate.md;
- interactive answering with natural-language normalization;
- explicit CUSTOM Human Decisions (V0.2 Capability A);
- COMPLETE / PARTIAL / AMBIGUOUS / QUESTION_ONLY validation over the
  latest effective answer per decision_key (V0.2 Capability D);
- append-only decisions with SUPERSEDED semantics;
- task-revision invalidation of stale designs;
- the Human Authority Check routing and the Convergence Gate for
  review-discovered NEED_HUMAN issues (V0.2 Capability B);
- the Human Interruption Budget.
"""

from __future__ import annotations

import hashlib

from agent_review.models import (
    AnswerValidation,
    AnswerType,
    AuthorityOutcome,
    CUSTOM_REQUEST_ANSWERS,
    DECISION_SEMANTIC_CATEGORIES,
    GLOBAL_RECOMMEND_ANSWERS,
    Decision,
    DecisionCandidate,
    DecisionSource,
    DecisionStatus,
    ExitCode,
    GateAnswer,
    GateCategory,
    GateOption,
    GateQuestion,
    GateStatus,
    HumanAuthorityCheckResult,
    HumanCandidate,
    HumanGate,
    IssueStatus,
    Phase,
    SessionStatus,
    TaskKind,
    normalize_answer_text,
    normalized_custom_selector_aliases,
    normalized_global_recommend_aliases,
    normalized_option_aliases,
    option_alias_violation,
)

# Human decision semantic categories for BOTH intake candidates and
# authority-check candidates (V0.2-RC2 B203). CONVERGENCE is a gate
# routing category — never a Human decision semantic.
DECISION_CATEGORIES = set(DECISION_SEMANTIC_CATEGORIES)
MAX_QUESTIONS_PER_GATE = 3
MAX_ANSWER_PASSES = 2  # bounded re-ask rounds before waiting again

# Protocol control commands (V0.2-RC3 B301): defined once in models as
# part of the Human Answer Alias Space and re-exported here for
# compatibility. The SAME constants + normalization drive Gate
# validation, candidate/packet rejection, and runtime matching.
_GLOBAL_RECOMMEND_ALIASES = normalized_global_recommend_aliases()
_CUSTOM_SELECTOR_ALIASES = normalized_custom_selector_aliases()

CUSTOM_DECISION_PROMPT = (
    "Enter your decision (this becomes an authoritative session decision): "
)


# ---------------------------------------------------------------------------
# Candidate filtering
# ---------------------------------------------------------------------------


def candidate_decision_key(category: str, question: str) -> str:
    """Stable decision key derived from the question itself."""
    digest = hashlib.sha1(
        f"{category}|{question}".encode("utf-8")
    ).hexdigest()[:8]
    prefix = (category or "DEC")[:4].upper().replace("_", "")
    return f"{prefix}-{digest}"


def candidate_key_of(candidate: HumanCandidate) -> str:
    return candidate_decision_key(candidate.category, candidate.question)


def eligible_candidates(
    o, candidates: list[HumanCandidate]
) -> tuple[list[HumanCandidate], list[HumanCandidate]]:
    """Filter candidates to gate-worthy questions.

    Returns (eligible, suppressed). Suppression rules (spec 14):
    categories outside the allowed set (naming/taste/extensibility are not
    categories at all), questions whose option count is outside 2-4
    (N301) or whose Human Answer Alias Space is ambiguous (B301).
    Already-decided questions are session facts and are skipped silently.
    """
    decisions = o.store.load_decisions().decisions
    decided = {
        d.decision_key
        for d in decisions
        if d.status == DecisionStatus.ACTIVE
    }
    eligible: list[HumanCandidate] = []
    suppressed: list[HumanCandidate] = []
    reserved = normalized_custom_selector_aliases()
    for candidate in candidates:
        key = candidate_key_of(candidate)
        if candidate.category not in DECISION_CATEGORIES:
            reason = (
                f"category not a Human decision semantic "
                f"(REQUIREMENT/FACT/TRADE_OFF/SCOPE): {candidate.category}"
            )
        elif not (2 <= len(candidate.options) <= 4):
            # N301 (V0.2-RC3): normal Intake enforces the SAME 2-4
            # option cardinality as convergence packets. >4 options is
            # suppressed — never silently truncated to four, which would
            # make the Agent-visible packet differ from the
            # Human-visible one and could orphan a recommendation.
            reason = (
                f"requires 2-4 meaningful options, got {len(candidate.options)}"
            )
        elif any(not op.key.strip() or not op.label.strip() for op in candidate.options):
            reason = "option keys and labels must be non-empty"
        elif any(_norm(op.key) in reserved for op in candidate.options):
            reason = "option key collides with the reserved custom-decision selector"
        elif len({_norm(op.key) for op in candidate.options}) != len(candidate.options):
            # Same invariant as the GateQuestion model boundary
            # (V0.2-RC2 B203.2): options indistinguishable by answer
            # matching must never reach a Human.
            reason = "duplicate option keys after normalization"
        else:
            # B301 (V0.2-RC3): reject the full Human Answer Alias Space
            # ambiguity — duplicate labels, key/label/composite
            # collisions, numeric/选项N collisions and protocol-control
            # collisions — with the shared deterministic reason. No Gate
            # is created and no Human interruption is consumed.
            reason = option_alias_violation(candidate.options)
        if reason is not None:
            suppressed.append(candidate)
            o.event("HUMAN_CANDIDATE_SUPPRESSED", decision_key=key, reason=reason)
        elif key in decided:
            # Human answer is session fact; never re-ask unless superseded.
            continue
        else:
            eligible.append(candidate)
    return eligible, suppressed


def _to_question(candidate: HumanCandidate) -> GateQuestion:
    # N301 (V0.2-RC3): consume the ALREADY VALIDATED option list —
    # eligible_candidates enforced 2-4 options, so there is nothing to
    # truncate and invalid cardinality can no longer be hidden by slicing.
    options = [
        GateOption(key=o.key, label=o.label, impact=o.impact)
        for o in candidate.options
    ]
    return GateQuestion(
        decision_key=candidate_key_of(candidate),
        category=candidate.category,
        question=candidate.question,
        why_human=candidate.why,
        options=options,
        recommendation=candidate.recommendation,
    )


# ---------------------------------------------------------------------------
# Gate creation
# ---------------------------------------------------------------------------


def compute_resume_semantics(questions: list[GateQuestion]) -> str:
    """Deterministic resume semantic for a Convergence Gate (B202).

    ``CONVERGENCE`` records WHERE the gate came from; this function
    records WHAT KIND of Human decision it establishes, derived from
    the validated question categories:

    - any FACT question forces ``FACT`` — a Problem-Mode session must
      re-investigate with the new Human fact instead of combining it
      with a stale root-cause model (conservative mixed-packet rule);
    - a single common category is preserved verbatim;
    - mixed non-FACT packets are ``MIXED`` and resume through INTAKE.
    """
    categories = {(q.category or "").strip().upper() for q in questions}
    categories.discard("")
    if "FACT" in categories:
        return GateCategory.FACT.value
    if len(categories) == 1:
        return next(iter(categories))
    return "MIXED"


def create_gate(
    o,
    questions: list[GateQuestion],
    remaining_keys: list[str] | None = None,
    source_issue_ids: list[str] | None = None,
    resume_semantics: str = "",
) -> HumanGate | None:
    """Create the decision packet; None means the interruption budget said no."""
    if o.state.budgets.human_interruptions_used >= o.state.limits.max_human_interruptions:
        o.handoff(
            "Human interruption budget exhausted "
            f"({o.state.budgets.human_interruptions_used}/"
            f"{o.state.limits.max_human_interruptions}); unresolved decisions: "
            + ", ".join(q.decision_key for q in questions),
            pending_questions=questions,
        )
        return None

    log = o.store.load_gate_log()
    is_convergence = bool(source_issue_ids)
    gate = HumanGate(
        gate_id=f"HG{log.next_gate_number:03d}",
        category=(
            GateCategory.CONVERGENCE
            if is_convergence
            else (GateCategory(questions[0].category) if questions else GateCategory.REQUIREMENT)
        ),
        created_in_phase=o.state.phase.value,
        questions=questions[:MAX_QUESTIONS_PER_GATE],
        remaining_candidate_keys=remaining_keys or [],
        source_issue_ids=list(source_issue_ids or []),
        resume_semantics=resume_semantics if is_convergence else "",
    )
    log.next_gate_number += 1
    log.current = gate
    log.gates.append(gate)
    o.store.save_gate_log(log)  # mirrors current into gates[] + re-renders md
    o.state.active_gate = gate.gate_id
    o.state.budgets.human_interruptions_used += 1
    o.event(
        "HUMAN_GATE_CREATED",
        gate_id=gate.gate_id,
        questions=[q.decision_key for q in gate.questions],
        category=gate.category.value,
        source_issue_ids=gate.source_issue_ids,
        resume_semantics=gate.resume_semantics or None,
    )
    if is_convergence:
        o.event(
            "CONVERGENCE_GATE_CREATED",
            gate_id=gate.gate_id,
            questions=[q.decision_key for q in gate.questions],
            source_issue_ids=gate.source_issue_ids,
            resume_semantics=gate.resume_semantics or None,
        )
    o.transition(Phase.WAITING_FOR_HUMAN, status=SessionStatus.RUNNING)
    return gate


# ---------------------------------------------------------------------------
# Answer normalization
# ---------------------------------------------------------------------------


def _norm(text: str) -> str:
    # The canonical normalization lives in models so the shared
    # GateQuestion boundary enforces the same key uniqueness that
    # answer matching relies on (V0.2-RC2 B203.2).
    return normalize_answer_text(text)


def match_option(question: GateQuestion, raw: str) -> GateOption | None:
    """Normalize a Human answer onto exactly one option, or None.

    Resolution uses the SAME ``normalized_option_aliases`` sets as
    GateQuestion validation (RC3 B301 §2.6 single source of truth):
    option key, option label, key + label, numeric index, 选项N and
    "option N", all through ``normalize_answer_text``.

    Defense in depth (RC3 B301 §2.7): a valid GateQuestion makes
    ambiguous matches impossible, but runtime matching must not rely
    on first-match-wins for malformed/corrupt historical artifacts or
    future validator regressions::

        0 matches   -> unmatched (stays unresolved)
        1 match     -> that option
        >1 matches  -> protocol ambiguity; fail closed (None)

    An ambiguity therefore never silently becomes an ACTIVE Decision.
    """
    normalized = _norm(raw)
    if not normalized:
        return None
    matches: list[GateOption] = []
    for index, option in enumerate(question.options, 1):
        if normalized in normalized_option_aliases(option, index):
            matches.append(option)
    if len(matches) == 1:
        return matches[0]
    return None


def is_global_recommend(raw: str) -> bool:
    return _norm(raw) in _GLOBAL_RECOMMEND_ALIASES


def is_custom_request(raw: str) -> bool:
    """True only for the EXPLICIT custom-decision selectors (spec 4.1).

    Any other unmatched free text stays an unresolved attempt; it never
    silently becomes an authoritative CUSTOM decision.
    """
    return _norm(raw) in _CUSTOM_SELECTOR_ALIASES


def normalize_answer(question: GateQuestion, raw: str) -> GateAnswer:
    """One answer -> GateAnswer; recommendation shortcut honored only
    when the question actually has a recommended option."""
    if is_global_recommend(raw):
        if question.recommendation:
            option = next(
                (o for o in question.options if o.key == question.recommendation), None
            )
            if option is not None:
                return GateAnswer(
                    decision_key=question.decision_key,
                    raw=raw,
                    option_key=option.key,
                    matched=True,
                )
        return GateAnswer(decision_key=question.decision_key, raw=raw, matched=False)
    option = match_option(question, raw)
    if option is not None:
        return GateAnswer(
            decision_key=question.decision_key,
            raw=raw,
            option_key=option.key,
            matched=True,
        )
    return GateAnswer(decision_key=question.decision_key, raw=raw, matched=False)


def effective_answers(answers: list[GateAnswer]) -> list[GateAnswer]:
    """Latest answer per decision_key (V0.2 Capability D)."""
    latest: dict[str, GateAnswer] = {}
    for answer in answers:
        latest[answer.decision_key] = answer
    return list(latest.values())


def validate_answers(answers: list[GateAnswer]) -> AnswerValidation:
    """Batch validation over the LATEST effective answer per key.

    Historical unmatched attempts stay in the audit trail but no longer
    make a fully answered gate appear PARTIAL forever: when every gate
    question has a later valid answer the result must be COMPLETE.
    """
    effective = effective_answers(answers)
    if not effective:
        return AnswerValidation.AMBIGUOUS
    matched = [a for a in effective if a.matched]
    if len(matched) == len(effective):
        return AnswerValidation.COMPLETE
    if matched:
        return AnswerValidation.PARTIAL
    question_only = all(
        a.raw.strip().endswith("?") or a.raw.strip().endswith("？") for a in effective
    )
    return AnswerValidation.QUESTION_ONLY if question_only else AnswerValidation.AMBIGUOUS


# ---------------------------------------------------------------------------
# Decision application
# ---------------------------------------------------------------------------


def apply_gate_answers(o, gate: HumanGate) -> list[Decision]:
    """Append decisions for valid effective answers; supersede prior ACTIVE ones.

    Both offered-option and CUSTOM decisions are first-class: a valid
    custom decision behaves exactly like a valid offered option (V0.2
    spec 4.3 / 11.2).
    """
    log = o.store.load_decisions()
    questions = {q.decision_key: q for q in gate.questions}
    applied: list[Decision] = []
    for answer in gate.effective_answers():
        if not answer.matched:
            continue
        question = questions.get(answer.decision_key)
        if question is None:
            continue
        decision_id = f"D{log.next_decision_number:03d}"
        log.next_decision_number += 1
        if answer.answer_type == AnswerType.CUSTOM:
            option_label = ""
        else:
            option_label = ""
            for option in question.options:
                if option.key == answer.option_key:
                    option_label = option.label
                    break
        decision = Decision(
            decision_id=decision_id,
            decision_key=question.decision_key,
            gate_id=gate.gate_id,
            question=question.question,
            selected_option_key=answer.option_key,
            answer_text=option_label or (answer.custom_text or "") or answer.raw,
            source=(
                DecisionSource.CUSTOM
                if answer.answer_type == AnswerType.CUSTOM
                else DecisionSource.OPTION
            ),
            status=DecisionStatus.ACTIVE,
        )
        for prior in log.decisions:
            if (
                prior.decision_key == question.decision_key
                and prior.status == DecisionStatus.ACTIVE
            ):
                prior.status = DecisionStatus.SUPERSEDED
                prior.superseded_by = decision_id
                o.event(
                    "DECISION_SUPERSEDED",
                    decision_id=prior.decision_id,
                    by=decision_id,
                )
        log.decisions.append(decision)
        applied.append(decision)
        if answer.answer_type == AnswerType.CUSTOM:
            o.event(
                "CUSTOM_DECISION_CAPTURED",
                decision_id=decision_id,
                decision_key=question.decision_key,
                gate_id=gate.gate_id,
            )
        o.event(
            "DECISION_APPLIED",
            decision_id=decision_id,
            decision_key=question.decision_key,
            option=answer.option_key,
            source=decision.source.value,
        )
    o.store.save_decisions(log)
    return applied


def invalidate_design_basis(o, reason: str) -> None:
    """task_revision += 1; old proposal -> history/STALE; open issues stale."""
    archived = False
    if o.store.load_proposal() is not None:
        dest = o.store.archive_proposal(reason)
        if dest is not None:
            archived = True
            o.event("PROPOSAL_STALE", archived=str(dest), reason=reason)
    log = o.store.load_issues()
    for issue in log.issues:
        if issue.status in (IssueStatus.OPEN, IssueStatus.ADDRESSED, IssueStatus.NEED_HUMAN):
            issue.status = IssueStatus.SUPERSEDED
            o.event("ISSUE_SUPERSEDED", issue_id=issue.id, reason="task revision changed")
    o.store.save_issues(log)
    o.state.task_revision += 1
    o.store.save_state(o.state)
    o.event(
        "TASK_REVISION_INCREMENTED",
        task_revision=o.state.task_revision,
        reason=reason,
        archived=archived,
    )


# ---------------------------------------------------------------------------
# Gate sources
# ---------------------------------------------------------------------------


def _gate_from_candidates(o, candidates: list[HumanCandidate]) -> tuple[bool, ExitCode | None]:
    """Returns (gate_created, terminal_exit_code)."""
    eligible, _suppressed = eligible_candidates(o, candidates)
    if not eligible:
        return False, None
    questions = [_to_question(c) for c in eligible]
    remaining: list[str] = []
    if len(questions) > MAX_QUESTIONS_PER_GATE:
        # REQUIREMENT_TOO_AMBIGUOUS: ask only the most upstream decisions,
        # then rerun intake within budget.
        remaining = [q.decision_key for q in questions[MAX_QUESTIONS_PER_GATE:]]
        questions = questions[:MAX_QUESTIONS_PER_GATE]
        o.event(
            "REQUIREMENT_TOO_AMBIGUOUS",
            asked=[q.decision_key for q in questions],
            deferred=remaining,
        )
    gate = create_gate(o, questions, remaining_keys=remaining)
    if gate is None:
        return False, int(ExitCode.HUMAN_HANDOFF)
    return True, None


def evaluate_intake_gate(o) -> ExitCode | None:
    """Intake: aggregate candidates and open a gate when required.

    Returns an exit code only for terminal outcomes; a created gate is
    signalled by the phase having changed to WAITING_FOR_HUMAN.
    """
    from agent_review.phases.intake import collect_human_candidates

    candidates = collect_human_candidates(o)
    _created, code = _gate_from_candidates(o, candidates)
    return code


def try_gate_for_unresolved_root_cause(o, result) -> ExitCode | None:
    """Problem Mode: UNRESOLVED root cause; ask FACT questions or hand off."""
    fact_candidates = [
        c
        for c in result.human_candidates
        if c.category == GateCategory.FACT.value
    ]
    created, code = _gate_from_candidates(o, fact_candidates)
    if code is not None:
        return code
    if created:
        return None  # gate created; the loop will ask it
    missing = "; ".join(result.missing_evidence) or "root cause could not be supported"
    o.handoff(
        "root cause UNRESOLVED, missing facts materially affect fix direction: " + missing
    )
    return int(ExitCode.HUMAN_HANDOFF)


def try_gate_for_need_human_issues(
    o, issue_ids, allow_revision: bool = True, continue_routing: bool = True
) -> ExitCode | None:
    """V0.2: NEED_HUMAN issues go through the Human Authority Check.

    Returns an exit code for terminal outcomes. ``None`` means the
    routing resolved: either a Convergence Gate was opened (phase moved
    to WAITING_FOR_HUMAN) or every issue was proven covered by ACTIVE
    decisions and the normal solution-correction routing continues
    (``continue_routing=False`` returns to the calling phase's body,
    which owns the now-OPEN blockers itself).
    """
    return resolve_need_human_issues(
        o, issue_ids, allow_revision=allow_revision, continue_routing=continue_routing
    )


# ---------------------------------------------------------------------------
# V0.2 Capability B: Human Authority Check + Convergence Gate
# ---------------------------------------------------------------------------


def _authority_input_issues(o, issue_ids: list[str]) -> list:
    log = o.store.load_issues()
    by_id = {i.id: i for i in log.issues}
    return [by_id[i] for i in issue_ids if i in by_id]


def _active_decisions(o) -> list[Decision]:
    return [
        d
        for d in o.store.load_decisions().decisions
        if d.status == DecisionStatus.ACTIVE
    ]


def _validate_candidate_packet(
    o,
    candidate: DecisionCandidate,
    decided_keys: set[str],
    outcome_issue_id: str,
    batch_issue_ids: list[str],
) -> str | None:
    """Mechanical validation of a decision candidate packet (V0.2-RC2 B203).

    Returns an error string when the packet must be rejected (fail
    closed BEFORE gate creation, budget consumption or issue mutation);
    None when it is gate-ready. Same structural rules as a normal Human
    Gate candidate (spec V0.2 5.4) plus the RC2 identity/provenance
    hardening: exact source-issue provenance, decision-semantic
    category, unique option keys and a unique decision identity.
    """
    if candidate.category not in DECISION_CATEGORIES:
        return (
            f"decision candidate category {candidate.category!r} is not a "
            "Human decision semantic category "
            "(REQUIREMENT/FACT/TRADE_OFF/SCOPE); CONVERGENCE is a gate "
            "routing category and can never be a decision semantic"
        )
    if not candidate.question.strip():
        return "decision candidate question is empty"
    if not (2 <= len(candidate.options) <= 4):
        return (
            f"decision candidate for issue(s) {candidate.source_issue_ids or [outcome_issue_id]} "
            f"requires 2-4 options, got {len(candidate.options)}"
        )
    reserved = normalized_custom_selector_aliases()
    seen_keys: set[str] = set()
    for option in candidate.options:
        if not option.key.strip() or not option.label.strip():
            return "decision candidate options require non-empty key and label"
        if _norm(option.key) in reserved:
            return (
                f"option key {option.key!r} collides with the reserved "
                "custom-decision selector"
            )
        normalized = _norm(option.key)
        if normalized in seen_keys:
            # B203.2: options indistinguishable by answer matching could
            # persist a Human selection with another option's label.
            return (
                f"decision candidate for issue(s) "
                f"{candidate.source_issue_ids or [outcome_issue_id]} has "
                f"duplicate option keys after normalization: {option.key!r}"
            )
        seen_keys.add(normalized)
    # B301 (V0.2-RC3): the complete Human Answer Alias Space must be
    # unambiguous — labels, composite key+label forms, numeric/选项N
    # aliases and the reserved protocol-control commands share one
    # namespace with option keys. Same shared helper as GateQuestion
    # validation and runtime matching.
    alias_violation = option_alias_violation(candidate.options)
    if alias_violation is not None:
        return (
            f"decision candidate for issue(s) "
            f"{candidate.source_issue_ids or [outcome_issue_id]}: "
            f"{alias_violation}"
        )
    if candidate.recommendation is not None:
        keys = {option.key for option in candidate.options}
        if candidate.recommendation not in keys:
            return (
                f"decision candidate recommendation {candidate.recommendation!r} "
                "is not an option key"
            )
    key = candidate_decision_key(candidate.category, candidate.question)
    if key in decided_keys:
        return (
            f"decision candidate key {key} is already decided ACTIVE; the "
            "authority outcome contradicts itself (should have been COVERED)"
        )
    # B203.1: provenance must be exact. The candidate must carry the
    # outcome's own issue and may only reference issues from the current
    # authority-check batch — unknown ids are never silently filtered
    # (filtering could turn an invalid convergence packet into a normal
    # gate and lose the Convergence provenance entirely).
    if not candidate.source_issue_ids:
        return "decision candidate requires source_issue_ids"
    if outcome_issue_id not in candidate.source_issue_ids:
        return (
            f"decision candidate source_issue_ids {candidate.source_issue_ids} "
            f"do not include the outcome issue {outcome_issue_id}"
        )
    unknown = [i for i in candidate.source_issue_ids if i not in batch_issue_ids]
    if unknown:
        return (
            f"decision candidate references source issue id(s) {unknown} "
            f"outside the current authority-check batch {batch_issue_ids}"
        )
    return None


def _run_authority_check(o, issue_ids: list[str]) -> HumanAuthorityCheckResult | None:
    """Ask Pi to classify coverage and derive a candidate packet.

    Returns None when no safe agent judgment is available (adapter
    lacks the method, or no matching issues remain): the caller fails
    closed. Adapter tooling/protocol failures propagate as FAILED —
    only a valid CANNOT_DETERMINE result is a task-level handoff.
    """
    issues = _authority_input_issues(o, issue_ids)
    if not issues:
        return None
    checker = getattr(o.pi, "human_authority_check", None)
    if checker is None:
        return None
    decisions = _active_decisions(o)
    contract = o.store.load_contract()
    o.event(
        "ISSUE_HUMAN_AUTHORITY_CHECK_STARTED",
        issue_ids=[i.id for i in issues],
        active_decision_ids=[d.decision_id for d in decisions],
    )
    # Tooling/protocol failures propagate and fail the session (FAILED)
    # — only a *valid* CANNOT_DETERMINE result is a task-level handoff.
    result = o.agent_call(
        "pi",
        "human_authority_check",
        lambda: checker(o.state, issues, decisions, contract),
    )
    return HumanAuthorityCheckResult.model_validate(
        result.model_dump() if hasattr(result, "model_dump") else result
    )


def resolve_need_human_issues(
    o, issue_ids: list[str], allow_revision: bool = True, continue_routing: bool = True
) -> ExitCode | None:
    """Human Authority Check routing (V0.2 spec 5).

    COVERED_BY_ACTIVE_DECISION -> issue reverts to OPEN as a solution
    coverage gap (provenance preserved) and normal correction routing
    continues. NEEDS_NEW_HUMAN_DECISION -> Convergence Gate within the
    interruption budget. Anything undeterminable or invalid fails
    closed to HUMAN_HANDOFF with a structured handoff package.
    """
    result = _run_authority_check(o, issue_ids)
    if result is None:
        o.handoff(
            "human authority check unavailable; cannot determine coverage "
            "or derive a decision packet for issues: " + ", ".join(issue_ids)
        )
        return int(ExitCode.HUMAN_HANDOFF)

    # Mechanical validation BEFORE mutating anything: the mapping must
    # cover exactly the flipped issues, every outcome must be complete,
    # and every COVERED reference must be an existing ACTIVE decision.
    by_issue: dict[str, object] = {}
    for outcome in result.outcomes:
        if outcome.issue_id not in issue_ids:
            o.handoff(
                "human authority check returned an outcome for an unknown "
                f"issue {outcome.issue_id!r}; failing closed for: "
                + ", ".join(issue_ids)
            )
            return int(ExitCode.HUMAN_HANDOFF)
        if outcome.issue_id in by_issue:
            o.handoff(
                "human authority check returned duplicate outcomes for "
                f"{outcome.issue_id}; failing closed for: " + ", ".join(issue_ids)
            )
            return int(ExitCode.HUMAN_HANDOFF)
        by_issue[outcome.issue_id] = outcome
    missing = [i for i in issue_ids if i not in by_issue]
    if missing:
        o.handoff(
            "human authority check did not classify issues: "
            + ", ".join(missing)
        )
        return int(ExitCode.HUMAN_HANDOFF)

    decisions_by_id = {d.decision_id: d for d in _active_decisions(o)}
    decided_keys = {
        d.decision_key for d in _active_decisions(o)
    }

    covered: list[tuple[object, list[str], str]] = []
    candidates: list[tuple[object, DecisionCandidate]] = []
    candidate_keys: dict[str, str] = {}  # decision_key -> issue_id (B203.3)
    for issue_id in issue_ids:
        outcome = by_issue[issue_id]
        if outcome.outcome == AuthorityOutcome.COVERED_BY_ACTIVE_DECISION:
            bad = [
                d for d in outcome.referenced_decision_ids if d not in decisions_by_id
            ]
            if bad:
                o.handoff(
                    f"coverage claim for {issue_id} references non-ACTIVE or "
                    f"nonexistent decisions {bad}; failing closed"
                )
                return int(ExitCode.HUMAN_HANDOFF)
            covered.append((outcome, outcome.referenced_decision_ids, outcome.rationale))
        elif outcome.outcome == AuthorityOutcome.NEEDS_NEW_HUMAN_DECISION:
            candidate = outcome.decision_candidate
            error = _validate_candidate_packet(
                o, candidate, decided_keys, issue_id, list(issue_ids)
            )
            if error is not None:
                o.handoff(
                    f"invalid decision candidate for {issue_id}: {error}; "
                    "failing closed"
                )
                return int(ExitCode.HUMAN_HANDOFF)
            key = candidate_decision_key(candidate.category, candidate.question)
            if key in candidate_keys:
                # B203.3: gate answer tracking is keyed by decision_key;
                # two questions collapsing onto one identity could make
                # one answer satisfy both and corrupt supersession
                # semantics. Fail closed before any mutation.
                o.handoff(
                    f"human authority check produced duplicate decision_key "
                    f"{key} for issues {candidate_keys[key]} and {issue_id}; "
                    "distinct Human questions must not collapse into one "
                    "decision identity; failing closed"
                )
                return int(ExitCode.HUMAN_HANDOFF)
            candidate_keys[key] = issue_id
            candidates.append((outcome, candidate))
        else:  # CANNOT_DETERMINE
            o.handoff(
                "human authority could not be determined for issue(s): "
                + ", ".join(issue_ids)
                + (
                    f" ({outcome.rationale.strip()})"
                    if outcome.rationale.strip()
                    else ""
                )
            )
            return int(ExitCode.HUMAN_HANDOFF)

    # All outcomes validated — now apply the routing.
    if covered:
        log = o.store.load_issues()
        for outcome, decision_ids, rationale in covered:
            for issue in log.issues:
                if issue.id == outcome.issue_id:
                    # Solution coverage gap, not missing Human semantics:
                    # back to OPEN for the normal correction path. The
                    # original reviewer category/provenance stays intact;
                    # the durable covered_by_decisions marker keeps later
                    # phase-entry re-checks from re-flipping the issue,
                    # and the routing note records the finding.
                    issue.status = IssueStatus.OPEN
                    issue.covered_by_decisions = list(decision_ids)
                    issue.resolution = (
                        "human authority check: semantics already decided by "
                        + ", ".join(decision_ids)
                        + " — routed as a solution coverage gap"
                    )
                    o.event(
                        "ISSUE_COVERED_BY_DECISION",
                        issue_id=issue.id,
                        decision_ids=decision_ids,
                    )
                    break
        o.store.save_issues(log)

    if not candidates:
        # Pure coverage: continue the normal solution-correction ladder.
        if not continue_routing:
            # Called from a phase that already owns correction (REVISION /
            # ABLATION entry re-check); the caller proceeds with the
            # reverted OPEN blockers itself.
            return None
        from agent_review.phases.review import continue_blocker_routing

        return continue_blocker_routing(o, allow_revision=allow_revision)

    # New Human-owned decisions discovered: open a Convergence Gate.
    questions: list[GateQuestion] = []
    gate_source_issues: list[str] = []
    for _outcome, candidate in candidates:
        questions.append(
            GateQuestion(
                decision_key=candidate_decision_key(candidate.category, candidate.question),
                category=candidate.category,
                question=candidate.question,
                why_human=candidate.why_human,
                # N301: options already validated to exactly 2-4 — no
                # slicing that could hide invalid cardinality.
                options=[
                    GateOption(key=op.key, label=op.label, impact=op.impact)
                    for op in candidate.options
                ],
                recommendation=candidate.recommendation,
            )
        )
        # Exact provenance (B203.1): validation already guaranteed every
        # source id belongs to this authority-check batch, so the union
        # is taken verbatim — never silently filtered.
        for source_id in candidate.source_issue_ids:
            if source_id not in gate_source_issues:
                gate_source_issues.append(source_id)
    remaining: list[str] = []
    if len(questions) > MAX_QUESTIONS_PER_GATE:
        remaining = [q.decision_key for q in questions[MAX_QUESTIONS_PER_GATE:]]
        questions = questions[:MAX_QUESTIONS_PER_GATE]
        o.event(
            "REQUIREMENT_TOO_AMBIGUOUS",
            asked=[q.decision_key for q in questions],
            deferred=remaining,
        )
    gate = create_gate(
        o,
        questions,
        remaining_keys=remaining,
        source_issue_ids=gate_source_issues,
        resume_semantics=compute_resume_semantics(questions),
    )
    if gate is None:
        # Budget exhausted: create_gate already generated the handoff
        # package with the pending questions.
        return int(ExitCode.HUMAN_HANDOFF)
    return None


# ---------------------------------------------------------------------------
# WAITING_FOR_HUMAN execution
# ---------------------------------------------------------------------------


def _print_question(o, question: GateQuestion) -> None:
    o.ui.echo("")
    o.ui.echo(f"[{question.category}] {question.decision_key}: {question.question}")
    if question.why_human:
        o.ui.echo(f"  why human: {question.why_human}")
    for index, option in enumerate(question.options, 1):
        marker = " (recommended)" if question.recommendation == option.key else ""
        o.ui.echo(f"  {index}. [{option.key}] {option.label}{marker}")
        if option.impact:
            o.ui.echo(f"     impact: {option.impact}")
    o.ui.echo("  0. [custom] none of the above — I will define the decision")


def _ask_pass(o, gate: HumanGate) -> list[GateAnswer]:
    """One pass over unresolved questions; returns the new answers."""
    new_answers: list[GateAnswer] = []
    for question in list(gate.unresolved_questions()):
        if question.decision_key in gate.answered_keys():
            continue  # answered by a global shortcut within this pass
        _print_question(o, question)
        raw = o.ui.ask(
            "Your answer (number/key/label, 0=custom, '都按推荐', empty to skip): "
        )
        if not raw.strip():
            # Empty input = leave unresolved (skip). A skip is not an
            # attempt: recording it would make it the latest effective
            # answer and degrade earlier question-like attempts.
            o.ui.echo(f"  {question.decision_key} left unresolved")
            continue
        if is_global_recommend(raw):
            # Global shortcut applies to every unresolved question that has
            # a recommendation; questions without one stay unresolved.
            answered_any = False
            for unresolved in gate.unresolved_questions():
                if unresolved.recommendation:
                    answer = normalize_answer(unresolved, raw)
                    if answer.matched:
                        gate.answers.append(answer)
                        new_answers.append(answer)
                        answered_any = True
                else:
                    o.ui.echo(
                        f"  note: {unresolved.decision_key} has no recommended "
                        "option and needs an explicit answer"
                    )
            if answered_any:
                continue
            continue
        if is_custom_request(raw):
            # Explicit custom-decision mode (V0.2 Capability A): only here
            # may free text become an authoritative Human Decision.
            custom_text = o.ui.ask(CUSTOM_DECISION_PROMPT).strip()
            if not custom_text:
                o.ui.echo(
                    "  empty custom decision; the question stays unresolved"
                )
                continue
            answer = GateAnswer(
                decision_key=question.decision_key,
                raw=raw,
                answer_type=AnswerType.CUSTOM,
                custom_text=custom_text,
                matched=True,
            )
            gate.answers.append(answer)
            new_answers.append(answer)
            o.ui.echo("  recorded as your authoritative decision")
            continue
        answer = normalize_answer(question, raw)
        gate.answers.append(answer)
        new_answers.append(answer)
        if not answer.matched:
            o.ui.echo(
                f"  could not map '{raw.strip()}' to an option for "
                f"{question.decision_key}; it stays unresolved "
                "(use 0/custom to define your own decision)"
            )
    return new_answers


def run(o) -> ExitCode | None:
    gate_log = o.store.load_gate_log()
    gate = gate_log.current
    if gate is None or gate.status not in (GateStatus.OPEN,):
        o.fail("WAITING_FOR_HUMAN without an open gate")
        return int(ExitCode.FAILED)

    if not o.ui.is_interactive():
        # Packet already persisted; resume later with answers.
        o.event("HUMAN_GATE_WAITING_NONINTERACTIVE", gate_id=gate.gate_id)
        return int(ExitCode.WAITING_FOR_HUMAN)

    o.event("HUMAN_GATE_ASKING", gate_id=gate.gate_id)
    for _pass in range(MAX_ANSWER_PASSES):
        if not gate.unresolved_questions():
            break
        try:
            _ask_pass(o, gate)
        except EOFError:
            # Interactive stream closed (e.g. piped stdin ran out): the
            # gate stays open with partial answers; resume later.
            o.store.save_gate_log(gate_log)
            o.ui.echo(
                "input closed; the gate stays open. Re-run 'review resume' "
                "to answer the remaining decisions."
            )
            return int(ExitCode.WAITING_FOR_HUMAN)
        o.store.save_gate_log(gate_log)
        # Human answers are a durable boundary even if applying decisions
        # crashes later. Resume can apply them without asking again.
        o.store.begin_phase()
        validation = validate_answers(gate.answers)
        o.event("HUMAN_GATE_ANSWERS_VALIDATED", result=validation.value)

    if gate.unresolved_questions():
        # PARTIAL/AMBIGUOUS: keep the same gate open, persist progress,
        # and wait for a future resume.
        o.store.save_gate_log(gate_log)
        o.ui.echo(
            "Unresolved decisions remain; the gate stays open. "
            "Re-run 'review resume' to answer them."
        )
        return int(ExitCode.WAITING_FOR_HUMAN)

    # COMPLETE: apply decisions and invalidate the design basis.
    gate.status = GateStatus.ANSWERED
    from datetime import datetime, timezone

    gate.answered_at = datetime.now(timezone.utc)
    o.store.save_gate_log(gate_log)
    apply_gate_answers(o, gate)
    gate.status = GateStatus.CLOSED
    o.store.save_gate_log(gate_log)
    o.state.active_gate = None
    o.event("HUMAN_GATE_CLOSED", gate_id=gate.gate_id)

    invalidate_design_basis(o, f"human decisions applied from {gate.gate_id}")

    # Re-run intake: rebuilds the contract with confirmed decisions and
    # re-evaluates remaining candidates (REQUIREMENT_TOO_AMBIGUOUS path).
    # Problem Mode re-investigates with the new human facts.
    #
    # V0.2-RC2 (B202): the gate's CONVERGENCE provenance must not erase
    # WHAT was decided — a convergence gate whose effective Human
    # decision establishes FACT semantics re-enters INVESTIGATE so the
    # new authoritative fact is never combined with a stale root-cause
    # model. Normal gates keep using their own category.
    establishes_fact = (
        gate.category == GateCategory.FACT
        or gate.resume_semantics == GateCategory.FACT.value
    )
    if o.state.task_kind == TaskKind.PROBLEM and establishes_fact:
        o.transition(Phase.INVESTIGATE)
    else:
        o.transition(Phase.INTAKE)
    return None
