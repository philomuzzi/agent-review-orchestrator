"""Pydantic v2 protocol models for the V0 orchestrator.

These models are the authoritative structured protocol between
orchestrator, agent adapters and persisted session state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
    option_key: Optional[str] = None
    matched: bool = False


class HumanGate(BaseModel):
    gate_id: str
    category: GateCategory
    created_in_phase: str
    questions: list[GateQuestion]
    status: GateStatus = GateStatus.OPEN
    answers: list[GateAnswer] = Field(default_factory=list)
    remaining_candidate_keys: list[str] = Field(default_factory=list)
    answered_at: Optional[datetime] = None

    def answered_keys(self) -> set[str]:
        return {a.decision_key for a in self.answers if a.matched}

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
    status: DecisionStatus = DecisionStatus.ACTIVE
    superseded_by: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Persisted collection wrappers
# ---------------------------------------------------------------------------


class IssueLog(BaseModel):
    issues: list[Issue] = Field(default_factory=list)
    next_issue_number: int = 1


class DecisionLog(BaseModel):
    decisions: list[Decision] = Field(default_factory=list)
    next_decision_number: int = 1


class GateLog(BaseModel):
    current: Optional[HumanGate] = None
    gates: list[HumanGate] = Field(default_factory=list)
    next_gate_number: int = 1
