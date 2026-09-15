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
# Human Answer Alias Space (V0.2-RC3 B301)
#
# The CLI answering protocol accepts more than option keys: a Human may
# answer a Gate question with the option key, the option label, key +
# label, the numeric index, "选项N" or "option N". Reserved protocol
# control commands (custom-decision selectors, global recommendation
# selectors) live in the same input namespace and are recognized BEFORE
# option matching. The safety invariant is therefore not "option keys
# are unique" but "every normalized Human input accepted as
# authoritative has exactly one interpretation".
#
# These constants and helpers are the SINGLE source of truth shared by
# GateQuestion validation (prove the alias space is unambiguous BEFORE
# a Human is asked) and runtime answer matching (resolve input with the
# same alias sets). Keeping them in models means validators and the
# matching code can never drift apart.
# ---------------------------------------------------------------------------

# Explicit custom-decision mode selectors (V0.2 spec 4.1). Only these
# RESERVED protocol tokens turn free text into an authoritative Human
# Decision; unmatched prose never acquires Requirement Authority by
# itself. Option-owned aliases must not collide with these tokens.
CUSTOM_REQUEST_ANSWERS = frozenset(
    {
        "0",
        "custom",
        "自定义",
        "自定义决策",
        "自己定义",
        "自己决定",
    }
)

# Global recommendation selectors: apply every question's recommended
# option in one answer. Option-owned aliases must not collide with
# these tokens either.
GLOBAL_RECOMMEND_ANSWERS = frozenset(
    {
        "都按推荐",
        "按推荐",
        "全部按推荐",
        "all recommended",
    }
)


def normalized_custom_selector_aliases() -> frozenset[str]:
    """Custom-decision selectors after the answer normalization."""
    return frozenset(normalize_answer_text(a) for a in CUSTOM_REQUEST_ANSWERS)


def normalized_global_recommend_aliases() -> frozenset[str]:
    """Global recommendation selectors after the answer normalization."""
    return frozenset(normalize_answer_text(a) for a in GLOBAL_RECOMMEND_ANSWERS)


def normalized_protocol_control_aliases() -> frozenset[str]:
    """The full reserved protocol-control namespace, normalized (RC3 B301 §2.5).

    CUSTOM_REQUEST_ANSWERS ∪ GLOBAL_RECOMMEND_ANSWERS through the same
    ``normalize_answer_text`` used for option aliases and runtime answer
    matching. The numeric custom selector ``0`` is included through the
    custom-control set.
    """
    return normalized_custom_selector_aliases() | normalized_global_recommend_aliases()


def normalized_option_aliases(option, index: int) -> tuple[str, ...]:
    """Every normalized answer form the CLI accepts for one option.

    For the option at 1-based ``index`` the answering protocol accepts:
    the option key; the option label; ``key + " " + label``; the numeric
    index; ``"选项" + index``; ``"option " + index`` — each passed through
    ``normalize_answer_text`` exactly like runtime answer matching
    (RC3 B301 §2.5). Fixed order so violation reporting is deterministic.
    Aliases of the SAME option may normalize to the same string; aliases
    of DIFFERENT options must never intersect.
    """
    return (
        normalize_answer_text(option.key),
        normalize_answer_text(option.label),
        normalize_answer_text(f"{option.key} {option.label}"),
        normalize_answer_text(str(index)),
        normalize_answer_text(f"选项{index}"),
        normalize_answer_text(f"option {index}"),
    )


def option_alias_violation(options) -> str | None:
    """Deterministic Human Answer Alias Space check (RC3 B301 §2.5).

    Returns None when every alias is unambiguous; otherwise a
    deterministic error string for the FIRST violation in option order.
    Two rules are enforced:

    1. no alias of one option may intersect the alias set of another
       option (a Human answer must have exactly one interpretation);
    2. no option-owned alias may intersect the reserved protocol-control
       namespace (custom-decision / global recommendation selectors) —
       a displayed option must be safely selectable through every
       advertised answer form.

    Used by the shared GateQuestion model boundary, intake candidate
    suppression, and convergence packet validation — one rule, three
    enforcement points. Never auto-renames or reorders options.
    """
    control = normalized_protocol_control_aliases()
    owner: dict[str, int] = {}  # normalized alias -> 1-based option index
    for index, option in enumerate(options, 1):
        for alias in normalized_option_aliases(option, index):
            if alias in control:
                return (
                    f"option {index} answer alias {alias!r} collides with a "
                    "reserved protocol control command (custom/recommendation "
                    "selector); a displayed option must be safely selectable "
                    "through every advertised answer form"
                )
            prior_index = owner.get(alias)
            if prior_index is not None and prior_index != index:
                return (
                    f"answer alias {alias!r} matches both option {prior_index} "
                    f"and option {index}; every normalized Human answer must "
                    "have exactly one interpretation"
                )
            owner[alias] = index
    return None


