"""Deterministic phase state machine.

Transitions out of terminal states are rejected; resume recovery is
handled explicitly by the orchestrator rather than by this table.
"""

from __future__ import annotations

from agent_review.models import Phase, SessionStatus

ALLOWED_TRANSITIONS: dict[Phase, set[Phase]] = {
    Phase.INIT: {Phase.DISCOVER},
    # V0.3 C0: repository discovery is always followed by the scope
    # guard; no path bypasses it into solutioning.
    Phase.DISCOVER: {Phase.SCOPE_GUARD},
    Phase.SCOPE_GUARD: {
        Phase.INTAKE,
        Phase.INVESTIGATE,
        # DECOMPOSITION_REQUIRED / OUT_OF_SCOPE terminate here —
        # internally a task-level boundary; the user-facing result
        # status carries the classification (design §56).
        Phase.HUMAN_HANDOFF,
    },
    Phase.INVESTIGATE: {Phase.INTAKE, Phase.WAITING_FOR_HUMAN, Phase.HUMAN_HANDOFF},
    Phase.INTAKE: {Phase.WAITING_FOR_HUMAN, Phase.DESIGN, Phase.HUMAN_HANDOFF},
    Phase.WAITING_FOR_HUMAN: {
        Phase.INTAKE,
        Phase.INVESTIGATE,
        Phase.DESIGN,
        Phase.REVISION,
        Phase.FOCUSED_REVISION,
        Phase.INTERRUPTED,
        Phase.HUMAN_HANDOFF,
        Phase.FAILED,
    },
    Phase.DESIGN: {Phase.INITIAL_REVIEW},
    Phase.INITIAL_REVIEW: {
        Phase.REVISION,
        Phase.FOCUSED_REVISION,
        Phase.ABLATION,
        Phase.FINALIZE,
        Phase.WAITING_FOR_HUMAN,
        Phase.HUMAN_HANDOFF,
    },
    Phase.REVISION: {
        Phase.CLOSURE_REVIEW,
        # V0.2: a Convergence Gate may open from within the correction
        # phases when a review-discovered decision cannot be resolved
        # by revision/ablation alone.
        Phase.WAITING_FOR_HUMAN,
        Phase.HUMAN_HANDOFF,
    },
    # V0.3 C3: focused correction of a bounded part of an otherwise
    # valid design. Closure review verifies the focused fix, exactly as
    # it verifies a full revision — the Author never verifies itself.
    Phase.FOCUSED_REVISION: {
        Phase.CLOSURE_REVIEW,
        Phase.WAITING_FOR_HUMAN,
        Phase.HUMAN_HANDOFF,
    },
    Phase.CLOSURE_REVIEW: {
        Phase.REVISION,
        Phase.FOCUSED_REVISION,
        Phase.ABLATION,
        Phase.FINALIZE,
        Phase.WAITING_FOR_HUMAN,
        Phase.HUMAN_HANDOFF,
    },
    Phase.ABLATION: {
        Phase.FINAL_REVIEW,
        Phase.WAITING_FOR_HUMAN,
        Phase.HUMAN_HANDOFF,
    },
    Phase.FINAL_REVIEW: {
        Phase.FINALIZE,
        # V0.2-RC2 (B201): Final Review obeys the same Human Authority /
        # Convergence Gate semantics as Initial/Closure Review. A true new
        # Human decision may open a bounded Convergence Gate; a blocker
        # proven covered by an ACTIVE decision may consume remaining
        # correction budget instead of terminating by category alone.
        Phase.WAITING_FOR_HUMAN,
        Phase.REVISION,
        Phase.FOCUSED_REVISION,
        Phase.ABLATION,
        Phase.HUMAN_HANDOFF,
    },
    Phase.FINALIZE: {Phase.DONE},
    # Terminal states: no outbound transitions.
    Phase.DONE: set(),
    Phase.HUMAN_HANDOFF: set(),
    Phase.INTERRUPTED: set(),
    Phase.FAILED: set(),
}

# Global targets permitted from any non-terminal phase.
GLOBAL_TARGETS: set[Phase] = {Phase.FAILED, Phase.INTERRUPTED}

RESUMABLE_STATUSES = {
    SessionStatus.RUNNING,  # e.g. WAITING_FOR_HUMAN phase
    SessionStatus.INTERRUPTED,
    SessionStatus.FAILED,
}


def can_transition(current: Phase, target: Phase) -> bool:
    if current in (Phase.FAILED, Phase.INTERRUPTED, Phase.DONE, Phase.HUMAN_HANDOFF):
        return False
    return target in ALLOWED_TRANSITIONS.get(current, set()) or target in GLOBAL_TARGETS


def assert_transition(current: Phase, target: Phase) -> None:
    if not can_transition(current, target):
        raise ValueError(f"illegal phase transition: {current.value} -> {target.value}")
