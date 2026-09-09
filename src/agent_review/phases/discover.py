"""DISCOVER phase: establish repository facts before any solutioning."""

from __future__ import annotations

from agent_review.models import ExitCode, Phase, TaskKind
from agent_review.rendering import render_discovery


def run_init(o) -> ExitCode | None:
    """INIT: session already persisted by StateStore; move to DISCOVER."""
    o.transition(Phase.DISCOVER)
    return None


def run(o) -> ExitCode | None:
    o.event("DISCOVER_STARTED")
    result = o.pi.discover(o.state)
    # Persist completed phase output BEFORE the transition (atomicity rule).
    o.store.save_discovery(result)
    o.store.write_text("discovery.md", render_discovery(result))
    if not o.state.kind_explicit:
        o.state.task_kind = result.task_kind or TaskKind.CHANGE
    o.event(
        "DISCOVER_COMPLETED",
        task_kind=o.state.task_kind.value,
        components=len(result.relevant_components),
    )
    if o.state.task_kind == TaskKind.PROBLEM:
        o.transition(Phase.INVESTIGATE)
    else:
        o.transition(Phase.INTAKE)
    return None