# ---------------------------------------------------------------------------
# V0.3-RC1 B404: canonical design-section vocabulary.
#
# Focused Revision containment validates the ACTUAL serialized proposal
# delta, not the Agent's self-reported ``changed_sections``. The delta is
# computed over the top-level DesignResult fields that carry design
# semantics; ``allowed_change_scope`` entries from reviewer issues are
# matched against these canonical names after normalization
# (case/whitespace/hyphen-insensitive), so prompts instruct reviewers to
# use the canonical section names.
# ---------------------------------------------------------------------------

DESIGN_TEXT_SECTIONS: tuple[str, ...] = (
    "summary",
    "current_flow",
    "proposed_flow",
)

DESIGN_LIST_SECTIONS: tuple[str, ...] = (
    "changes",
    "data_model_changes",
    "interface_changes",
    "state_lifecycle_changes",
    "failure_handling",
    "compatibility",
    "risks",
    "alternatives_considered",
    "verification_plan",
    "explicitly_unchanged",
)

CHANGE_MAP_SECTIONS: tuple[str, ...] = (
    "affected_components",
    "data_changes",
    "api_changes",
    "config_changes",
    "behavior_changes",
    "unchanged_behaviors",
)


def normalize_section_name(name: str) -> str:
    """Canonical comparison form for design section names (B404)."""
    return re.sub(r"[\s\-]+", "_", name.strip().lower())


def _normalized_str_list(items: list[str]) -> list[str]:
    return sorted(s.strip() for s in items if s.strip())


def design_actual_changed_sections(old, new) -> list[str]:
    """Deterministic structural delta between two DesignResults (B404).

    Returns the canonical section names whose serialized content
    differs (order-insensitive for list fields; whitespace-normalized).
    This is Orchestrator-owned truth — Agent self-report never replaces
    it for containment decisions.
    """
    changed: list[str] = []
    for field in DESIGN_TEXT_SECTIONS:
        if (getattr(old, field) or "").strip() != (getattr(new, field) or "").strip():
            changed.append(field)
    for field in DESIGN_LIST_SECTIONS:
        if _normalized_str_list(getattr(old, field)) != _normalized_str_list(
            getattr(new, field)
        ):
            changed.append(field)
    for sub in CHANGE_MAP_SECTIONS:
        if _normalized_str_list(getattr(old.change_map, sub)) != _normalized_str_list(
            getattr(new.change_map, sub)
        ):
            changed.append(f"change_map.{sub}")
    return changed


def section_within_scope(section: str, allowed_change_scope: list[str]) -> bool:
    """Canonical-name containment check for one changed section (B404)."""
    canonical = normalize_section_name(section)
    return any(
        normalize_section_name(entry) == canonical for entry in allowed_change_scope
    )


def enforce_late_blocker_provenance(issues) -> None:
    """B401: a new BLOCKING issue from a LATE review phase fails closed
    when required provenance is missing — it is NEVER downgraded to
    NON_BLOCKING (a Reviewer protocol defect must not lower engineering
    severity or manufacture a false PASS).

    Deterministic compatibility default: a REGRESSION-categorized issue
    is the canonical INTRODUCED_BY_CORRECTION case, so the origin is
    filled mechanically when omitted.

    Enforced at the review-result model boundary (so real agents get
    protocol repair) and re-enforced by the orchestrator at ingest.
    """
    for issue in issues:
        if issue.severity != IssueSeverity.BLOCKING:
            continue
        if issue.origin is None and issue.category == IssueCategory.REGRESSION:
            issue.origin = NewIssueOrigin.INTRODUCED_BY_CORRECTION
        if issue.origin is None:
            raise ValueError(
                f"late BLOCKING issue '{issue.title}' must record origin "
                "(INTRODUCED_BY_CORRECTION | PREVIOUS_REVIEW_MISS | NEW_EVIDENCE | "
                "DIRECTLY_REQUIRED_FOR_CLOSURE); missing provenance fails closed "
                "and is never downgraded to NON_BLOCKING"
            )
        if (
            issue.origin == NewIssueOrigin.PREVIOUS_REVIEW_MISS
            and not (issue.why_not_detected_initially or "").strip()
        ):
            raise ValueError(
                f"late BLOCKING issue '{issue.title}' with origin "
                "PREVIOUS_REVIEW_MISS must explain why_not_detected_initially; "
                "the packet is invalid and fails closed"
            )


