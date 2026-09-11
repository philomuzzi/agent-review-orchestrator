"""V0.1 runtime progress visibility: renderer levels, events, heartbeat."""

from __future__ import annotations

import io
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_review.agents.fakes import FakeCodexAdapter, FakePiAdapter, make_blocking_issue
from agent_review.config import Config
from agent_review.models import ExitCode, Phase
from agent_review.orchestrator import Orchestrator
from agent_review.progress import (
    PLACEHOLDER_TITLE,
    OutputLevel,
    ProgressRenderer,
    display_title,
    format_elapsed,
)

T0 = datetime(2026, 9, 10, 10, 36, 38, tzinfo=timezone.utc)


def ev(name: str, at: float = 0.0, **data) -> dict:
    return {"event": name, "ts": (T0 + timedelta(seconds=at)).isoformat(), **data}


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


def test_format_elapsed():
    assert format_elapsed(0) == "[00:00]"
    assert format_elapsed(65) == "[01:05]"
    assert format_elapsed(3671) == "[1:01:11]"
    assert format_elapsed(-5) == "[00:00]"


def test_display_title_placeholder():
    class S:
        task_title = None

    assert display_title(S()) == PLACEHOLDER_TITLE
    S.task_title = "  同步任务暂停能力 "
    assert display_title(S()) == "同步任务暂停能力"


# ---------------------------------------------------------------------------
# default level rendering
# ---------------------------------------------------------------------------


def render_all(level: OutputLevel, events: list[dict]) -> str:
    out = io.StringIO()
    renderer = ProgressRenderer(level=level, stream=out, heartbeat_interval=0)
    renderer._session_start = T0
    for event in events:
        renderer.handle(event)
    return out.getvalue()


def test_default_level_renders_phase_lifecycle():
    text = render_all(
        OutputLevel.DEFAULT,
        [
            ev("PHASE_STARTED", 0, phase="DISCOVER"),
            ev("AGENT_CALL_STARTED", 0, phase="DISCOVER", agent="pi", action="discover"),
            ev("AGENT_CALL_COMPLETED", 18, phase="DISCOVER", agent="pi", action="discover", seconds=18.2),
            ev("DISCOVER_COMPLETED", 18, task_kind="CHANGE", components=6),
        ],
    )
    assert "→ DISCOVER" in text
    assert "Pi inspecting repository..." in text
    assert "✓ DISCOVER · 6 relevant components · CHANGE" in text
    assert "[00:18]" in text


def test_default_level_review_counts_and_done():
    text = render_all(
        OutputLevel.DEFAULT,
        [
            ev("PHASE_STARTED", 0, phase="INITIAL_REVIEW"),
            ev("AGENT_CALL_STARTED", 0, phase="INITIAL_REVIEW", agent="codex", action="initial_review"),
            ev("ISSUES_INGESTED", 5, provenance="INITIAL_REVIEW", total=3, blocking=2, non_blocking=1, issue_ids=["R001", "R002", "R003"]),
            ev("INITIAL_REVIEW_COMPLETED", 28, issues=3, blocking=2, non_blocking=1, issue_ids=["R001", "R002", "R003"]),
            ev("PHASE_STARTED", 60, phase="FINALIZE"),
            ev("FINAL_MD_WRITTEN", 61),
            ev("SESSION_DONE", 61),
        ],
    )
    assert "→ INITIAL_REVIEW" in text
    assert "Codex reviewing proposal..." in text
    assert "✓ INITIAL_REVIEW · 2 blocking · 1 non-blocking" in text
    assert "✓ DONE · final.md generated" in text
    # Raw agent output must never appear (nothing streams reasoning here).
    assert "R001" not in text  # issue ids are verbose-only


def test_default_level_human_gate_and_retry():
    text = render_all(
        OutputLevel.DEFAULT,
        [
            ev("HUMAN_GATE_CREATED", 20, gate_id="HG001", questions=["Q1", "Q2"]),
            ev("HUMAN_GATE_WAITING_NONINTERACTIVE", 21, gate_id="HG001"),
            ev("PROTOCOL_RETRY", 40, agent="codex", phase="CLOSURE_REVIEW", next_attempt=2, schema="ClosureReviewResult"),
            ev("PROTOCOL_RETRY_EXHAUSTED", 70, agent="codex", phase="CLOSURE_REVIEW", attempts=2),
            ev("SESSION_FAILED", 70, reason="protocol failure"),
        ],
    )
    assert "! HUMAN GATE · 2 decision(s) required" in text
    assert "non-interactive" in text
    assert "↻ PROTOCOL RETRY · CLOSURE_REVIEW" in text
    assert "attempt 2" in text
    assert "✗ FAILED · protocol failure" in text


