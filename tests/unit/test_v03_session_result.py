"""V0.3 C1 — Terminal Result Contract + telemetry (design §14–§23, §56, §59).

100% of terminal sessions generate session-result.md; internal state
and user-facing classification stay separate; the renderer is
deterministic from persisted artifacts with a mandatory fallback.
"""

from __future__ import annotations

import json

from agent_review.agents.fakes import FakePiAdapter, FakeCodexAdapter, make_blocking_issue
from agent_review.config import Config
from agent_review.models import ExitCode, Phase, SessionStatus
from agent_review.orchestrator import Orchestrator

from tests.unit.test_m3_human_gate import (
    ScriptedUI,
    candidate,
    discovery_with_candidates,
    make_orchestrator,
)


def events_of(o) -> list[dict]:
    return [
        json.loads(line)
        for line in (o.store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]


# --- APPROVED ----------------------------------------------------------------------


def test_approved_result_written_on_done(repo):
    o = make_orchestrator(repo, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.DONE)
    assert o.state.result_status == "APPROVED"
    result = o.store.read_text("session-result.md")
    assert result
    assert "**APPROVED**" in result
    assert "## Implementation Readiness" in result
    assert "**READY**" in result
    assert "## Frozen Human Decisions" not in result or "human-defined" not in result
    assert (o.store.dir / "telemetry.json").is_file()
    events = [e["event"] for e in events_of(o)]
    assert "SESSION_RESULT_WRITTEN" in events
    assert "TELEMETRY_WRITTEN" in events


def test_approved_with_decisions_lists_frozen_decisions(repo):
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates([candidate()])]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(answers=["1"]))
    assert o.run() == int(ExitCode.DONE)
    result = o.store.read_text("session-result.md")
    assert "## Frozen Human Decisions" in result
    assert "cooperative" in result


# --- DESIGN_NOT_APPROVED -------------------------------------------------------------


def design_not_approved_flow(repo):
    codex = FakeCodexAdapter(
        script={
            "initial_review": [
                json.dumps({"issues": [make_blocking_issue(1).model_dump()], "summary": "b"})
            ],
            "closure_review": [
                json.dumps(
                    {
                        "issue_outcomes": [
                            {
                                "issue_id": "R001",
                                "resolution": "UNRESOLVED",
                                "note": "close condition unchanged",
                                "correction_action": "FULL_REVISION",
                                "material_progress": "NO_PROGRESS",
                            }
                        ],
                        "new_issues": [],
                        "summary": "no",
                    }
                )
            ],
        }
    )
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    return o, o.run()


def test_design_not_approved_result_sections(repo):
    o, code = design_not_approved_flow(repo)
    assert code == int(ExitCode.HUMAN_HANDOFF)
    # §56: internal state and user-facing classification are separate.
    assert o.state.phase == Phase.HUMAN_HANDOFF
    assert o.state.status == SessionStatus.HUMAN_HANDOFF
    assert o.state.result_status == "DESIGN_NOT_APPROVED"
    result = o.store.read_text("session-result.md")
    assert "**DESIGN_NOT_APPROVED**" in result
    assert "internal state: HUMAN_HANDOFF" in result
    assert "## Remaining Blocking Issues" in result
    assert "close conditions:" in result
    assert "**NOT_READY**" in result
    assert "## Recommended Next Action" in result
    assert "engineering gaps" in result
    # The reviewer recommendation is surfaced for the follow-up session.
    assert "FULL_REVISION" in result


# --- NEEDS_HUMAN_DECISION --------------------------------------------------------------


def needs_human_flow(repo):
    """Interruption budget exhausted with unresolved decisions ->
    NEEDS_HUMAN_DECISION (genuine Human authority outstanding)."""
    candidates = [candidate(question=f"Q{i}?") for i in range(1, 14)]
    pi = FakePiAdapter(script={"discover": [discovery_with_candidates(candidates)]})
    ui = ScriptedUI(answers=["1"] * 12)
    o = make_orchestrator(repo, pi=pi, ui=ui)
    return o, o.run()


def test_needs_human_decision_result(repo):
    o, code = needs_human_flow(repo)
    assert code == int(ExitCode.HUMAN_HANDOFF)
    assert o.state.result_status == "NEEDS_HUMAN_DECISION"
    result = o.store.read_text("session-result.md")
    assert "**NEEDS_HUMAN_DECISION**" in result
    assert "Requirement/Fact decision is genuinely required" in result