def validate_candidate_dependency_packet(candidates, packet: str) -> None:
    """B402: packet-local ``candidate_id`` dependency protocol.

    Human candidates get an explicit packet-local identity the Agent
    authors itself (``candidate_id``), and ``depends_on`` references
    those ids — never the orchestrator's internal decision-key hash.
    Unknown, self-referencing or cyclic dependencies are INVALID (fail
    closed with an auditable reason); they never silently become
    independent questions.

    Compatibility rule: candidates with no ``depends_on`` may omit
    ``candidate_id`` (identical to pre-RC1 independent packets);
    dependency expression and references require the public protocol.
    """
    id_index: dict[str, int] = {}
    for index, candidate in enumerate(candidates):
        cid = (candidate.candidate_id or "").strip()
        if not cid:
            continue
        if cid in id_index:
            raise ValueError(
                f"{packet}: duplicate candidate_id {cid!r}; candidate ids must "
                "be unique within one Agent packet"
            )
        id_index[cid] = index
    graph: dict[int, set[int]] = {}
    for index, candidate in enumerate(candidates):
        if not candidate.depends_on:
            continue
        cid = (candidate.candidate_id or "").strip()
        if not cid:
            raise ValueError(
                f"{packet}: a candidate declaring depends_on must carry its own "
                "non-empty candidate_id (public packet-local protocol)"
            )
        deps: set[int] = set()
        for ref in candidate.depends_on:
            ref = (ref or "").strip()
            if not ref:
                raise ValueError(
                    f"{packet}: candidate {cid!r} declares an empty dependency "
                    "reference"
                )
            if ref == cid:
                raise ValueError(
                    f"{packet}: candidate {cid!r} depends on itself; "
                    "self-dependency is invalid"
                )
            if ref not in id_index:
                raise ValueError(
                    f"{packet}: candidate {cid!r} depends on unknown candidate_id "
                    f"{ref!r}; unknown dependencies are invalid and never "
                    "silently treated as independent"
                )
            deps.add(id_index[ref])
        graph[index] = deps
    # Deterministic cycle detection (iterative DFS in packet order).
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {i: WHITE for i in graph}
    for start in sorted(graph):
        if color[start] != WHITE:
            continue
        stack = [(start, iter(sorted(graph[start])))]
        color[start] = GRAY
        while stack:
            node, edges = stack[-1]
            advanced = False
            for nxt in edges:
                if nxt not in graph:
                    continue
                if color[nxt] == GRAY:
                    raise ValueError(
                        f"{packet}: candidate dependency cycle detected through "
                        f"candidate_id {candidates[nxt].candidate_id!r}; cyclic "
                        "dependencies are invalid and fail closed"
                    )
                if color[nxt] == WHITE:
                    color[nxt] = GRAY
                    stack.append((nxt, iter(sorted(graph[nxt]))))
                    advanced = True
                    break
            if not advanced:
                color[node] = BLACK
                stack.pop()


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Phase(str, Enum):
    INIT = "INIT"
    DISCOVER = "DISCOVER"
    # V0.3 C0: scope guard sits between repository discovery and any
    # solutioning; unsuitable single-session tasks stop before DESIGN.
    SCOPE_GUARD = "SCOPE_GUARD"
    INVESTIGATE = "INVESTIGATE"
    INTAKE = "INTAKE"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    DESIGN = "DESIGN"
    INITIAL_REVIEW = "INITIAL_REVIEW"
    REVISION = "REVISION"
    # V0.3 C3: focused correction of a bounded part of an otherwise
    # valid design; a separate mechanism from full REVISION, not a
    # sequential life in one generic ladder.
    FOCUSED_REVISION = "FOCUSED_REVISION"
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