def test_default_level_heartbeat_line():
    text = render_all(
        OutputLevel.DEFAULT,
        [
            ev("PHASE_STARTED", 0, phase="DESIGN"),
            ev("AGENT_CALL_STARTED", 0, phase="DESIGN", agent="pi", action="design"),
            ev("AGENT_CALL_HEARTBEAT", 19, phase="DESIGN", agent="pi", action="design", seconds=19.0),
            ev("AGENT_CALL_HEARTBEAT", 34, phase="DESIGN", agent="pi", action="design", seconds=34.0),
        ],
    )
    assert "DESIGN · Pi still working... 19s" in text
    assert "DESIGN · Pi still working... 34s" in text


def test_task_revision_and_handoff_visible():
    text = render_all(
        OutputLevel.DEFAULT,
        [
            ev("TASK_REVISION_INCREMENTED", 30, task_revision=2, reason="human decisions"),
            ev("SESSION_HUMAN_HANDOFF", 90, reason="convergence budget exhausted"),
            ev("SESSION_INTERRUPTED", 10, phase="DESIGN"),
        ],
    )
    assert "task revision 2" in text
    assert "! HUMAN_HANDOFF · convergence budget exhausted" in text
    assert "INTERRUPTED during DESIGN" in text


def test_verbose_level_adds_artifacts_and_issue_ids():
    text = render_all(
        OutputLevel.VERBOSE,
        [
            ev("PHASE_STARTED", 0, phase="INITIAL_REVIEW"),
            ev("ISSUE_CREATED", 5, issue_id="R001", severity="BLOCKING", category="DESIGN", provenance="INITIAL_REVIEW"),
            ev("ISSUES_INGESTED", 6, provenance="INITIAL_REVIEW", total=1, blocking=1, non_blocking=0, issue_ids=["R001"]),
            ev("INITIAL_REVIEW_COMPLETED", 8, issues=1, blocking=1, non_blocking=0, issue_ids=["R001"]),
            ev("PROPOSAL_CREATED", 30, based_on_task_revision=1),
            ev("AGENT_CALL_COMPLETED", 31, phase="DESIGN", agent="pi", action="design", seconds=25.0),
            ev("PASS_COMPUTED", 32, passed=True, reasons=[]),
        ],
    )
    assert "issue R001: BLOCKING DESIGN" in text
    assert "issues ingested (INITIAL_REVIEW): 1 blocking, 0 non-blocking [R001]" in text
    assert "proposal.md" in text
    assert "based on task revision 1" in text
    assert "Pi call finished (25.0s)" in text
    assert "PASS_COMPUTED" in text  # verbose fallback dumps state events


def test_quiet_level_shows_only_gates_errors_result():
    text = render_all(
        OutputLevel.QUIET,
        [
            ev("PHASE_STARTED", 0, phase="DISCOVER"),
            ev("AGENT_CALL_STARTED", 0, phase="DISCOVER", agent="pi", action="discover"),
            ev("AGENT_CALL_HEARTBEAT", 19, phase="DISCOVER", agent="pi", action="discover", seconds=19.0),
            ev("DISCOVER_COMPLETED", 20, task_kind="CHANGE", components=6),
            ev("HUMAN_GATE_CREATED", 25, gate_id="HG001", questions=["Q1"]),
            ev("SESSION_DONE", 60),
            ev("SESSION_FAILED", 61, reason="x"),
            ev("SESSION_HUMAN_HANDOFF", 62, reason="y"),
            ev("SESSION_INTERRUPTED", 63, phase="DESIGN"),
        ],
    )
    assert "! HUMAN GATE" in text
    assert "✓ DONE" in text
    assert "✗ FAILED" in text
    assert "HUMAN_HANDOFF" in text
    assert "INTERRUPTED" in text
    # Everything else is suppressed.
    assert "DISCOVER" not in text
    assert "Pi" not in text
    assert "still working" not in text


