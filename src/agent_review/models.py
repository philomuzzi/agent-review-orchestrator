"""Pydantic v2 protocol models for the V0 orchestrator.

These models are the authoritative structured protocol between
orchestrator, agent adapters and persisted session state.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_answer_text(text: str) -> str:
    """Canonical normalization for answer/option-key matching (V0.2-RC2 B203.2).

    The SAME normalization is used for (a) matching a Human answer onto
    an option and (b) enforcing option-key uniqueness, so a set of
    options that cannot be distinguished by answer matching can never
    be persisted as a GateQuestion (a Human selection by index could
    otherwise be recorded with another option's label). Kept in models
    so the shared GateQuestion boundary inherits it without importing
    phase code.
    """
    text = text.strip().lower()
    text = re.sub(r"[\s\-_·、,，。;；:：]+", " ", text)
    return text.strip(" .?!!")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Phase(str, Enum):
    INIT = "INIT"
    DISCOVER = "DISCOVER"
    INVESTIGATE = "INVESTIGATE"
    INTAKE = "INTAKE"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    DESIGN = "DESIGN"
    INITIAL_REVIEW = "INITIAL_REVIEW"
    REVISION = "REVISION"
    CLOSURE_REVIEW = "CLOSURE_REVIEW"
    ABLATION = "ABLATION"
    FINAL_REVIEW = "FINAL_REVIEW"
    FINALIZE = "FINALIZE"
    DONE = "DONE"
    HUMAN_HANDOFF = "HUMAN_HANDOFF"
    INTERRUPTED = "INTERRUPTED"
    FAILED = "FAILED"


class SessionStatus(str, Enum):
    RUNNING = "RUNNING"
    DONE = "DONE"
    HUMAN_HANDOFF = "HUMAN_HANDOFF"
    INTERRUPTED = "INTERRUPTED"
    FAILED = "FAILED"


class TaskKind(str, Enum):
    CHANGE = "CHANGE"
    PROBLEM = "PROBLEM"


class IssueCategory(str, Enum):
    DESIGN = "DESIGN"
    REQUIREMENT = "REQUIREMENT"
    FACT = "FACT"
    REGRESSION = "REGRESSION"
    SUGGESTION = "SUGGESTION"


class IssueSeverity(str, Enum):
    BLOCKING = "BLOCKING"
    NON_BLOCKING = "NON_BLOCKING"


class IssueStatus(str, Enum):
    OPEN = "OPEN"
    ADDRESSED = "ADDRESSED"
    RESOLVED = "RESOLVED"
    NEED_HUMAN = "NEED_HUMAN"
    ACCEPTED_RISK = "ACCEPTED_RISK"
    SUPERSEDED = "SUPERSEDED"


class GateCategory(str, Enum):
    REQUIREMENT = "REQUIREMENT"
    FACT = "FACT"
    TRADE_OFF = "TRADE_OFF"
    SCOPE = "SCOPE"
    CONVERGENCE = "CONVERGENCE"


# Human decision semantic categories (V0.2-RC2 B203). CONVERGENCE is a
# Gate routing/provenance category — where a gate came from — and must
# never be used as the semantic category of a Human Decision itself.
DECISION_SEMANTIC_CATEGORIES = {
    GateCategory.REQUIREMENT.value,
    GateCategory.FACT.value,
    GateCategory.TRADE_OFF.value,
    GateCategory.SCOPE.value,
}

# Valid HumanGate.resume_semantics values (V0.2-RC2 B202). The resume
# semantic records WHAT KIND of Human decision a convergence gate
# establishes, separately from the CONVERGENCE provenance category.
# MIXED = mixed non-FACT semantics (any FACT question forces FACT so a
# Problem-Mode session always re-investigates with the new Human fact).
RESUME_SEMANTICS = {
    GateCategory.REQUIREMENT.value,
    GateCategory.FACT.value,
    GateCategory.TRADE_OFF.value,
    GateCategory.SCOPE.value,
    "MIXED",
}


class GateStatus(str, Enum):
    OPEN = "OPEN"
    ANSWERED = "ANSWERED"
    CLOSED = "CLOSED"
    SUPERSEDED = "SUPERSEDED"


class AnswerValidation(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    AMBIGUOUS = "AMBIGUOUS"
    QUESTION_ONLY = "QUESTION_ONLY"


class AnswerType(str, Enum):
    """How a Human answered one gate question (V0.2 Capability A).

    OPTION = the answer selected one of the Agent-proposed options;
    CUSTOM = the Human explicitly entered custom-decision mode and
    authored an authoritative decision of their own. Unmatched free
    text is NOT auto-promoted to CUSTOM — it stays an unresolved
    attempt until superseded by a later valid answer.
    """

    OPTION = "OPTION"
    CUSTOM = "CUSTOM"


class DecisionSource(str, Enum):
    OPTION = "OPTION"
    CUSTOM = "CUSTOM"


class AuthorityOutcome(str, Enum):
    """Result of the Human Authority Check on a blocking
    REQUIREMENT/FACT issue (V0.2 Capability B)."""

    COVERED_BY_ACTIVE_DECISION = "COVERED_BY_ACTIVE_DECISION"
    NEEDS_NEW_HUMAN_DECISION = "NEEDS_NEW_HUMAN_DECISION"
    CANNOT_DETERMINE = "CANNOT_DETERMINE"


class DecisionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class RootCauseStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNRESOLVED = "UNRESOLVED"


class ExitCode(int, Enum):
    DONE = 0
    HUMAN_HANDOFF = 10
    WAITING_FOR_HUMAN = 20
    FAILED = 30
    INTERRUPTED = 130


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


class BudgetLimits(BaseModel):
    max_revision_rounds: int = 1
    max_ablation_rounds: int = 1
    max_human_interruptions: int = 2
    max_protocol_retries: int = 1


class BudgetUsage(BaseModel):
    revision_used: int = 0
    ablation_used: int = 0
    human_interruptions_used: int = 0
    protocol_retries_used: int = 0


class SessionState(BaseModel):
    session_id: str
    repository: str
    request: str
    # V0.1 presentation metadata; never a routing/state-machine key.
    task_title: Optional[str] = None
    task_title_source: Optional[str] = None  # "user" | "discover"
    task_kind: TaskKind = TaskKind.CHANGE
    kind_explicit: bool = False
    phase: Phase = Phase.INIT
    status: SessionStatus = SessionStatus.RUNNING
    task_revision: int = 1
    active_gate: Optional[str] = None
    round: int = 0
    budgets: BudgetUsage = BudgetUsage()
    limits: BudgetLimits = BudgetLimits()
    resume_phase: Optional[Phase] = None
    error: Optional[str] = None
    handoff_reason: Optional[str] = None
    gate_seq: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Discovery / investigation
# ---------------------------------------------------------------------------


class GateOption(BaseModel):
    key: str
    label: str
    impact: str = ""


class HumanCandidate(BaseModel):
    category: str
    question: str
    why: str = ""
    options: list[GateOption] = Field(default_factory=list)
    recommendation: Optional[str] = None
    source: str = ""


class DiscoveryResult(BaseModel):
    # Concise semantic task title (V0.1 session presentation).
    task_title: str = ""
    task_kind: TaskKind = TaskKind.CHANGE
    current_state: str = ""
    relevant_components: list[str] = Field(default_factory=list)
    existing_constraints: list[str] = Field(default_factory=list)
    change_surface: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    human_candidates: list[HumanCandidate] = Field(default_factory=list)


class Evidence(BaseModel):
    description: str
    location: str = ""


class Hypothesis(BaseModel):
    statement: str
    status: str = "UNTESTED"
    supporting_evidence: list[str] = Field(default_factory=list)


class InvestigationResult(BaseModel):
    evidence: list[Evidence] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    root_cause: str = ""
    root_cause_status: RootCauseStatus = RootCauseStatus.UNRESOLVED
    causal_chain: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    human_candidates: list[HumanCandidate] = Field(default_factory=list)
    unresolved_contradictions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _supported_requires_evidence(self) -> "InvestigationResult":
        if self.root_cause_status == RootCauseStatus.SUPPORTED:
            if (not self.root_cause.strip()
                    or not self.evidence
                    or any(not e.description.strip() or not e.location.strip() for e in self.evidence)
                    or not self.causal_chain
                    or any(not link.strip() for link in self.causal_chain)
                    or self.unresolved_contradictions
                    or self.missing_evidence):
                raise ValueError("SUPPORTED requires a root cause, located evidence, causal chain, and no unresolved evidence or contradictions")
        return self


# ---------------------------------------------------------------------------
# Change contract (task.md)
# ---------------------------------------------------------------------------


class Assumption(BaseModel):
    value: str
    reason: str
    impact_if_wrong: str


class ChangeContract(BaseModel):
    user_intent: str
    current_behavior: str
    desired_behavior: str
    must_preserve: list[str] = Field(default_factory=list)
    scope: list[str] = Field(default_factory=list)
    known_constraints: list[str] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    confirmed_decisions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    root_cause: str = ""
    based_on_task_revision: int = 1

    @model_validator(mode="after")
    def _require_core_fields(self) -> "ChangeContract":
        for name in ("user_intent", "current_behavior", "desired_behavior"):
            if not getattr(self, name).strip():
                raise ValueError(f"ChangeContract requires non-empty {name}")
        return self


# ---------------------------------------------------------------------------
# Design / revision / ablation
# ---------------------------------------------------------------------------


class ChangeMap(BaseModel):
    affected_components: list[str] = Field(default_factory=list)
    data_changes: list[str] = Field(default_factory=list)
    api_changes: list[str] = Field(default_factory=list)
    config_changes: list[str] = Field(default_factory=list)
    behavior_changes: list[str] = Field(default_factory=list)
    unchanged_behaviors: list[str] = Field(default_factory=list)


class DesignResult(BaseModel):
    summary: str = ""
    current_flow: str = ""
    proposed_flow: str = ""
    changes: list[str] = Field(default_factory=list)
    data_model_changes: list[str] = Field(default_factory=list)
    interface_changes: list[str] = Field(default_factory=list)
    state_lifecycle_changes: list[str] = Field(default_factory=list)
    failure_handling: list[str] = Field(default_factory=list)
    compatibility: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    alternatives_considered: list[str] = Field(default_factory=list)
    verification_plan: list[str] = Field(default_factory=list)
    explicitly_unchanged: list[str] = Field(default_factory=list)
    change_map: ChangeMap = Field(default_factory=ChangeMap)
    based_on_task_revision: int = 1

    @model_validator(mode="after")
    def _require_summary_and_unchanged(self) -> "DesignResult":
        if not self.summary.strip():
            raise ValueError("DesignResult requires a non-empty summary")
        if not self.explicitly_unchanged:
            raise ValueError(
                "DesignResult requires a non-empty explicitly_unchanged section"
            )
        return self


class AddressedIssue(BaseModel):
    issue_id: str
    how_addressed: str


class RevisionResult(BaseModel):
    proposal: DesignResult
    addressed_issues: list[AddressedIssue] = Field(default_factory=list)
    notes: str = ""


class AblationResult(BaseModel):
    proposal: DesignResult
    removed: list[str] = Field(default_factory=list)
    rationale: str = ""
    addressed_issues: list[AddressedIssue] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Issues and reviews
# ---------------------------------------------------------------------------


class Issue(BaseModel):
    id: str = ""
    category: IssueCategory = IssueCategory.DESIGN
    severity: IssueSeverity = IssueSeverity.NON_BLOCKING
    status: IssueStatus = IssueStatus.OPEN
    title: str
    problem: str = ""
    evidence: list[str] = Field(default_factory=list)
    impact: str = ""
    acceptance: list[str] = Field(default_factory=list)
    introduced_round: int = 1
    provenance: str = "INITIAL_REVIEW"
    based_on_task_revision: int = 1
    addressed_by: Optional[str] = None
    resolution: Optional[str] = None
    why_not_detected_initially: Optional[str] = None
    # Orchestrator-owned routing metadata (V0.2): ACTIVE decision ids a
    # Human Authority Check proved to cover this issue's semantics.
    # Persisted with the issue so later phase-entry re-checks do not
    # re-flip it NEED_HUMAN; reset on ingest so the reviewer can never
    # forge coverage.
    covered_by_decisions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _blocking_requires_acceptance(self) -> "Issue":
        if self.severity == IssueSeverity.BLOCKING and not self.acceptance:
            raise ValueError(
                f"BLOCKING issue '{self.title}' requires explicit acceptance criteria"
            )
        return self


class InitialReviewResult(BaseModel):
    issues: list[Issue] = Field(default_factory=list)
    summary: str = ""


class IssueOutcome(BaseModel):
    issue_id: str
    resolution: str  # RESOLVED | UNRESOLVED
    note: str = ""


class ClosureReviewResult(BaseModel):
    issue_outcomes: list[IssueOutcome] = Field(default_factory=list)
    new_issues: list[Issue] = Field(default_factory=list)
    summary: str = ""


class FinalReviewResult(BaseModel):
    satisfies_requirement: bool = False
    unresolved_issue_ids: list[str] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    summary: str = ""


class PassResult(BaseModel):
    passed: bool
    open_blocking: list[str] = Field(default_factory=list)
    addressed_blocking: list[str] = Field(default_factory=list)
    need_human: list[str] = Field(default_factory=list)
    active_gate: bool = False
    stale: bool = False
    reasons: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Human gate and decisions
# ---------------------------------------------------------------------------


class GateQuestion(BaseModel):
    decision_key: str
    category: str = ""
    question: str
    why_human: str = ""
    options: list[GateOption] = Field(default_factory=list)
    recommendation: Optional[str] = None

    @model_validator(mode="after")
    def _two_to_four_options(self) -> "GateQuestion":
        if not (2 <= len(self.options) <= 4):
            raise ValueError(
                f"GateQuestion '{self.decision_key}' requires 2-4 options, "
                f"got {len(self.options)}"
            )
        # Uniqueness BEFORE recommendation membership (V0.2-RC2 B203.2):
        # duplicate keys — exact or after the answer-matching
        # normalization — could persist a Human selection with another
        # option's label. Fail closed; never auto-rename agent keys.
        seen: set[str] = set()
        for option in self.options:
            normalized = normalize_answer_text(option.key)
            if normalized in seen:
                raise ValueError(
                    f"GateQuestion '{self.decision_key}' has duplicate option "
                    f"keys after normalization: {option.key!r}"
                )
            seen.add(normalized)
        if self.recommendation is not None:
            keys = {o.key for o in self.options}
            if self.recommendation not in keys:
                raise ValueError(
                    f"GateQuestion '{self.decision_key}' recommendation "
                    f"'{self.recommendation}' is not an option key"
                )
        return self


class GateAnswer(BaseModel):
    decision_key: str
    raw: str
    answer_type: AnswerType = AnswerType.OPTION
    option_key: Optional[str] = None
    custom_text: Optional[str] = None
    matched: bool = False

    @model_validator(mode="after")
    def _valid_answer_shape(self) -> "GateAnswer":
        """A valid answer satisfies exactly one of (spec V0.2 4.2):
        OPTION -> option_key is present; CUSTOM -> custom_text non-empty."""
        if self.answer_type == AnswerType.CUSTOM:
            if self.matched and not (self.custom_text or "").strip():
                raise ValueError(
                    f"CUSTOM answer for {self.decision_key} requires non-empty "
                    "custom_text"
                )
        elif self.matched and not self.option_key:
            raise ValueError(
                f"OPTION answer for {self.decision_key} requires option_key"
            )
        return self


class HumanGate(BaseModel):
    gate_id: str
    category: GateCategory
    created_in_phase: str
    questions: list[GateQuestion]
    status: GateStatus = GateStatus.OPEN
    answers: list[GateAnswer] = Field(default_factory=list)
    remaining_candidate_keys: list[str] = Field(default_factory=list)
    # Convergence provenance (V0.2): review issue ids this gate was
    # derived from. Empty for normal intake/fact gates.
    source_issue_ids: list[str] = Field(default_factory=list)
    # V0.2-RC2 (B202): what KIND of Human decision this gate establishes
    # (REQUIREMENT/FACT/TRADE_OFF/SCOPE, or MIXED for mixed non-FACT
    # packets). ``category`` stays CONVERGENCE for provenance; the resume
    # semantic — derived deterministically from the validated candidate
    # categories at creation — decides the resume phase, so a Problem-Mode
    # FACT convergence decision re-enters INVESTIGATE instead of pairing
    # a new Human fact with a stale root-cause model. Empty for normal
    # gates (their own category carries the semantics).
    resume_semantics: str = ""
    answered_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _resume_semantics_shape(self) -> "HumanGate":
        if self.resume_semantics and self.resume_semantics not in RESUME_SEMANTICS:
            raise ValueError(
                f"HumanGate '{self.gate_id}' resume_semantics must be one of "
                f"{sorted(RESUME_SEMANTICS)}, got {self.resume_semantics!r}"
            )
        return self

    def effective_answers(self) -> list[GateAnswer]:
        """Latest answer per decision_key (V0.2 Capability D).

        Validation and decision application operate on the latest
        effective answer per key; historical failed attempts remain in
        the audit trail but never poison the effective view.
        """
        latest: dict[str, GateAnswer] = {}
        for answer in self.answers:
            latest[answer.decision_key] = answer
        return list(latest.values())

    def answered_keys(self) -> set[str]:
        return {
            a.decision_key
            for a in self.effective_answers()
            if a.matched
        }

    def unresolved_questions(self) -> list[GateQuestion]:
        answered = self.answered_keys()
        return [q for q in self.questions if q.decision_key not in answered]


class Decision(BaseModel):
    decision_id: str
    decision_key: str
    gate_id: str
    question: str
    selected_option_key: Optional[str] = None
    answer_text: str = ""
    source: DecisionSource = DecisionSource.OPTION
    status: DecisionStatus = DecisionStatus.ACTIVE
    superseded_by: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Persisted collection wrappers
# ---------------------------------------------------------------------------


class IssueLog(BaseModel):
    issues: list[Issue] = Field(default_factory=list)
    next_issue_number: int = 1


# ---------------------------------------------------------------------------
# V0.2 Capability B: Human Authority Check (review-discovered decisions)
# ---------------------------------------------------------------------------


class DecisionCandidate(BaseModel):
    """Gate-ready Human Decision Candidate derived from review issues.

    Structurally the same packet as a normal Human Gate candidate so
    the orchestrator can validate it with identical rules.
    """

    category: str
    question: str
    why_human: str = ""
    options: list[GateOption] = Field(default_factory=list)
    recommendation: Optional[str] = None
    source_issue_ids: list[str] = Field(default_factory=list)


class IssueAuthorityOutcome(BaseModel):
    issue_id: str
    outcome: AuthorityOutcome
    referenced_decision_ids: list[str] = Field(default_factory=list)
    rationale: str = ""
    decision_candidate: Optional[DecisionCandidate] = None

    @model_validator(mode="after")
    def _outcome_shape(self) -> "IssueAuthorityOutcome":
        if self.outcome == AuthorityOutcome.COVERED_BY_ACTIVE_DECISION:
            if not self.referenced_decision_ids:
                raise ValueError(
                    f"COVERED_BY_ACTIVE_DECISION for {self.issue_id} requires "
                    "referenced_decision_ids"
                )
            if not self.rationale.strip():
                raise ValueError(
                    f"COVERED_BY_ACTIVE_DECISION for {self.issue_id} requires "
                    "a rationale explaining the coverage"
                )
        if self.outcome == AuthorityOutcome.NEEDS_NEW_HUMAN_DECISION:
            if self.decision_candidate is None:
                raise ValueError(
                    f"NEEDS_NEW_HUMAN_DECISION for {self.issue_id} requires "
                    "a decision_candidate packet"
                )
        return self


class HumanAuthorityCheckResult(BaseModel):
    outcomes: list[IssueAuthorityOutcome] = Field(default_factory=list)


class DecisionLog(BaseModel):
    decisions: list[Decision] = Field(default_factory=list)
    next_decision_number: int = 1


class GateLog(BaseModel):
    current: Optional[HumanGate] = None
    gates: list[HumanGate] = Field(default_factory=list)
    next_gate_number: int = 1