# V0.3 C1: user-facing terminal result classification. Deliberately a
# SEPARATE concept from the internal workflow state (design §56): the
# internal phase may be HUMAN_HANDOFF while the user-facing result is
# DESIGN_NOT_APPROVED (engineering conclusion) or NEEDS_HUMAN_DECISION
# (genuine new Human authority required). Agent convergence failure
# must never be mislabeled as a Human decision need.
class ResultStatus(str, Enum):
    APPROVED = "APPROVED"
    DESIGN_NOT_APPROVED = "DESIGN_NOT_APPROVED"
    NEEDS_HUMAN_DECISION = "NEEDS_HUMAN_DECISION"
    DECOMPOSITION_REQUIRED = "DECOMPOSITION_REQUIRED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    FAILED = "FAILED"


# V0.3 C0: scope verdicts after DISCOVER (design §9).
class ScopeVerdict(str, Enum):
    BOUNDED = "BOUNDED"
    DECOMPOSITION_REQUIRED = "DECOMPOSITION_REQUIRED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


# V0.3 C2: generic correction actions (design §25). Agents RECOMMEND an
# action; the deterministic orchestrator controls execution (§32).
class CorrectionAction(str, Enum):
    FULL_REVISION = "FULL_REVISION"
    FOCUSED_REVISION = "FOCUSED_REVISION"
    ABLATION = "ABLATION"
    HUMAN_DECISION = "HUMAN_DECISION"
    STOP = "STOP"


# V0.3 C2 §31: descriptive focus dimension. NEVER creates additional
# workflow states — both FOCUSED_REVISION+VALIDATION and
# FOCUSED_REVISION+DATA use the same workflow path.
class FocusArea(str, Enum):
    BEHAVIOR = "BEHAVIOR"
    DATA = "DATA"
    INTEGRATION = "INTEGRATION"
    VALIDATION = "VALIDATION"
    OPERABILITY = "OPERABILITY"
    PERFORMANCE = "PERFORMANCE"
    SECURITY = "SECURITY"
    COMPATIBILITY = "COMPATIBILITY"
    OTHER = "OTHER"


# V0.3 C4 §43/§45: why a new issue appeared in a later review phase.
class NewIssueOrigin(str, Enum):
    INTRODUCED_BY_CORRECTION = "INTRODUCED_BY_CORRECTION"
    PREVIOUS_REVIEW_MISS = "PREVIOUS_REVIEW_MISS"
    NEW_EVIDENCE = "NEW_EVIDENCE"
    DIRECTLY_REQUIRED_FOR_CLOSURE = "DIRECTLY_REQUIRED_FOR_CLOSURE"


# V0.3 C4 §46–49: material progress of a persistent blocker, assessed
# from structured evidence (close-condition delta, notes, changed
# sections) — never from "looks better" prose.
class MaterialProgress(str, Enum):
    PROGRESSED = "PROGRESSED"
    NO_PROGRESS = "NO_PROGRESS"


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
    # V0.3 §37: full revision, focused revision and ablation are
    # semantically different corrective actions, not sequential lives
    # in one generic ladder. Budgets are NOT increased merely because
    # V0.2 exhausted them.
    max_revision_rounds: int = 1  # FULL_REVISION budget
    max_focused_revision_rounds: int = 1  # FOCUSED_REVISION budget
    max_ablation_rounds: int = 1
    max_human_interruptions: int = 2
    max_protocol_retries: int = 1


