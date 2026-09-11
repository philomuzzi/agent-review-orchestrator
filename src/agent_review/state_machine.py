"""Deterministic phase state machine.

Transitions out of terminal states are rejected; resume recovery is
handled explicitly by the orchestrator rather than by this table.
"""

from __future__ import annotations

from agent_review.models import Phase, SessionStatus

ALLOWED_TRANSITIONS: dict[Phase, set[Phase]] = {
    Phase.INIT: {Phase.DISCOVER},
    Phase.DISCOVER: {Phase.INTAKE, Phase.INVESTIGATE},
    Phase.INVESTIGATE: {Phase.INTAKE, Phase.WAITING_FOR_HUMAN, Phase.HUMAN_HANDOFF},
    Phase.INTAKE: {Phase.WAITING_FOR_HUMAN, Phase.DESIGN, Phase.HUMAN_HANDOFF},
    Phase.WAITING_FOR_HUMAN: {
        Phase.INTAKE,
        Phase.INVESTIGATE,
        Phase.DESIGN,
        Phase.REVISION,
        Phase.INTERRUPTED,
        Phase.HUMAN_HANDOFF,
        Phase.FAILED,
    },
    Phase.DESIGN: {Phase.INITIAL_REVIEW},
    Phase.INITIAL_REVIEW: {
        Phase.REVISION,
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
    Phase.CLOSURE_REVIEW: {
        Phase.REVISION,
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
    Phase.FINAL_REVIEW: {Phase.FINALIZE, Phase.HUMAN_HANDOFF},
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
