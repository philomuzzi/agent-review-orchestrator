"""SCOPE_GUARD phase (V0.3 C0).

Runs after DISCOVER: the Agent produces a structured scope assessment
(verdict + decomposition guidance when required); the ORCHESTRATOR
controls continuation deterministically (design §12). No Agent may
silently override the Scope Guard by continuing the workflow: only a
BOUNDED verdict may enter INVESTIGATE/INTAKE; DECOMPOSITION_REQUIRED
and OUT_OF_SCOPE stop BEFORE any Design/Review budget is spent and
produce an actionable terminal result.

Scope Guard never invents Requirement decisions (§54): when the
classification would depend on a real Requirement ambiguity the Agent
classifies conservatively and records the uncertainty — no gate is
opened from this phase.
"""

from __future__ import annotations

from agent_review.models import ExitCode, Phase, ResultStatus, ScopeVerdict, TaskKind
from agent_review.rendering import render_scope_assessment


def run(o) -> ExitCode | None:
    o.event("SCOPE_GUARD_STARTED")
    discovery = o.store.load_discovery()
    if discovery is None:
        o.fail("SCOPE_GUARD reached without discovery")
        return int(ExitCode.FAILED)
    result = o.agent_call(
        "pi", "scope_guard", lambda: o.pi.scope_guard(o.state, discovery)
    )
    # Persist the completed phase output BEFORE any transition (atomicity).
    o.store.save_scope_assessment(result)
    o.store.write_text("scope-assessment.md", render_scope_assessment(result))
    o.state.scope_verdict = result.verdict.value
    o.store.save_state(o.state)
    o.event(
        "SCOPE_GUARD_COMPLETED",
        verdict=result.verdict.value,
        independent_outcomes=len(result.independent_outcomes),
        decomposition_count=len(result.decomposition),
        uncertainty=bool(result.uncertainty.strip()) or None,
    )

    if result.verdict == ScopeVerdict.BOUNDED:
        if o.state.task_kind == TaskKind.PROBLEM:
            o.transition(Phase.INVESTIGATE)
        else:
            o.transition(Phase.INTAKE)
        return None

    # DECOMPOSITION_REQUIRED / OUT_OF_SCOPE: terminal task-level boundary.
    # Internally HUMAN_HANDOFF (minimal state-machine expansion, §55/§56);
    # the user-facing classification lives in result_status and
    # session-result.md. handoff() renders session-result.md with the
    # Decomposition Proposal section (design §19/§22).
    reason = (
        f"scope guard: {result.verdict.value} — {result.rationale}"
    )
    o.event(
        "SCOPE_GUARD_STOPPED",
        verdict=result.verdict.value,
        rationale=result.rationale,
        decomposition_count=len(result.decomposition),
    )
    o.handoff(
        reason,
        result_status=(
            ResultStatus.DECOMPOSITION_REQUIRED.value
            if result.verdict == ScopeVerdict.DECOMPOSITION_REQUIRED
            else ResultStatus.OUT_OF_SCOPE.value
        ),
    )
    return int(ExitCode.HUMAN_HANDOFF)