class BudgetUsage(BaseModel):
    revision_used: int = 0
    focused_revision_used: int = 0
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
    # V0.3 C1: user-facing terminal result classification (None while
    # running). Written at the terminal boundary together with
    # session-result.md; never a routing key for the state machine.
    result_status: Optional[str] = None
    # V0.3 C0: persisted scope verdict for status/telemetry/audit.
    scope_verdict: Optional[str] = None
    # V0.3 C2: the correction mechanism that ran most recently
    # (FULL_REVISION / FOCUSED_REVISION / ABLATION). Read by closure
    # routing as the ``attempted_action`` for material-progress stops.
    last_correction_action: Optional[str] = None
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
    # V0.3-RC1 B402: explicit packet-local identity the Agent authors and
    # references. ``depends_on`` lists candidate ids from the SAME packet —
    # never the orchestrator's internal decision-key hash (a real Agent
    # has no stable way to know another candidate's generated key while
    # producing one packet). Validation: see
    # ``validate_candidate_dependency_packet``.
    candidate_id: Optional[str] = None
    category: str
    question: str
    why: str = ""
    options: list[GateOption] = Field(default_factory=list)
    recommendation: Optional[str] = None
    source: str = ""
    # V0.3 C5 §51: decision keys of OTHER candidates whose answers this
    # question's final wording or valid options materially depend on.
    # A candidate may be deferred to a later gate ONLY when it declares
    # such a dependency on the current gate; independent candidates are
    # batched into the same gate.
    # RC1 semantics: the Agent fills packet-local candidate ids here;
    # the orchestrator resolves them to internal decision keys in
    # ``depends_on_keys`` after packet validation.
    depends_on: list[str] = Field(default_factory=list)
    # Orchestrator-owned resolution of ``depends_on`` candidate ids to
    # internal stable decision keys (populated at collection time from
    # the candidate's own packet; empty for independent candidates).
    depends_on_keys: list[str] = Field(default_factory=list)


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

    @model_validator(mode="after")
    def _candidate_packet_valid(self) -> "DiscoveryResult":
        # B402: the candidate dependency protocol is validated at the
        # packet boundary so real agents get protocol repair.
        validate_candidate_dependency_packet(self.human_candidates, "discovery")
        return self


# ---------------------------------------------------------------------------
# V0.3 C0: Scope Guard assessment (design §8–§13)
# ---------------------------------------------------------------------------


class DecompositionProposal(BaseModel):
    """One proposed bounded child session (design §11/§13).

    Split by independent decision/acceptance/outcome boundaries — never
    mechanically by folder, class or technology name.
    """

    title: str
    goal: str
    inputs: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _require_title_and_goal(self) -> "DecompositionProposal":
        if not self.title.strip() or not self.goal.strip():
            raise ValueError("DecompositionProposal requires non-empty title and goal")
        return self


class ScopeAssessment(BaseModel):
    """Structured scope judgment produced by the Agent after DISCOVER.

    The Agent may judge scope probabilistically; the ORCHESTRATOR
    controls continuation deterministically (design §12): only a
    BOUNDED verdict may enter the normal workflow. Per §54 the scope
    guard must not invent Requirement decisions — when classification
    depends on a real Requirement ambiguity the Agent classifies
    conservatively and records the uncertainty instead of guessing.
    """

    verdict: ScopeVerdict
    primary_outcome: str = ""
    independent_outcomes: list[str] = Field(default_factory=list)
    decision_clusters: list[str] = Field(default_factory=list)
    change_surfaces: list[str] = Field(default_factory=list)
    external_unknowns: list[str] = Field(default_factory=list)
    rationale: str = ""
    # §54 conservative-classification explanation (optional).
    uncertainty: str = ""
    decomposition: list[DecompositionProposal] = Field(default_factory=list)

    @model_validator(mode="after")
    def _verdict_shape(self) -> "ScopeAssessment":
        if not self.rationale.strip():
            raise ValueError("ScopeAssessment requires a non-empty rationale")
        if self.verdict == ScopeVerdict.DECOMPOSITION_REQUIRED:
            if len(self.decomposition) < 2:
                raise ValueError(
                    "DECOMPOSITION_REQUIRED requires at least two proposed "
                    "child sessions (a single child session is not a "
                    "decomposition)"
                )
            if not self.independent_outcomes:
                raise ValueError(
                    "DECOMPOSITION_REQUIRED requires the independently "
                    "converging outcomes that motivated the split"
                )
        if self.verdict == ScopeVerdict.BOUNDED and not self.primary_outcome.strip():
            raise ValueError("BOUNDED requires a primary_outcome")
        return self


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
    def _candidate_packet_valid(self) -> "InvestigationResult":
        # B402: same packet-local dependency protocol as discovery.
        validate_candidate_dependency_packet(self.human_candidates, "investigation")
        return self

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


