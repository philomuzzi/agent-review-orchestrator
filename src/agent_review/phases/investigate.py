"""INVESTIGATE phase (Problem Mode only)."""

from __future__ import annotations

from agent_review.models import ExitCode, Phase, RootCauseStatus
from agent_review.rendering import render_investigation


def run(o) -> ExitCode | None:
    o.event("INVESTIGATE_STARTED")
    result = o.pi.investigate(o.state, discovery=o.store.load_discovery())
    o.store.save_investigation(result)
    o.store.write_text("investigation.md", render_investigation(result))
    o.event(
        "INVESTIGATE_COMPLETED",
        root_cause_status=result.root_cause_status.value,
    )
    if result.root_cause_status == RootCauseStatus.SUPPORTED:
        o.transition(Phase.INTAKE)
        return None
    # UNRESOLVED root cause: never fabricate a fix design (spec 8.2).
    # A FACT Human Gate may unblock this in M3; without resolvable human
    # facts this is a handoff.
    from agent_review.phases.human_gate import try_gate_for_unresolved_root_cause

    return try_gate_for_unresolved_root_cause(o, result)
