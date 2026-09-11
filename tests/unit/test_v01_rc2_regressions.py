"""V0.1-RC2 regressions: presentation sanitization, renderer line-safety,
corrupt-session lookup resilience, session-id collision format, CLI
convenience commands. Each test fails on the RC1 defect it pins.
"""

from __future__ import annotations

import io
import json
import re
from datetime import datetime, timedelta, timezone

from typer.testing import CliRunner

from agent_review.agents.fakes import FakeCodexAdapter, FakePiAdapter, make_blocking_issue
from agent_review.cli import app, main as cli_main
from agent_review.config import Config
from agent_review.models import ExitCode
from agent_review.orchestrator import Orchestrator
from agent_review.progress import (
    MAX_TITLE_LENGTH,
    PLACEHOLDER_TITLE,
    OutputLevel,
    ProgressRenderer,
    sanitize_title,
)
from agent_review.storage import StateStore

runner = CliRunner()

T0 = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)


def ev(name: str, at: float = 0.0, **data) -> dict:
    return {"event": name, "ts": (T0 + timedelta(seconds=at)).isoformat(), **data}


class NonInteractiveUI:
    def is_interactive(self) -> bool:
        return False

    def echo(self, text: str) -> None:
        pass

    def ask(self, prompt: str) -> str:  # pragma: no cover
        return ""


# ---------------------------------------------------------------------------
# B001: agent/user-supplied titles are host-sanitized before persistence
# ---------------------------------------------------------------------------


def test_sanitize_title_collapses_and_bounds():
    assert sanitize_title("  a\nb\tc  ") == "a b c"
    # Control characters act as separators (never survive into the title).
    assert sanitize_title("标题\x00\x1f去控\t制符") == "标题 去控 制符"
    assert sanitize_title("标题去控制符") == "标题去控制符"
    assert sanitize_title("长" * 300) == "长" * MAX_TITLE_LENGTH
    assert len(sanitize_title("长" * 300)) == MAX_TITLE_LENGTH
    assert sanitize_title("全局任务并行执行能力") == "全局任务并行执行能力"
    assert sanitize_title("") == ""
    assert sanitize_title(None) == ""
    assert sanitize_title(" \n\t ") == ""