# V0.3-RC1 B403: valid Requirement-Authority reference forms for a
# Contract acceptance criterion. "REQUEST" = the original user request
# (always resolvable); "D###" = an ACTIVE Human Decision id. Acceptance
# ids ("A###") are deliberately NOT valid authority for the contract's
# own criteria (an Agent writing a criterion into the Contract never
# grants it Requirement Authority by itself).
AUTHORITY_REF_PATTERN = re.compile(r"^(REQUEST|D\d{3,})$")
ACCEPTANCE_ID_PATTERN = re.compile(r"^A\d{3,}$")


class AcceptanceCriterion(BaseModel):
    """B403: one authoritative acceptance criterion owned by the Change
    Contract (the current effective Acceptance Baseline for ONE task
    revision).

    Requirements:

    - ``id`` is stable within the task revision (A001, A002, ...);
    - every authoritative criterion carries mechanically valid
      Requirement-Authority provenance (REQUEST or an ACTIVE Human
      Decision id) — an Agent merely writing a criterion into the
      Contract grants no authority;
    - assumptions / open questions never enter this set.

    When new evidence legitimately changes Requirement understanding,
    the existing task_revision / contract-rebuild mechanism produces a
    NEW baseline for the new revision; reviewers never silently mutate
    the current one.
    """

    id: str
    criterion: str
    authority_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _criterion_shape(self) -> "AcceptanceCriterion":
        if not ACCEPTANCE_ID_PATTERN.fullmatch(self.id.strip()):
            raise ValueError(
                f"acceptance criterion id must match A### (e.g. A001), "
                f"got {self.id!r}"
            )
        self.id = self.id.strip()
        if not self.criterion.strip():
            raise ValueError(f"acceptance criterion {self.id} requires text")
        if not self.authority_refs:
            raise ValueError(
                f"acceptance criterion {self.id} requires authority provenance "
                "(REQUEST and/or ACTIVE Human Decision ids); an Agent-written "
                "criterion without authority is not authoritative"
            )
        for ref in self.authority_refs:
            ref = (ref or "").strip()
            if not AUTHORITY_REF_PATTERN.fullmatch(ref):
                raise ValueError(
                    f"acceptance criterion {self.id} has unknown authority ref "
                    f"{ref!r}; valid forms: REQUEST or D### (ACTIVE decision id)"
                )
        return self


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
    # V0.3-RC1 B403: the CURRENT effective Acceptance Baseline owned by
    # the Contract. Empty ONLY for legacy pre-RC1 persisted sessions
    # (explicit compatibility rule: see review.effective_acceptance_baseline);
    # every new RC1 session builds a non-empty baseline in INTAKE.
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)

    @model_validator(mode="after")
    def _require_core_fields(self) -> "ChangeContract":
        for name in ("user_intent", "current_behavior", "desired_behavior"):
            if not getattr(self, name).strip():
                raise ValueError(f"ChangeContract requires non-empty {name}")
        ids = [criterion.id for criterion in self.acceptance_criteria]
        if len(ids) != len(set(ids)):
            raise ValueError(
                "ChangeContract acceptance criterion ids must be unique within "
                f"one task revision; duplicates: "
                + ", ".join(sorted({i for i in ids if ids.count(i) > 1}))
            )
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


# ---------------------------------------------------------------------------
# V0.3 C3: Focused Revision (design §33–§37)
# ---------------------------------------------------------------------------