# --- DECOMPOSITION_REQUIRED / OUT_OF_SCOPE: see test_v03_scope_guard.py ----------------


# --- FAILED fallback ---------------------------------------------------------------------


def test_failed_result_written_with_minimal_fallback(repo, monkeypatch):
    """Protocol failure -> FAILED result; a rich-renderer crash falls
    back to the deterministic minimal result (design §23)."""
    from agent_review import rendering

    def boom(*args, **kwargs):
        raise RuntimeError("renderer exploded")

    monkeypatch.setattr(rendering, "render_session_result", boom)
    bad = json.dumps({"issues": "not-a-list"})
    codex = FakeCodexAdapter(
        script={"initial_review": [bad], "initial_review:repair": [bad]}
    )
    o = make_orchestrator(repo, codex=codex, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.FAILED)
    assert o.state.result_status == "FAILED"
    minimal = o.store.read_text("session-result.md")
    assert minimal
    assert "FAILED" in minimal
    events = events_of(o)
    written = [e for e in events if e["event"] == "SESSION_RESULT_WRITTEN"]
    assert written and written[-1].get("fallback") == "minimal"
    # The terminal state is never masked by the rendering failure.
    assert o.state.phase == Phase.FAILED


def test_failed_result_on_agent_error(repo):
    from agent_review.agents.base import AgentError

    pi = FakePiAdapter(script={"discover": [AgentError("pi missing")]})
    o = make_orchestrator(repo, pi=pi, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.FAILED)
    result = o.store.read_text("session-result.md")
    assert "FAILED" in result


# --- telemetry (§59) -----------------------------------------------------------------------


def test_telemetry_fields(repo):
    o, code = design_not_approved_flow(repo)
    assert code == int(ExitCode.HUMAN_HANDOFF)
    telemetry = json.loads((o.store.dir / "telemetry.json").read_text(encoding="utf-8"))
    assert telemetry["scope_verdict"] == "BOUNDED"
    assert telemetry["initial_blocker_count"] == 1
    assert telemetry["closure_new_blocker_count"] == 0
    assert telemetry["final_new_blocker_count"] == 0
    assert telemetry["full_revision_count"] == 1
    assert telemetry["focused_revision_count"] == 0
    assert telemetry["ablation_count"] == 0
    assert telemetry["no_material_progress_stop_count"] == 1
    assert telemetry["terminal_result_status"] == "DESIGN_NOT_APPROVED"
    assert telemetry["session_result_generated"] is True
    assert telemetry["human_interruptions"] == 0
    assert telemetry["scope_guard_duration_seconds"] is not None
    assert telemetry["total_elapsed_seconds"] is not None


def test_telemetry_decomposition_counts(repo):
    from tests.unit.test_v03_scope_guard import make_composite

    o = make_composite(repo)
    o.run()
    telemetry = json.loads((o.store.dir / "telemetry.json").read_text(encoding="utf-8"))
    assert telemetry["scope_verdict"] == "DECOMPOSITION_REQUIRED"
    assert telemetry["decomposition_count"] == 3
    assert telemetry["initial_blocker_count"] == 0


# --- CLI --------------------------------------------------------------------------------------


def test_show_result_cli(repo):
    from typer.testing import CliRunner

    from agent_review.cli import app

    runner = CliRunner()
    o = make_orchestrator(repo, ui=ScriptedUI(interactive=False))
    assert o.run() == int(ExitCode.DONE)
    result = runner.invoke(
        app, ["show", "result", "--repo", str(repo)]
    )
    assert result.exit_code == 0
    assert "APPROVED" in result.output


def test_status_shows_result_and_focused_budget(repo):
    from typer.testing import CliRunner

    from agent_review.cli import app

    runner = CliRunner()
    o, code = design_not_approved_flow(repo)
    assert code == int(ExitCode.HUMAN_HANDOFF)
    result = runner.invoke(app, ["status", "--repo", str(repo)])
    assert result.exit_code == 0
    assert "result:         DESIGN_NOT_APPROVED" in result.output
    assert "focused revision 0/1" in result.output