def test_discover_title_sanitized_before_persist(repo):
    evil = "标题第一行\n标题第二行\t带制表 " + "长" * 300
    pi = FakePiAdapter(
        script={
            "discover": [
                json.dumps(
                    {
                        "task_title": evil,
                        "task_kind": "CHANGE",
                        "current_state": "s",
                        "relevant_components": ["src/"],
                        "existing_constraints": [],
                        "change_surface": [],
                        "unknowns": [],
                        "human_candidates": [],
                    }
                )
            ]
        }
    )
    o = Orchestrator.create(
        repository=repo,
        request="evil title request",
        config=Config(),
        pi=pi,
        codex=FakeCodexAdapter(),
        ui=NonInteractiveUI(),
    )
    assert o.run() == int(ExitCode.DONE)
    state = StateStore.load_state_of(repo, o.state.session_id)
    assert state.task_title == sanitize_title(evil)
    assert "\n" not in state.task_title
    assert "\t" not in state.task_title
    assert len(state.task_title) == MAX_TITLE_LENGTH
    events = [
        json.loads(line)
        for line in (o.store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    title_events = [e for e in events if e["event"] == "TASK_TITLE_SET"]
    assert len(title_events) == 1
    assert title_events[0]["title"] == state.task_title


def test_user_name_sanitized(repo):
    o = Orchestrator.create(
        repository=repo,
        request="named request",
        config=Config(),
        pi=FakePiAdapter(),
        codex=FakeCodexAdapter(),
        ui=NonInteractiveUI(),
        name="名字甲\n名字乙\t丙",
    )
    assert o.run() == int(ExitCode.DONE)
    state = StateStore.load_state_of(repo, o.state.session_id)
    assert state.task_title == "名字甲 名字乙 丙"
    assert state.task_title_source == "user"


def test_display_title_sanitizes_hostile_legacy_state(repo):
    class Legacy:
        task_title = "行一\n行二"

    from agent_review.progress import display_title

    assert display_title(Legacy()) == "行一 行二"
    assert "\n" not in display_title(Legacy())


def test_status_list_rows_stay_single_line_with_evil_title(repo):
    pi = FakePiAdapter(
        script={
            "discover": [
                json.dumps(
                    {
                        "task_title": "行甲\n行乙",
                        "task_kind": "CHANGE",
                        "current_state": "s",
                        "relevant_components": ["src/"],
                        "existing_constraints": [],
                        "change_surface": [],
                        "unknowns": [],
                        "human_candidates": [],
                    }
                )
            ]
        }
    )
    o = Orchestrator.create(
        repository=repo,
        request="row injection probe",
        config=Config(),
        pi=pi,
        codex=FakeCodexAdapter(),
        ui=NonInteractiveUI(),
    )
    assert o.run() == int(ExitCode.DONE)
    listing = runner.invoke(app, ["status", "--repo", str(repo), "--list"])
    assert listing.exit_code == 0
    lines = listing.output.splitlines()
    rows = [l for l in lines if re.match(r"\d{8}-\d{6}-[0-9a-f]{4}", l)]
    assert len(rows) == 1
    assert "行甲 行乙" in rows[0]
    # No injected stand-alone line from the title payload.
    assert "行乙" not in [l.strip() for l in lines if l not in rows]
    # Header block stays one line per field.
    status = runner.invoke(app, ["status", "--repo", str(repo)])
    task_lines = [l for l in status.output.splitlines() if l.startswith("Task:")]
    assert len(task_lines) == 1
    assert "行甲 行乙" in task_lines[0]


# ---------------------------------------------------------------------------
# B002: renderer line-safety (one line per event, any payload)
# ---------------------------------------------------------------------------


def render_all(level: OutputLevel, events: list[dict]) -> str:
    out = io.StringIO()
    renderer = ProgressRenderer(level=level, stream=out, heartbeat_interval=0)
    renderer._session_start = T0
    for event in events:
        renderer.handle(event)
    return out.getvalue()


def test_session_failed_reason_collapsed_to_one_line():
    text = render_all(
        OutputLevel.DEFAULT,
        [
            ev(
                "SESSION_FAILED",
                reason="codex exec failed (rc=1)\nstderr line A\nstderr line B",
            )
        ],
    )
    lines = [l for l in text.splitlines() if l.strip()]
    assert len(lines) == 1
    assert "stderr line A stderr line B" in lines[0]


def test_handoff_and_agent_failure_reasons_collapsed():
    text = render_all(
        OutputLevel.DEFAULT,
        [
            ev("SESSION_HUMAN_HANDOFF", reason="a\nb"),
            ev("AGENT_CALL_FAILED", agent="pi", phase="DESIGN", error="X\nY", seconds=1.0),
            ev("TASK_TITLE_SET", source="discover", title="t1\nt2"),
        ],
    )
    lines = [l for l in text.splitlines() if l.strip()]
    assert len(lines) == 3
    assert all("\n" not in l for l in lines)
    assert "a b" in lines[0]
    assert "X Y" in lines[1]
    assert "t1 t2" in lines[2]


def test_quiet_failed_reason_single_line():
    text = render_all(
        OutputLevel.QUIET,
        [ev("SESSION_FAILED", reason="r1\nr2\nr3")],
    )
    lines = [l for l in text.splitlines() if l.strip()]
    assert len(lines) == 1
    assert "r1 r2 r3" in lines[0]


def test_verbose_fallback_collapses_newlines():
    text = render_all(
        OutputLevel.VERBOSE,
        [ev("PASS_COMPUTED", passed=False, reasons=["a\nb"])],
    )
    lines = [l for l in text.splitlines() if l.strip()]
    assert len(lines) == 1
    assert "a b" in lines[0]


# ---------------------------------------------------------------------------
# B003: corrupt session state degrades cleanly across lookup paths
# ---------------------------------------------------------------------------


def _make_sessions(repo):
    """One DONE session, then one corrupt session on top of it."""
    o = Orchestrator.create(
        repository=repo,
        request="good request",
        config=Config(),
        pi=FakePiAdapter(),
        codex=FakeCodexAdapter(),
        ui=NonInteractiveUI(),
    )
    assert o.run() == int(ExitCode.DONE)
    bad = StateStore.create_session(repo, "corrupt me")
    (bad.dir / "state.json").write_text("{ this is not json", encoding="utf-8")
    return o.state.session_id, bad.session_id


def test_status_list_survives_corrupt_session(repo):
    good, bad = _make_sessions(repo)
    listing = runner.invoke(app, ["status", "--repo", str(repo), "--list"])
    assert listing.exit_code == 0
    assert bad in listing.output
    assert "(corrupt state)" in listing.output
    assert good in listing.output


def test_status_on_corrupt_session_fails_closed(repo):
    _good, bad = _make_sessions(repo)
    result = runner.invoke(app, ["status", bad, "--repo", str(repo)])
    assert result.exit_code == int(ExitCode.FAILED)
    assert "Corrupt session state" in result.output


def test_show_on_corrupt_session_fails_closed(repo):
    _good, bad = _make_sessions(repo)
    result = runner.invoke(app, ["show", "final", bad, "--repo", str(repo)])
    assert result.exit_code == int(ExitCode.FAILED)
    assert "Traceback" not in result.output


def test_resume_on_corrupt_session_fails_closed(repo):
    _good, bad = _make_sessions(repo)
    result = runner.invoke(app, ["resume", bad, "--repo", str(repo)])
    assert result.exit_code == int(ExitCode.FAILED)
    assert f"Cannot resume session {bad}" in result.output
    assert "Traceback" not in result.output


def test_load_state_lenient_but_checkpoint_still_strict(repo):
    store = StateStore.create_session(repo, "lenient probe")
    (store.dir / "state.json").write_text("not json", encoding="utf-8")
    assert store.load_state() is None
    assert StateStore.load_state_of(repo, store.session_id) is None
    # An invalid phase checkpoint remains a hard, explicit failure.
    (store.dir / "phase-checkpoint.json").write_text("{}", encoding="utf-8")
    try:
        store.recover_phase()
    except ValueError as exc:
        assert "checkpoint" in str(exc)
    else:  # pragma: no cover - the defect direction would be silence
        raise AssertionError("invalid checkpoint must raise ValueError")


# ---------------------------------------------------------------------------
# V0.1-RC2 audit (remote baseline) regressions: B101 session resolution,
# B102 review progress truth, N101/N103/N105 event semantics
# ---------------------------------------------------------------------------


def test_same_second_sessions_resolve_by_created_at(repo, monkeypatch):
    """B101 acceptance 1: random suffixes have no temporal meaning."""
    import agent_review.storage as storage

    suffixes = iter(["ffff", "0000"])  # lexical order opposes creation order
    monkeypatch.setattr(
        storage, "new_session_id", lambda: f"20260911-020202-{next(suffixes)}"
    )
    first = storage.StateStore.create_session(repo, "lexically last")
    second = storage.StateStore.create_session(repo, "created last")
    assert first.session_id.endswith("ffff")
    assert second.session_id.endswith("0000")
    assert storage.StateStore.latest_session(repo, unfinished_only=False) == second.session_id


def test_latest_unfinished_includes_failed_and_interrupted(repo):
    """B101 acceptance 2: newer FAILED/INTERRUPTED sessions are resumable
    and must not be hidden by an older RUNNING one."""
    from agent_review.models import Phase, SessionStatus

    running = StateStore.create_session(repo, "older running")
    failed = StateStore.create_session(repo, "newer failed")
    state = failed.load_state()
    state.status = SessionStatus.FAILED
    state.phase = Phase.FAILED
    state.resume_phase = Phase.DESIGN
    failed.save_state(state)
    assert StateStore.latest_session(repo, unfinished_only=True) == failed.session_id

    interrupted = StateStore.create_session(repo, "newest interrupted")
    state = interrupted.load_state()
    state.status = SessionStatus.INTERRUPTED
    state.phase = Phase.INTERRUPTED
    state.resume_phase = Phase.DESIGN
    interrupted.save_state(state)
    assert StateStore.latest_session(repo, unfinished_only=True) == interrupted.session_id

    # Terminal (DONE) sessions never win the unfinished slot.
    done = StateStore.create_session(repo, "newest done")
    state = done.load_state()
    state.status = SessionStatus.DONE
    state.phase = Phase.DONE
    done.save_state(state)
    assert StateStore.latest_session(repo, unfinished_only=True) == interrupted.session_id
    assert StateStore.latest_session(repo, unfinished_only=False) == done.session_id


def test_resolution_and_list_share_ordering(repo):
    """B101 acceptance 3: status --list top row == default resolution."""
    for i in range(3):
        store = StateStore.create_session(repo, f"session {i}")
        from agent_review.models import Phase, SessionStatus

        state = store.load_state()
        state.status = SessionStatus.DONE
        state.phase = Phase.DONE
        store.save_state(state)
    listing = runner.invoke(app, ["status", "--repo", str(repo), "--list"])
    assert listing.exit_code == 0
    top_row = next(
        l for l in listing.output.splitlines() if re.match(r"\d{8}-\d{6}-[0-9a-f]{4}", l)
    )
    assert top_row.split()[0] == StateStore.latest_session(repo, unfinished_only=False)


def _load_events(store) -> list[dict]:
    return [
        json.loads(line)
        for line in (store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def _rendered(store, out: io.StringIO) -> str:
    """Replay persisted events through a fresh default renderer."""
    text = out.getvalue()
    renderer = ProgressRenderer(level=OutputLevel.DEFAULT, stream=out, heartbeat_interval=0)
    for event in _load_events(store):
        renderer.handle(event)
    return text


def test_closure_regression_never_renders_unqualified_success(repo):
    """B102 closure case: 1 resolved + 1 new blocking regression."""
    from agent_review.agents.fakes import make_blocking_issue
    from agent_review.models import IssueCategory

    regression = make_blocking_issue(9, title="regression introduced by fix")
    regression.category = IssueCategory.REGRESSION
    codex = FakeCodexAdapter(
        script={
            "initial_review": [
                json.dumps({"issues": [make_blocking_issue(1).model_dump()], "summary": "one"})
            ],
            "closure_review": [
                json.dumps(
                    {
                        "issue_outcomes": [
                            {"issue_id": "R001", "resolution": "RESOLVED", "note": "ok"}
                        ],
                        "new_issues": [regression.model_dump()],
                        "summary": "fixed but regressed",
                    }
                )
            ],
        }
    )
    out = io.StringIO()
    renderer = ProgressRenderer(stream=out, heartbeat_interval=0)
    o = Orchestrator.create(
        repository=repo,
        request="closure regression probe",
        config=Config(),
        pi=FakePiAdapter(),
        codex=codex,
        ui=NonInteractiveUI(),
        renderer=renderer,
    )
    assert o.run() == int(ExitCode.DONE)  # ablation -> final review closes it
    events = _load_events(o.store)
    closure = next(e for e in events if e["event"] == "CLOSURE_REVIEW_COMPLETED")
    assert closure["resolved"] == 1 and closure["new_blocking"] == 1
    assert closure["remaining"] >= 1
    text = _rendered(o.store, out)
    closure_lines = [l for l in text.splitlines() if "CLOSURE_REVIEW" in l and "✓" in l]
    assert closure_lines, "expected a closure completion line"
    assert "new blocker(s)" in closure_lines[0]
    assert "unresolved" in closure_lines[0]
    # The unqualified success wording must not appear alongside a regression.
    assert "blocker(s) verified resolved" not in closure_lines[0]


def test_closure_all_resolved_keeps_success_wording(repo):
    codex = FakeCodexAdapter(
        script={
            "initial_review": [
                json.dumps({"issues": [make_blocking_issue(1).model_dump()], "summary": "one"})
            ],
            "closure_review": [
                json.dumps(
                    {
                        "issue_outcomes": [
                            {"issue_id": "R001", "resolution": "RESOLVED", "note": "ok"}
                        ],
                        "new_issues": [],
                        "summary": "verified",
                    }
                )
            ],
        }
    )
    out = io.StringIO()
    renderer = ProgressRenderer(stream=out, heartbeat_interval=0)
    o = Orchestrator.create(
        repository=repo,
        request="closure clean probe",
        config=Config(),
        pi=FakePiAdapter(),
        codex=codex,
        ui=NonInteractiveUI(),
        renderer=renderer,
    )
    assert o.run() == int(ExitCode.DONE)
    text = _rendered(o.store, out)
    assert "1 of 1 blocker(s) verified resolved" in text


def test_final_review_verdict_never_overstates_pass(repo):
    """B102 final case: reviewer says satisfied, mechanical PASS disagrees."""
    codex = FakeCodexAdapter(
        script={
            "initial_review": [
                json.dumps({"issues": [make_blocking_issue(1).model_dump()], "summary": "one"})
            ],
            "closure_review": [
                json.dumps(
                    {
                        "issue_outcomes": [
                            {"issue_id": "R001", "resolution": "UNRESOLVED", "note": "no"}
                        ],
                        "new_issues": [],
                        "summary": "not verified",
                    }
                )
            ],
            "final_review": [
                json.dumps(
                    {
                        "satisfies_requirement": True,
                        "unresolved_issue_ids": ["R001"],
                        "issues": [],
                        "summary": "reviewer likes it",
                    }
                )
            ],
        }
    )
    out = io.StringIO()
    renderer = ProgressRenderer(stream=out, heartbeat_interval=0)
    o = Orchestrator.create(
        repository=repo,
        request="final disagreement probe",
        config=Config(),
        pi=FakePiAdapter(),
        codex=codex,
        ui=NonInteractiveUI(),
        renderer=renderer,
    )
    assert o.run() == int(ExitCode.HUMAN_HANDOFF)  # open blocker -> ablation -> final -> fail
    events = _load_events(o.store)
    final = next(e for e in events if e["event"] == "FINAL_REVIEW_COMPLETED")
    assert final["satisfies_requirement"] is True
    assert final["passed"] is False
    assert final["remaining"] >= 1
    text = _rendered(o.store, out)
    final_lines = [l for l in text.splitlines() if "FINAL_REVIEW" in l and ("✓" in l or "!" in l)]
    assert final_lines
    assert "requirement satisfied" not in final_lines[0]
    assert "not passed" in final_lines[0]
    assert "unresolved" in final_lines[0]


def test_final_review_pass_renders_satisfied(repo):
    """Genuine pass at FINAL_REVIEW (after ablation) renders satisfied+PASS."""
    codex = FakeCodexAdapter(
        script={
            "initial_review": [
                json.dumps({"issues": [make_blocking_issue(1).model_dump()], "summary": "one"})
            ],
            "closure_review": [
                json.dumps(
                    {
                        "issue_outcomes": [
                            {"issue_id": "R001", "resolution": "UNRESOLVED", "note": "no"}
                        ],
                        "new_issues": [],
                        "summary": "not verified",
                    }
                )
            ],
            # final_review defaults: satisfies=True, unresolved=[] -> the
            # ablation-addressed blocker is verified -> mechanical PASS.
        }
    )
    out = io.StringIO()
    renderer = ProgressRenderer(stream=out, heartbeat_interval=0)
    o = Orchestrator.create(
        repository=repo,
        request="clean pass probe",
        config=Config(),
        pi=FakePiAdapter(),
        codex=codex,
        ui=NonInteractiveUI(),
        renderer=renderer,
    )
    assert o.run() == int(ExitCode.DONE)
    text = _rendered(o.store, out)
    assert "requirement satisfied · PASS" in text


def test_keyboard_interrupt_not_counted_as_agent_failure(repo):
    """N101: Ctrl+C emits AGENT_CALL_INTERRUPTED, never AGENT_CALL_FAILED."""

    class InterruptingPi(FakePiAdapter):
        def discover(self, state):
            raise KeyboardInterrupt

    o = Orchestrator.create(
        repository=repo,
        request="interrupt classification probe",
        config=Config(),
        pi=InterruptingPi(),
        codex=FakeCodexAdapter(),
        ui=NonInteractiveUI(),
    )
    assert o.run() == int(ExitCode.INTERRUPTED)
    names = [e["event"] for e in _load_events(o.store)]
    assert "AGENT_CALL_INTERRUPTED" in names
    assert "AGENT_CALL_FAILED" not in names
    assert "SESSION_INTERRUPTED" in names


def test_protocol_retry_events_use_canonical_phase(repo):
    """N103: adapter method names never leak as event phase values."""
    codex = FakeCodexAdapter(
        script={
            "initial_review": ["not json"],
            "initial_review:repair": [json.dumps({"issues": [], "summary": "ok"})],
        }
    )
    o = Orchestrator.create(
        repository=repo,
        request="canonical phase probe",
        config=Config(),
        pi=FakePiAdapter(),
        codex=codex,
        ui=NonInteractiveUI(),
    )
    assert o.run() == int(ExitCode.DONE)
    retries = [e for e in _load_events(o.store) if e["event"].startswith("PROTOCOL_")]
    assert retries
    assert all(e.get("phase", "").isupper() for e in retries)
    assert any(e["phase"] == "INITIAL_REVIEW" for e in retries)


class AnsweringUI(NonInteractiveUI):
    def __init__(self, answers):
        self.answers = list(answers)

    def is_interactive(self) -> bool:
        return True

    def ask(self, prompt: str) -> str:
        return self.answers.pop(0) if self.answers else ""


def test_task_revision_message_only_claims_real_archives(repo):
    """N105: gate before any proposal -> no STALE archive claim."""
    pi = FakePiAdapter(
        script={
            "discover": [
                json.dumps(
                    {
                        "task_title": "门后无提案",
                        "task_kind": "CHANGE",
                        "current_state": "s",
                        "relevant_components": ["src/"],
                        "existing_constraints": [],
                        "change_surface": [],
                        "unknowns": [],
                        "human_candidates": [
                            {
                                "category": "TRADE_OFF",
                                "question": "策略 A 还是 B？",
                                "why": "",
                                "options": [
                                    {"key": "a", "label": "A", "impact": "x"},
                                    {"key": "b", "label": "B", "impact": "y"},
                                ],
                                "recommendation": "a",
                                "source": "DISCOVER",
                            }
                        ],
                    }
                )
            ]
        }
    )
    out = io.StringIO()
    renderer = ProgressRenderer(stream=out, heartbeat_interval=0)
    o = Orchestrator.create(
        repository=repo,
        request="revision before proposal probe",
        config=Config(),
        pi=pi,
        codex=FakeCodexAdapter(),
        ui=AnsweringUI(["1"]),
        renderer=renderer,
    )
    assert o.run() == int(ExitCode.DONE)
    revisions = [e for e in _load_events(o.store) if e["event"] == "TASK_REVISION_INCREMENTED"]
    assert revisions and revisions[0]["archived"] is False
    text = _rendered(o.store, out)
    revision_lines = [l for l in text.splitlines() if "task revision" in l]
    assert revision_lines
    assert "archived STALE" not in revision_lines[0]



# ---------------------------------------------------------------------------
# N002: session-id collision keeps the compact format invariant
# ---------------------------------------------------------------------------


def test_session_id_collision_keeps_compact_format(repo, monkeypatch):
    import agent_review.storage as storage

    fixed = ["20260911-010101-aaaa"]
    monkeypatch.setattr(storage, "new_session_id", lambda: fixed[0])
    first = storage.StateStore.create_session(repo, "first")
    assert first.session_id == "20260911-010101-aaaa"
    # The retry must regenerate a fresh compact id, never append "-2".
    calls = {"n": 0}

    def alternating():
        calls["n"] += 1
        return "20260911-010101-aaaa" if calls["n"] == 1 else "20260911-010101-bbbb"

    monkeypatch.setattr(storage, "new_session_id", alternating)
    second = storage.StateStore.create_session(repo, "second")
    assert second.session_id == "20260911-010101-bbbb"
    assert re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{4}", second.session_id)


# ---------------------------------------------------------------------------
# N001: convenience commands (--version, show events)
# ---------------------------------------------------------------------------


def test_cli_version(capsys):
    import sys

    argv = sys.argv
    try:
        sys.argv = ["review", "--version"]
        cli_main()
    finally:
        sys.argv = argv
    out = capsys.readouterr().out
    assert out.startswith("agent-review-orchestrator ")
    assert out.strip() != "agent-review-orchestrator unknown"


def test_cli_show_events(repo):
    o = Orchestrator.create(
        repository=repo,
        request="events probe",
        config=Config(),
        pi=FakePiAdapter(),
        codex=FakeCodexAdapter(),
        ui=NonInteractiveUI(),
    )
    assert o.run() == int(ExitCode.DONE)
    shown = runner.invoke(app, ["show", "events", "--repo", str(repo)])
    assert shown.exit_code == 0
    assert "SESSION_CREATED" in shown.output
    assert "AGENT_CALL_COMPLETED" in shown.output
    assert f"Session: {o.state.session_id}" in shown.output


# ---------------------------------------------------------------------------
# N003: resume --config parity
# ---------------------------------------------------------------------------


def test_cli_resume_accepts_config(repo, tmp_path, monkeypatch):
    import os

    class InterruptingPi(FakePiAdapter):
        def discover(self, state):
            raise KeyboardInterrupt

    o = Orchestrator.create(
        repository=repo,
        request="resume with config",
        config=Config(),
        pi=InterruptingPi(),
        codex=FakeCodexAdapter(),
        ui=NonInteractiveUI(),
    )
    assert o.run() == int(ExitCode.INTERRUPTED)
    config_file = tmp_path / "custom.toml"
    config_file.write_text(
        "[budgets]\nrevision = 1\nablation = 1\n\n[progress]\nheartbeat_seconds = 15.0\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_REVIEW_FAKE_ADAPTERS", "1")
    for key in ("AGENT_REVIEW_CONFIG",):
        monkeypatch.delenv(key, raising=False)
    result = runner.invoke(
        app,
        ["resume", o.state.session_id, "--repo", str(repo), "--config", str(config_file)],
    )
    assert result.exit_code == int(ExitCode.DONE)
    assert "final.md" in result.output


# ---------------------------------------------------------------------------
# V0 semantics preserved: title changes never alter workflow identity
# ---------------------------------------------------------------------------


def test_title_is_presentation_only(repo):
    o = Orchestrator.create(
        repository=repo,
        request="identity probe",
        config=Config(),
        pi=FakePiAdapter(),
        codex=FakeCodexAdapter(),
        ui=NonInteractiveUI(),
        name="演示标题",
    )
    sid = o.state.session_id
    assert o.run() == int(ExitCode.DONE)
    state = StateStore.load_state_of(repo, sid)
    state.task_title = "另一个标题"
    StateStore(repo, sid).save_state(state)
    listing = runner.invoke(app, ["status", "--repo", str(repo)])
    assert listing.exit_code == 0
    assert "另一个标题" in listing.output
    # Session id (identity) unchanged; phase machine untouched by the rename.
    assert StateStore.load_state_of(repo, sid).session_id == sid
    assert StateStore.load_state_of(repo, sid).phase.value == "DONE"