def test_banner_contains_session_and_title():
    out = io.StringIO()
    renderer = ProgressRenderer(stream=out, heartbeat_interval=0)

    class S:
        session_id = "20260910-103638-a7f3"
        repository = "C:/repo"
        task_title = "全局任务并行执行能力"
        task_kind = type("K", (), {"value": "CHANGE"})()
        created_at = T0

    renderer.banner(S())
    text = out.getvalue()
    assert "Agent Review" in text
    assert "Session: 20260910-103638-a7f3" in text
    assert "Task:    全局任务并行执行能力" in text
    assert "Mode:    CHANGE" in text


def test_banner_suppressed_in_quiet():
    out = io.StringIO()
    renderer = ProgressRenderer(level=OutputLevel.QUIET, stream=out)
    renderer.banner(type("S", (), {"session_id": "x", "repository": "r", "task_title": None, "task_kind": type("K", (), {"value": "CHANGE"})(), "created_at": T0})())
    assert out.getvalue() == ""


# ---------------------------------------------------------------------------
# orchestrator integration: events + heartbeats with fake adapters
# ---------------------------------------------------------------------------


class CapturingUI:
    def __init__(self):
        self.interactive = False
        self.echoes: list[str] = []

    def is_interactive(self) -> bool:
        return self.interactive

    def echo(self, text: str) -> None:
        self.echoes.append(text)

    def ask(self, prompt: str) -> str:  # pragma: no cover
        return ""


def run_with_renderer(repo: Path, request: str, renderer, pi=None, codex=None, ui=None):
    return Orchestrator.create(
        repository=repo,
        request=request,
        config=Config(),
        pi=pi or FakePiAdapter(),
        codex=codex or FakeCodexAdapter(),
        ui=ui or CapturingUI(),
        renderer=renderer,
    )