class FocusedRevisionResult(BaseModel):
    """Result of one focused revision targeting specific blocking issues.

    The Author returns the complete updated proposal (delta persistence
    is impractical in this architecture — design §36 permits the full
    rewrite as the SERIALIZATION format) plus the structured focused
    contract evidence: what was targeted, what scope was allowed, what
    was preserved, what changed, and an issue-by-issue response against
    each close condition.
    """

    proposal: DesignResult
    target_issue_ids: list[str]
    allowed_change_scope: list[str] = Field(default_factory=list)
    preserved_invariants: list[str] = Field(default_factory=list)
    changed_sections: list[str] = Field(default_factory=list)
    issue_responses: list[AddressedIssue] = Field(default_factory=list)
    acceptance_changes: list[str] = Field(default_factory=list)
    notes: str = ""

    @model_validator(mode="after")
    def _responses_required(self) -> "FocusedRevisionResult":
        if not self.target_issue_ids:
            raise ValueError("FocusedRevisionResult requires target_issue_ids")
        responded = {r.issue_id for r in self.issue_responses}
        missing = [i for i in self.target_issue_ids if i not in responded]
        if missing:
            raise ValueError(
                f"FocusedRevisionResult must respond issue-by-issue; missing "
                f"responses for: {', '.join(missing)}"
            )
        return self


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
    # V0.3 C2: reviewer-recommended generic correction action. None
    # means "no explicit recommendation" — the deterministic routing
    # then applies the conservative default FULL_REVISION (the pre-V0.3
    # behavior for unresolved engineering blockers).
    correction_action: Optional[CorrectionAction] = None
    # V0.3 C2 §31: descriptive focus dimension; never a workflow state.
    focus_area: Optional[FocusArea] = None
    # V0.3 C3: sections/components a focused fix of this issue may
    # touch. Empty = semantic scope (no mechanical containment check).
    change_scope: list[str] = Field(default_factory=list)
    # V0.3 C4 §43/§45: why this issue appeared in a LATER review phase.
    # None is legitimate only for INITIAL_REVIEW issues; ingest enforces
    # presence for new BLOCKING issues from CLOSURE/FINAL review.
    origin: Optional[NewIssueOrigin] = None
    # Orchestrator-owned routing metadata (V0.2): ACTIVE decision ids a
    # Human Authority Check proved to cover this issue's semantics.
    # Persisted with the issue so later phase-entry re-checks do not
    # re-flip it NEED_HUMAN; reset on ingest so the reviewer can never
    # forge coverage.
    covered_by_decisions: list[str] = Field(default_factory=list)
    # V0.3-RC1 B405: the FULL resolved authority-reference list (decision
    # ids + acceptance ids + REQUEST) proving coverage by the current
    # effective Requirement Authority. Auditable routing metadata; reset
    # on ingest together with covered_by_decisions.
    covered_by_authority: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _blocking_requires_acceptance(self) -> "Issue":
        if self.severity == IssueSeverity.BLOCKING and not self.acceptance:
            raise ValueError(
                f"BLOCKING issue '{self.title}' requires explicit acceptance criteria"
            )
        return self


class AcceptanceCoverageEntry(BaseModel):
    """V0.3 C4 §40 + RC1 B403: explicit accounting for one acceptance
    criterion of the CURRENT Contract baseline.

    Coverage is reported by stable acceptance ID (``acceptance_id``);
    ``criterion`` is the display echo. The invariant is that acceptance
    criteria may not silently disappear from review: a FAIL entry must
    name the BLOCKING issue (by exact title) that carries the criterion
    in the same result. ``acceptance_id`` is optional only for legacy
    pre-RC1 persisted coverage (ids are assigned in recorded order by
    the compatibility rule).
    """

    criterion: str
    status: str  # PASS | FAIL
    issue_title: Optional[str] = None
    acceptance_id: Optional[str] = None
    note: str = ""

    @model_validator(mode="after")
    def _coverage_shape(self) -> "AcceptanceCoverageEntry":
        if self.status not in ("PASS", "FAIL"):
            raise ValueError(
                f"acceptance coverage status must be PASS or FAIL, "
                f"got {self.status!r}"
            )
        if not self.criterion.strip():
            raise ValueError("acceptance coverage criterion must be non-empty")
        if self.acceptance_id is not None and not ACCEPTANCE_ID_PATTERN.fullmatch(
            self.acceptance_id.strip()
        ):
            raise ValueError(
                f"acceptance coverage acceptance_id must match A###, "
                f"got {self.acceptance_id!r}"
            )
        if self.acceptance_id is not None:
            self.acceptance_id = self.acceptance_id.strip()
        if self.status == "FAIL" and not (self.issue_title or "").strip():
            raise ValueError(
                f"acceptance criterion {self.criterion!r} marked FAIL must "
                "reference the BLOCKING issue title that carries it"
            )
        return self


class InitialReviewResult(BaseModel):
    issues: list[Issue] = Field(default_factory=list)
    # V0.3 C4 §39/§40: comprehensive review must explicitly account for
    # every acceptance criterion derived from the contract.
    acceptance_coverage: list[AcceptanceCoverageEntry] = Field(default_factory=list)
    summary: str = ""


