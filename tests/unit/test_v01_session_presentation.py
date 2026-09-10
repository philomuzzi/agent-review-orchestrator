"""V0.1 session presentation: short id, task title, status/resume/show."""

from __future__ import annotations

import io
import json
import os
import re

from typer.testing import CliRunner

from agent_review.agents.fakes import FakeCodexAdapter, FakePiAdapter
from agent_review.cli import app
from agent_review.config import Config
from agent_review.models import ExitCode
from agent_review.orchestrator import Orchestrator
from agent_review.progress import PLACEHOLDER_TITLE
from agent_review.storage import StateStore

runner = CliRunner()
FAKE_ENV = {"AGENT_REVIEW_FAKE_ADAPTERS": "1", **os.environ}


def test_session_id_short_stable_request_independent(repo):
    store = StateStore.create_session(repo, "当前项目全局任务只支持一个同时执行如果需要另起一个任务必须等待")
    sid = store.load_state().session_id
    assert re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{4}", sid)
    # Independent of request wording: no CJK, no request text.
    assert sid.isascii()
    # Stable for the session life; directory is never renamed.
    assert store.dir.name == sid
    store.save_state(store.load_state())
    assert store.load_state().session_id == sid


def test_session_id_unique_across_same_second(repo):
    ids = {
        StateStore.create_session(repo, f"request {i}").load_state().session_id
        for i in range(20)
    }
    assert len(ids) == 20


