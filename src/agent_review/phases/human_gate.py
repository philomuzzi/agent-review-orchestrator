"""Human Gate protocol.

Agents emit candidates; only the Orchestrator may pause the workflow.
This module owns:

- candidate aggregation, category filtering and suppression;
- decision packets (max 3 blocking decisions) persisted as
  human-gate.json / human-gate.md;
- interactive answering with natural-language normalization;
- COMPLETE / PARTIAL / AMBIGUOUS / QUESTION_ONLY validation;
- append-only decisions with SUPERSEDED semantics;
- task-revision invalidation of stale designs;
- the Human Interruption Budget.
"""

from __future__ import annotations

import hashlib
import re

from agent_review.models import (
    AnswerValidation,
    Decision,
    DecisionStatus,
    ExitCode,
    GateAnswer,
    GateCategory,
    GateOption,
    GateQuestion,
    GateStatus,
    HumanCandidate,
    HumanGate,
    IssueStatus,
    Phase,
    SessionStatus,
)
from agent_review.rendering import render_gate

ALLOWED_CATEGORIES = {c.value for c in GateCategory}
MAX_QUESTIONS_PER_GATE = 3
MAX_ANSWER_PASSES = 2  # bounded re-ask rounds before waiting again

GLOBAL_RECOMMEND_ANSWERS = {"都按推荐", "按推荐", "全部按推荐", "all recommended"}


# ---------------------------------------------------------------------------
# Candidate filtering
# ---------------------------------------------------------------------------


def candidate_decision_key(candidate: HumanCandidate) -> str:
    """Stable decision key derived from the question itself."""
    digest = hashlib.sha1(
        f"{candidate.category}|{candidate.question}".encode("utf-8")
    ).hexdigest()[:8]
    prefix = (candidate.category or "DEC")[:4].upper().replace("_", "")
    return f"{prefix}-{digest}"