class CorrectionRecommendation(BaseModel):
    """V0.3 C2: reviewer recommendation of the next correction step for
    one unresolved blocking issue. The orchestrator routes
    mechanically; unknown/malformed actions already failed closed at
    the enum boundary."""

    issue_id: str
    correction_action: CorrectionAction
    focus_area: Optional[FocusArea] = None
    # C4 §46–49: structured material-progress assessment (required on
    # outcomes of issues that already went through a correction
    # attempt). PROGRESSED requires evidence in ``note`` — "looks
    # better" prose is never sufficient (§49).
    material_progress: Optional[MaterialProgress] = None
    note: str = ""

    @model_validator(mode="after")
    def _progress_note_shape(self) -> "CorrectionRecommendation":
        if self.material_progress == MaterialProgress.PROGRESSED and not self.note.strip():
            raise ValueError(
                f"PROGRESSED for {self.issue_id} requires a note with the "
                "structured evidence (close-condition delta / new evidence "
                "/ narrowed scope)"
            )
        return self


class IssueOutcome(BaseModel):
    issue_id: str
    resolution: str  # RESOLVED | UNRESOLVED
    note: str = ""
    # V0.3 C2/C4: for UNRESOLVED outcomes the closure reviewer also
    # recommends the next correction action and assesses material
    # progress since the attempted correction.
    correction_action: Optional[CorrectionAction] = None
    focus_area: Optional[FocusArea] = None
    material_progress: Optional[MaterialProgress] = None


class ClosureReviewResult(BaseModel):
    issue_outcomes: list[IssueOutcome] = Field(default_factory=list)
    new_issues: list[Issue] = Field(default_factory=list)
    summary: str = ""

    @model_validator(mode="after")
    def _late_blockers_require_provenance(self) -> "ClosureReviewResult":
        # B401: enforced at the model boundary so real agents receive
        # protocol repair; a late BLOCKING issue without valid provenance
        # fails closed instead of being downgraded.
        enforce_late_blocker_provenance(self.new_issues)
        return self


class FinalReviewResult(BaseModel):
    satisfies_requirement: bool = False
    unresolved_issue_ids: list[str] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    # V0.3 C4 §44: readiness review re-accounts every acceptance
    # criterion from the current Contract baseline (completeness
    # invariant; exact-ID equality, RC1 B403).
    acceptance_coverage: list[AcceptanceCoverageEntry] = Field(default_factory=list)
    # V0.3 C2: next-step recommendations for the blockers listed in
    # unresolved_issue_ids (defaults to FULL_REVISION when absent).
    correction_recommendations: list[CorrectionRecommendation] = Field(
        default_factory=list
    )
    summary: str = ""

    @model_validator(mode="after")
    def _late_blockers_require_provenance(self) -> "FinalReviewResult":
        # B401: same fail-closed contract as CLOSURE_REVIEW.
        enforce_late_blocker_provenance(self.issues)
        return self


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
        # Full Human Answer Alias Space (V0.2-RC3 B301 §2.5/§2.8): the
        # CLI accepts key / label / key+label / numeric index / 选项N /
        # option N, and reserves control commands in the same namespace.
        # Every alias must have exactly one interpretation; validation
        # uses the SAME helper as runtime answer matching so the two can
        # never drift apart. Enforced here at the shared model boundary
        # so normal Intake gates, Problem Mode FACT gates, convergence
        # gates and future gate producers all inherit the invariant.
        violation = option_alias_violation(self.options)
        if violation is not None:
            raise ValueError(
                f"GateQuestion '{self.decision_key}': {violation}"
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
    # V0.3-RC1 B405: coverage may also reference the CURRENT effective
    # Requirement Authority beyond decisions: "A###" (an acceptance
    # criterion of the current Contract baseline) and "REQUEST" (the
    # original user request). Every reference must resolve to persisted
    # current-authority data; stale/superseded sources fail closed.
    authority_refs: list[str] = Field(default_factory=list)
    rationale: str = ""
    decision_candidate: Optional[DecisionCandidate] = None

    @model_validator(mode="after")
    def _outcome_shape(self) -> "IssueAuthorityOutcome":
        if self.outcome == AuthorityOutcome.COVERED_BY_ACTIVE_DECISION:
            if not (self.referenced_decision_ids or self.authority_refs):
                raise ValueError(
                    f"COVERED_BY_ACTIVE_DECISION for {self.issue_id} requires "
                    "referenced_decision_ids and/or authority_refs (D### / "
                    "A### / REQUEST)"
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