def test_events_jsonl_contains_agent_call_events(repo):
    out = io.StringIO()
    renderer = ProgressRenderer(stream=out, heartbeat_interval=0)
    o = run_with_renderer(repo, "add retry counter", renderer)
    assert o.run() == int(ExitCode.DONE)

    events = [
        json.loads(line)
        for line in (o.store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    names = [e["event"] for e in events]
    assert "AGENT_CALL_STARTED" in names
    assert "AGENT_CALL_COMPLETED" in names
    started = next(e for e in events if e["event"] == "AGENT_CALL_STARTED")
    assert started["phase"] == "DISCOVER" and started["agent"] == "pi"
    completed = [e for e in events if e["event"] == "AGENT_CALL_COMPLETED"]
    assert all("seconds" in e for e in completed)
    # One agent-call pair per agent phase.
    phases = {(e["phase"], e["agent"]) for e in completed}
    assert ("DISCOVER", "pi") in phases
    assert ("DESIGN", "pi") in phases
    assert ("INITIAL_REVIEW", "codex") in phases


def test_issues_ingested_event_carries_counts(repo):
    pi = FakePiAdapter()
    codex = FakeCodexAdapter(
        script={
            "initial_review": [
                json.dumps(
                    {
                        "issues": [make_blocking_issue(1).model_dump()],
                        "summary": "one blocker",
                    }
                )
            ],
            # closure: verify the addressed blocker resolved
            "closure_review": [
                json.dumps(
                    {
                        "issue_outcomes": [{"issue_id": "R001", "resolution": "RESOLVED", "note": "ok"}],
                        "new_issues": [],
                        "summary": "verified",
                    }
                )
            ],
        }
    )
    out = io.StringIO()
    renderer = ProgressRenderer(stream=out, heartbeat_interval=0)
    o = run_with_renderer(repo, "needs revision", renderer, pi=pi, codex=codex)
    assert o.run() == int(ExitCode.DONE)

    events = [
        json.loads(line)
        for line in (o.store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    ingested = next(e for e in events if e["event"] == "ISSUES_INGESTED")
    assert ingested["blocking"] == 1 and ingested["non_blocking"] == 0
    assert ingested["issue_ids"] == ["R001"]
    initial_done = next(e for e in events if e["event"] == "INITIAL_REVIEW_COMPLETED")
    assert initial_done["blocking"] == 1
    closure_done = next(e for e in events if e["event"] == "CLOSURE_REVIEW_COMPLETED")
    assert closure_done["resolved"] == 1
    # default output shows counts and revision path
    text = out.getvalue()
    assert "✓ INITIAL_REVIEW · 1 blocking · 0 non-blocking" in text
    assert "1 of 1 blocker(s) verified resolved" in text


def test_protocol_retry_event_and_visibility(repo):
    codex = FakeCodexAdapter(
        script={
            "initial_review": ["this is not json"],
            "initial_review:repair": [
                json.dumps({"issues": [], "summary": "repaired"})
            ],
        }
    )
    out = io.StringIO()
    renderer = ProgressRenderer(stream=out, heartbeat_interval=0)
    o = run_with_renderer(repo, "protocol retry case", renderer, codex=codex)
    assert o.run() == int(ExitCode.DONE)

    events = [
        json.loads(line)
        for line in (o.store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    retries = [e for e in events if e["event"] == "PROTOCOL_RETRY"]
    assert len(retries) == 1
    assert retries[0]["agent"] == "codex"
    assert retries[0]["next_attempt"] == 2
    succeeded = [e for e in events if e["event"] == "PROTOCOL_RETRY_SUCCEEDED"]
    assert len(succeeded) == 1
    text = out.getvalue()
    assert "↻ PROTOCOL RETRY · INITIAL_REVIEW" in text
    assert "attempt 2" in text


class SlowFakePi(FakePiAdapter):
    def __init__(self, delay: float):
        super().__init__()
        self.delay = delay

    def discover(self, state):
        time.sleep(self.delay)
        return super().discover(state)


def test_heartbeat_during_long_agent_call(repo):
    out = io.StringIO()
    renderer = ProgressRenderer(stream=out, heartbeat_interval=0.05)
    o = run_with_renderer(
        repo, "slow discovery", renderer, pi=SlowFakePi(0.3)
    )
    assert o.run() == int(ExitCode.DONE)

    events = [
        json.loads(line)
        for line in (o.store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    beats = [e for e in events if e["event"] == "AGENT_CALL_HEARTBEAT"]
    assert beats, "expected at least one heartbeat during the 0.3s call"
    assert all(e["phase"] == "DISCOVER" and e["agent"] == "pi" for e in beats)
    assert any(e["seconds"] >= 0.05 for e in beats)
    text = out.getvalue()
    assert "DISCOVER · Pi still working..." in text
    # The call still completes after heartbeats (not mistaken for EOF).
    assert "✓ DONE · final.md generated" in text


def test_failed_agent_call_is_visible(repo):
    from agent_review.agents.base import CapabilityError

    pi = FakePiAdapter(script={"discover": [CapabilityError("pi binary not found")]})
    out = io.StringIO()
    renderer = ProgressRenderer(stream=out, heartbeat_interval=0)
    o = run_with_renderer(repo, "will fail", renderer, pi=pi)
    assert o.run() == int(ExitCode.FAILED)
    text = out.getvalue()
    assert "✗ FAILED" in text


def test_interrupted_renders_and_resumes_with_progress(repo):
    ui = CapturingUI()

    class InterruptingPi(FakePiAdapter):
        def discover(self, state):
            raise KeyboardInterrupt

    out = io.StringIO()
    renderer = ProgressRenderer(stream=out, heartbeat_interval=0)
    o = Orchestrator.create(
        repository=repo,
        request="interrupt me",
        config=Config(),
        pi=InterruptingPi(),
        codex=FakeCodexAdapter(),
        ui=ui,
        renderer=renderer,
    )
    assert o.run() == int(ExitCode.INTERRUPTED)
    assert "INTERRUPTED during DISCOVER" in out.getvalue()

    # Resume with a working adapter; progress continues on the same clock.
    out2 = io.StringIO()
    renderer2 = ProgressRenderer(stream=out2, heartbeat_interval=0)
    o2 = Orchestrator.resume(
        repository=repo,
        session_id=o.state.session_id,
        config=Config(),
        pi=FakePiAdapter(),
        codex=FakeCodexAdapter(),
        ui=CapturingUI(),
        renderer=renderer2,
    )
    assert o2.run() == int(ExitCode.DONE)
    text = out2.getvalue()
    assert "resuming at DISCOVER" in text
    assert "✓ DONE · final.md generated" in text