def eligible_candidates(
    o, candidates: list[HumanCandidate]
) -> tuple[list[HumanCandidate], list[HumanCandidate]]:
    """Filter candidates to gate-worthy questions.

    Returns (eligible, suppressed). Suppression rules (spec 14):
    categories outside the allowed set (naming/taste/extensibility are not
    categories at all), and questions without 2+ meaningful options.
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
    for candidate in candidates:
        key = candidate_decision_key(candidate)
        if candidate.category not in ALLOWED_CATEGORIES:
            suppressed.append(candidate)
            o.event(
                "HUMAN_CANDIDATE_SUPPRESSED",
                decision_key=key,
                reason=f"category not gate-worthy: {candidate.category}",
            )
        elif len(candidate.options) < 2:
            suppressed.append(candidate)
            o.event(
                "HUMAN_CANDIDATE_SUPPRESSED",
                decision_key=key,
                reason="fewer than 2 meaningful options",
            )
        elif key in decided:
            # Human answer is session fact; never re-ask unless superseded.
            continue
        else:
            eligible.append(candidate)
    return eligible, suppressed


def _to_question(candidate: HumanCandidate) -> GateQuestion:
    options = [
        GateOption(key=o.key, label=o.label, impact=o.impact)
        for o in candidate.options[:4]
    ]
    return GateQuestion(
        decision_key=candidate_decision_key(candidate),
        category=candidate.category,
        question=candidate.question,
        why_human=candidate.why,
        options=options,
        recommendation=candidate.recommendation,
    )


# ---------------------------------------------------------------------------
# Gate creation
# ---------------------------------------------------------------------------


def create_gate(
    o,
    questions: list[GateQuestion],
    remaining_keys: list[str] | None = None,
) -> HumanGate | None:
    """Create the decision packet; None means the interruption budget said no."""
    if o.state.budgets.human_interruptions_used >= o.state.limits.max_human_interruptions:
        o.handoff(
            "Human interruption budget exhausted "
            f"({o.state.budgets.human_interruptions_used}/"
            f"{o.state.limits.max_human_interruptions}); unresolved decisions: "
            + ", ".join(q.decision_key for q in questions)
        )
        return None

    log = o.store.load_gate_log()
    gate = HumanGate(
        gate_id=f"HG{log.next_gate_number:03d}",
        category=GateCategory(questions[0].category) if questions else GateCategory.REQUIREMENT,
        created_in_phase=o.state.phase.value,
        questions=questions[:MAX_QUESTIONS_PER_GATE],
        remaining_candidate_keys=remaining_keys or [],
    )
    log.next_gate_number += 1
    log.current = gate
    log.gates.append(gate)
    o.store.save_gate_log(log)
    o.store.write_text("human-gate.md", render_gate(gate))
    o.state.active_gate = gate.gate_id
    o.state.budgets.human_interruptions_used += 1
    o.event(
        "HUMAN_GATE_CREATED",
        gate_id=gate.gate_id,
        questions=[q.decision_key for q in gate.questions],
    )
    o.transition(Phase.WAITING_FOR_HUMAN, status=SessionStatus.RUNNING)
    return gate


# ---------------------------------------------------------------------------
# Answer normalization
# ---------------------------------------------------------------------------


def _norm(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[\s\-_·、,，。;；:：]+", " ", text)
    return text.strip(" .?!!")


def match_option(question: GateQuestion, raw: str) -> GateOption | None:
    """Normalize a natural-language answer onto one option, or None."""
    normalized = _norm(raw)
    if not normalized:
        return None
    for index, option in enumerate(question.options, 1):
        keys = {
            _norm(option.key),
            _norm(option.label),
            _norm(f"{option.key} {option.label}"),
            str(index),
            _norm(f"选项{index}"),
            _norm(f"option {index}"),
        }
        if normalized in keys:
            return option
    return None


def is_global_recommend(raw: str) -> bool:
    return _norm(raw) in {_norm(a) for a in GLOBAL_RECOMMEND_ANSWERS}


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


def validate_answers(answers: list[GateAnswer]) -> AnswerValidation:
    """Batch validation of gate answers (spec 14)."""
    if not answers:
        return AnswerValidation.AMBIGUOUS
    matched = [a for a in answers if a.matched]
    if len(matched) == len(answers):
        return AnswerValidation.COMPLETE
    if matched:
        return AnswerValidation.PARTIAL
    question_only = all(a.raw.strip().endswith("?") or a.raw.strip().endswith("？") for a in answers)
    return AnswerValidation.QUESTION_ONLY if question_only else AnswerValidation.AMBIGUOUS


# ---------------------------------------------------------------------------
# Decision application
# ---------------------------------------------------------------------------


def apply_gate_answers(o, gate: HumanGate) -> list[Decision]:
    """Append decisions for matched answers; supersede prior ACTIVE ones."""
    log = o.store.load_decisions()
    questions = {q.decision_key: q for q in gate.questions}
    applied: list[Decision] = []
    for answer in gate.answers:
        if not answer.matched:
            continue
        question = questions.get(answer.decision_key)
        if question is None:
            continue
        decision_id = f"D{log.next_decision_number:03d}"
        log.next_decision_number += 1
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
            answer_text=option_label or answer.raw,
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
        o.event(
            "DECISION_APPLIED",
            decision_id=decision_id,
            decision_key=question.decision_key,
            option=answer.option_key,
        )
    o.store.save_decisions(log)
    return applied


def invalidate_design_basis(o, reason: str) -> None:
    """task_revision += 1; old proposal -> history/STALE; open issues stale."""
    if o.store.load_proposal() is not None:
        archived = o.store.archive_proposal(reason)
        if archived is not None:
            o.event("PROPOSAL_STALE", archived=str(archived), reason=reason)
    log = o.store.load_issues()
    for issue in log.issues:
        if issue.status in (IssueStatus.OPEN, IssueStatus.ADDRESSED, IssueStatus.NEED_HUMAN):
            issue.status = IssueStatus.SUPERSEDED
            o.event("ISSUE_SUPERSEDED", issue_id=issue.id, reason="task revision changed")
    o.store.save_issues(log)
    o.state.task_revision += 1
    o.event("TASK_REVISION_INCREMENTED", task_revision=o.state.task_revision, reason=reason)


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


def try_gate_for_need_human_issues(o, issue_ids) -> ExitCode | None:
    """NEED_HUMAN issues carry no decision options; V0 hands off."""
    o.handoff(
        "issues requiring human authority (no decision packet derivable): "
        + ", ".join(issue_ids)
    )
    return int(ExitCode.HUMAN_HANDOFF)


# ---------------------------------------------------------------------------
# WAITING_FOR_HUMAN execution
# ---------------------------------------------------------------------------


def _ask_pass(o, gate: HumanGate) -> list[GateAnswer]:
    """One pass over unresolved questions; returns the new answers."""
    new_answers: list[GateAnswer] = []
    for question in list(gate.unresolved_questions()):
        if question.decision_key in gate.answered_keys():
            continue  # answered by a global shortcut within this pass
        o.ui.echo("")
        o.ui.echo(f"[{question.category}] {question.decision_key}: {question.question}")
        if question.why_human:
            o.ui.echo(f"  why human: {question.why_human}")
        for index, option in enumerate(question.options, 1):
            marker = " (recommended)" if question.recommendation == option.key else ""
            o.ui.echo(f"  {index}. [{option.key}] {option.label}{marker}")
            if option.impact:
                o.ui.echo(f"     impact: {option.impact}")
        raw = o.ui.ask("Your answer (number/key/label, '都按推荐', empty to skip): ")
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
        answer = normalize_answer(question, raw)
        gate.answers.append(answer)
        new_answers.append(answer)
        if not answer.matched:
            o.ui.echo(
                f"  could not map '{raw.strip()}' to an option for "
                f"{question.decision_key}; it stays unresolved"
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
    if o.state.task_kind == "PROBLEM" and gate.category == GateCategory.FACT:
        o.transition(Phase.INVESTIGATE)
    else:
        o.transition(Phase.INTAKE)
    return None
