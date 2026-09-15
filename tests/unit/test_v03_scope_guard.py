"""V0.3 C0 — Scope Guard deterministic tests (design §8–§13, §54–§57).

Covers the design §60 test plan items: BOUNDED scope continuation,
DECOMPOSITION_REQUIRED early termination, OUT_OF_SCOPE early
termination, decomposition result rendering, and the scope-control
principle (the orchestrator — never the agent — controls continuation).
"""

from __future__ import annotations

import json

from agent_review.agents.fakes import FakeCodexAdapter, FakePiAdapter
from agent_review.config import Config
from agent_review.models import ExitCode, Phase, SessionStatus
from agent_review.orchestrator import Orchestrator
from agent_review.state_machine import ALLOWED_TRANSITIONS, can_transition

from tests.unit.test_m3_human_gate import (
    ScriptedUI,
    candidate,
    discovery_with_candidates,
    make_orchestrator,
)


def scope_guard_json(verdict="BOUNDED", **extra):
    payload = {
        "verdict": verdict,
        "primary_outcome": "one coherent bounded engineering outcome",
        "independent_outcomes": [],
        "decision_clusters": ["feature semantics"],
        "change_surfaces": ["src/pipeline.py"],
        "external_unknowns": [],
        "rationale": "single primary outcome; tightly coupled decisions",
    }
    if verdict == "DECOMPOSITION_REQUIRED":
        payload.update(
            {
                "primary_outcome": "",
                "independent_outcomes": [
                    "comparison contract semantics",
                    "comparison engine implementation",
                    "scheduling/rollout operationalization",
                ],
                "rationale": (
                    "three independently deliverable outcomes with "
                    "independent acceptance boundaries"
                ),
                "decomposition": [
                    {
                        "title": "Comparison Contract",
                        "goal": "settle the comparison semantics and data contract",
                        "inputs": ["request", "repository discovery"],
                        "non_goals": ["engine implementation", "deployment"],
                        "dependencies": [],
                    },
                    {
                        "title": "Comparison Engine",
                        "goal": "implement the engine against the contract",
                        "inputs": ["Comparison Contract result"],
                        "non_goals": ["semantics changes"],
                        "dependencies": ["Comparison Contract"],
                    },
                    {
                        "title": "Operationalization",
                        "goal": "scheduling, rollout and alerting design",
                        "inputs": ["Comparison Engine result"],
                        "non_goals": ["engine redesign"],
                        "dependencies": ["Comparison Engine"],
                    },
                ],
            }
        )
    if verdict == "OUT_OF_SCOPE":
        payload.update(
            {
                "primary_outcome": "",
                "rationale": "whole-product exploration from scratch; no bounded repository change",
            }
        )
    payload.update(extra)
    return json.dumps(payload)