def test_task_title_from_discovery_persisted(repo):
    o = Orchestrator.create(
        repository=repo,
        request="给同步任务增加暂停能力，尽量最小改动",
        config=Config(),
        pi=FakePiAdapter(),
        codex=FakeCodexAdapter(),
        ui=_noninteractive_ui(),
    )
    assert o.run() == int(ExitCode.DONE)
    state = StateStore.load_state_of(repo, o.state.session_id)
    # Fake discovery derives a deterministic title from the request.
    assert state.task_title == "给同步任务增加暂停能力，尽量最小改动"[:16]
    assert state.task_title_source == "discover"
    events = [
        json.loads(line)
        for line in (o.store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(e["event"] == "TASK_TITLE_SET" for e in events)


def test_user_name_overrides_discovery_title(repo):
    o = Orchestrator.create(
        repository=repo,
        request="很长的原始请求描述",
        config=Config(),
        pi=FakePiAdapter(),
        codex=FakeCodexAdapter(),
        ui=_noninteractive_ui(),
        name="全局任务并行化",
    )
    assert o.run() == int(ExitCode.DONE)
    state = StateStore.load_state_of(repo, o.state.session_id)
    assert state.task_title == "全局任务并行化"
    assert state.task_title_source == "user"
    # Session identity is unaffected by the name.
    assert re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{4}", state.session_id)


class _noninteractive_ui:
    def is_interactive(self) -> bool:
        return False

    def echo(self, text: str) -> None:
        pass

    def ask(self, prompt: str) -> str:  # pragma: no cover
        return ""


# ---------------------------------------------------------------------------
# CLI-level behavior
# ---------------------------------------------------------------------------


def test_cli_run_with_name_and_status_headers(repo):
    result = runner.invoke(
        app,
        ["run", "--repo", str(repo), "--name", "同步暂停", "add pause to sync"],
        env=FAKE_ENV,
    )
    assert result.exit_code == 0
    sid = StateStore.latest_session(repo, unfinished_only=False)
    status = runner.invoke(app, ["status", "--repo", str(repo)])
    assert status.exit_code == 0
    assert f"Session: {sid}" in status.output
    assert "Task:    同步暂停" in status.output
    assert "Repo:" in status.output
    assert "phase:" in status.output  # detail block retained
    assert "DONE" in status.output


def test_cli_status_placeholder_title_when_missing(repo):
    """Legacy V0 session (no task_title) still renders with a placeholder."""
    runner.invoke(app, ["run", "--repo", str(repo), "legacy request"], env=FAKE_ENV)
    sid = StateStore.latest_session(repo, unfinished_only=False)
    store = StateStore(repo, sid)
    # Simulate a legacy session: strip presentation metadata.
    state = store.load_state()
    state.task_title = None
    state.task_title_source = None
    store.save_state(state)
    status = runner.invoke(app, ["status", "--repo", str(repo)])
    assert status.exit_code == 0
    assert f"Task:    {PLACEHOLDER_TITLE}" in status.output


def test_cli_status_list_shows_recent_sessions(repo):
    runner.invoke(
        app, ["run", "--repo", str(repo), "--name", "会话一", "first request"], env=FAKE_ENV
    )
    runner.invoke(
        app, ["run", "--repo", str(repo), "--name", "会话二", "second request"], env=FAKE_ENV
    )
    listing = runner.invoke(app, ["status", "--repo", str(repo), "--list"])
    assert listing.exit_code == 0
    assert "Recent sessions" in listing.output
    lines = [l for l in listing.output.splitlines() if l[:2].isdigit()]
    assert len(lines) == 2
    # Newest first: second session on top.
    assert "会话二" in lines[0] and "DONE" in lines[0]
    assert "会话一" in lines[1]
    # Each row carries the compact id, the title and the outcome.
    for line in lines:
        assert re.match(r"\d{8}-\d{6}-[0-9a-f]{4}  \S+  \S+", line)


def test_cli_show_includes_session_header(repo):
    runner.invoke(
        app, ["run", "--repo", str(repo), "--name", "标题甲", "some request"], env=FAKE_ENV
    )
    shown = runner.invoke(app, ["show", "final", "--repo", str(repo)])
    assert shown.exit_code == 0
    sid = StateStore.latest_session(repo, unfinished_only=False)
    assert f"Session: {sid}" in shown.output
    assert "Task:    标题甲" in shown.output
    assert "# Final" in shown.output or "## " in shown.output


def test_cli_verbose_and_quiet_levels(repo):
    verbose = runner.invoke(
        app,
        ["run", "--repo", str(repo), "--verbose", "verbose request"],
        env=FAKE_ENV,
    )
    assert verbose.exit_code == 0
    assert "→ DISCOVER" in verbose.output
    assert "Pi inspecting repository..." in verbose.output
    assert "✓ INITIAL_REVIEW" in verbose.output
    assert "proposal.md" in verbose.output  # verbose artifact detail

    quiet = runner.invoke(
        app,
        ["run", "--repo", str(repo), "--quiet", "quiet request"],
        env=FAKE_ENV,
    )
    assert quiet.exit_code == 0
    assert "DONE:" in quiet.output  # final result
    assert "→ DISCOVER" not in quiet.output
    assert "Pi inspecting" not in quiet.output
    assert "✓ INITIAL_REVIEW" not in quiet.output
    assert "still working" not in quiet.output


def test_cli_verbose_quiet_mutually_exclusive(repo):
    result = runner.invoke(
        app,
        ["run", "--repo", str(repo), "--verbose", "--quiet", "req"],
        env=FAKE_ENV,
    )
    assert result.exit_code == int(ExitCode.FAILED)
    assert "mutually exclusive" in result.output


def test_cli_quiet_still_shows_human_gate(repo):
    """Non-interactive gate must be visible even in --quiet mode."""
    pi = FakePiAdapter(
        script={
            "discover": [
                json.dumps(
                    {
                        "task_title": "需要人工决策的改动",
                        "task_kind": "CHANGE",
                        "current_state": "state",
                        "relevant_components": ["src/"],
                        "existing_constraints": [],
                        "change_surface": ["src/"],
                        "unknowns": [],
                        "human_candidates": [
                            {
                                "category": "TRADE_OFF",
                                "question": "Choose strategy A or B?",
                                "why": "real trade-off",
                                "options": [
                                    {"key": "a", "label": "Strategy A", "impact": "fast"},
                                    {"key": "b", "label": "Strategy B", "impact": "safe"},
                                ],
                                "recommendation": None,
                                "source": "DISCOVER",
                            }
                        ],
                    }
                )
            ]
        }
    )
    ui = _noninteractive_ui()
    o = Orchestrator.create(
        repository=repo,
        request="request needing a gate",
        config=Config(),
        pi=pi,
        codex=FakeCodexAdapter(),
        ui=ui,
    )
    code = o.run()
    assert code == int(ExitCode.WAITING_FOR_HUMAN)

    out = io.StringIO()
    from agent_review.progress import OutputLevel, ProgressRenderer

    renderer = ProgressRenderer(level=OutputLevel.QUIET, stream=out, heartbeat_interval=0)
    # Replay the gate event through a quiet renderer to prove visibility.
    events = [
        json.loads(line)
        for line in (o.store.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    for event in events:
        renderer.handle(event)
    assert "! HUMAN GATE" in out.getvalue()