def events_of(o) -> list[dict]:
    return [
        json.loads(line)
        for line in (o.store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]


# --- BOUNDED continuation ------------------------------------------------------


def test_bounded_scope_continues_normal_workflow(repo):
    pi = FakePiAdapter(script={"scope_guard": [scope_guard_json("BOUNDED")]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.DONE)
    assert o.state.scope_verdict == "BOUNDED"
    assert (o.store.dir / "scope-assessment.json").is_file()
    events = [e["event"] for e in events_of(o)]
    assert "SCOPE_GUARD_STARTED" in events
    assert "SCOPE_GUARD_COMPLETED" in events
    assert "SCOPE_GUARD_STOPPED" not in events


def test_default_fake_scope_guard_is_bounded(repo):
    """Unscripted fake runs keep flowing into the normal workflow."""
    o = make_orchestrator(repo, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.DONE)
    assert o.state.scope_verdict == "BOUNDED"


def test_bounded_problem_mode_routes_to_investigate(repo):
    pi = FakePiAdapter(
        script={
            "discover": [discovery_with_candidates([], task_kind="PROBLEM")],
            "scope_guard": [scope_guard_json("BOUNDED")],
        }
    )
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(interactive=False), kind="problem")
    assert o.run() == int(ExitCode.DONE)
    events = [e["event"] for e in events_of(o)]
    assert "INVESTIGATE_STARTED" in events


# --- DECOMPOSITION_REQUIRED early termination -----------------------------------


def make_composite(repo):
    """The abstracted composite case (20260914-094512-84fb shape, no
    domain-specific terms): a request mixing independently deliverable
    concerns — comparison semantics + engine + operationalization."""
    pi = FakePiAdapter(script={"scope_guard": [scope_guard_json("DECOMPOSITION_REQUIRED")]})
    return make_orchestrator(
        repo,
        pi=pi,
        ui=ScriptedUI(interactive=False),
    )


def test_decomposition_required_stops_before_design(repo):
    o = make_composite(repo)
    code = o.run()
    assert code == int(ExitCode.HUMAN_HANDOFF)
    assert o.state.phase == Phase.HUMAN_HANDOFF
    assert o.state.status == SessionStatus.HUMAN_HANDOFF
    assert o.state.result_status == "DECOMPOSITION_REQUIRED"
    assert o.state.scope_verdict == "DECOMPOSITION_REQUIRED"
    # Hard invariant: no design/review budget was spent.
    assert o.state.round == 0
    assert o.state.budgets.revision_used == 0
    assert o.state.budgets.focused_revision_used == 0
    assert o.state.budgets.ablation_used == 0
    assert o.state.budgets.human_interruptions_used == 0
    events = [e["event"] for e in events_of(o)]
    assert "SCOPE_GUARD_STOPPED" in events
    assert "DESIGN_STARTED" not in events
    assert "INITIAL_REVIEW_STARTED" not in events
    # No design artifacts exist.
    assert not (o.store.dir / "proposal.md").exists()
    assert not (o.store.dir / "proposal.json").exists()


def test_decomposition_required_renders_actionable_split(repo):
    o = make_composite(repo)
    o.run()
    result = o.store.read_text("session-result.md")
    assert result
    assert "DECOMPOSITION_REQUIRED" in result
    assert "## Decomposition Proposal" in result
    # Every child session is actionable: goal + inputs + non-goals + deps.
    assert "Comparison Contract" in result
    assert "Comparison Engine" in result
    assert "Operationalization" in result
    assert "goal: settle the comparison semantics" in result
    assert "depends on:" in result
    assert "NOT executed automatically" in result
    # scope-assessment.md carries the same projection.
    assessment = o.store.read_text("scope-assessment.md")
    assert "DECOMPOSITION_REQUIRED" in assessment
    assert "### Session A" in assessment


# --- OUT_OF_SCOPE early termination ---------------------------------------------


def test_out_of_scope_stops_with_unsupported_reason(repo):
    pi = FakePiAdapter(script={"scope_guard": [scope_guard_json("OUT_OF_SCOPE")]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(interactive=False))
    code = o.run()
    assert code == int(ExitCode.HUMAN_HANDOFF)
    assert o.state.result_status == "OUT_OF_SCOPE"
    result = o.store.read_text("session-result.md")
    assert "OUT_OF_SCOPE" in result
    assert "outside the supported product scope" in result
    events = [e["event"] for e in events_of(o)]
    assert "DESIGN_STARTED" not in events


# --- assessment model + scope control principle ---------------------------------


def test_decomposition_requires_at_least_two_children(repo):
    """A single child session is not a decomposition: the malformed
    assessment fails protocol validation (initial + repair both invalid
    -> retries exhausted -> FAILED)."""
    bad = scope_guard_json(
        "DECOMPOSITION_REQUIRED",
        decomposition=[
            {"title": "Only one", "goal": "not a decomposition", "inputs": [], "non_goals": [], "dependencies": []}
        ],
    )
    pi = FakePiAdapter(
        script={"scope_guard": [bad], "scope_guard:repair": [bad]}
    )
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.FAILED)
    assert o.state.phase == Phase.FAILED
    assert o.state.result_status == "FAILED"


def test_scope_verdict_unknown_value_fails_closed(repo):
    bad = json.dumps({"verdict": "MAYBE", "rationale": "x"})
    pi = FakePiAdapter(
        script={"scope_guard": [bad], "scope_guard:repair": [bad]}
    )
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.FAILED)
    assert o.state.result_status == "FAILED"


def test_conservative_classification_records_uncertainty(repo):
    """§54: classification depending on a Requirement ambiguity must not
    guess — the verdict is chosen conservatively and the uncertainty is
    recorded and rendered."""
    pi = FakePiAdapter(
        script={
            "scope_guard": [
                scope_guard_json(
                    "BOUNDED",
                    uncertainty=(
                        "whether reporting output is in-domain for this session "
                        "depends on an unresolved Requirement ambiguity"
                    ),
                )
            ]
        }
    )
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.DONE)
    completed = next(e for e in events_of(o) if e["event"] == "SCOPE_GUARD_COMPLETED")
    assert completed["uncertainty"]
    assessment = o.store.read_text("scope-assessment.md")
    assert "Classification Uncertainty" in assessment


def test_state_machine_scope_guard_edges():
    assert Phase.SCOPE_GUARD in ALLOWED_TRANSITIONS[Phase.DISCOVER]
    assert ALLOWED_TRANSITIONS[Phase.DISCOVER] == {Phase.SCOPE_GUARD}
    assert Phase.INTAKE in ALLOWED_TRANSITIONS[Phase.SCOPE_GUARD]
    assert Phase.INVESTIGATE in ALLOWED_TRANSITIONS[Phase.SCOPE_GUARD]
    assert Phase.HUMAN_HANDOFF in ALLOWED_TRANSITIONS[Phase.SCOPE_GUARD]
    assert not can_transition(Phase.SCOPE_GUARD, Phase.DESIGN)


def test_scope_guard_runs_after_discover_before_any_gate(repo):
    """The guard sits between DISCOVER and INTAKE even when candidates
    exist — no gate or design happens before the scope verdict."""
    pi = FakePiAdapter(
        script={
            "discover": [discovery_with_candidates([candidate()])],
            "scope_guard": [scope_guard_json("DECOMPOSITION_REQUIRED")],
        }
    )
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.HUMAN_HANDOFF)
    events = [e["event"] for e in events_of(o)]
    assert events.index("SCOPE_GUARD_COMPLETED") < events.index("SCOPE_GUARD_STOPPED")
    assert "HUMAN_GATE_CREATED" not in events
