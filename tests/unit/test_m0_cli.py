"""M0: CLI surface via Typer's CliRunner."""

from __future__ import annotations

import os

from typer.testing import CliRunner

from agent_review.cli import app

runner = CliRunner()
FAKE_ENV = {"AGENT_REVIEW_FAKE_ADAPTERS": "1", **os.environ}


def test_help_exits_zero():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for word in ("run", "resume", "status", "show"):
        assert word in result.output


def test_run_creates_session(repo):
    result = runner.invoke(
        app, ["run", "--repo", str(repo), "add pause to sync"], env=FAKE_ENV
    )
    assert result.exit_code == 0
    state_files = list((repo / ".review").glob("*/state.json"))
    assert len(state_files) == 1
    final = list((repo / ".review").glob("*/final.md"))
    assert len(final) == 1


def test_run_rejects_bad_kind(repo):
    result = runner.invoke(app, ["run", "--kind", "bogus", "--repo", str(repo), "req"])
    assert result.exit_code == 30


def test_status_reports_session(repo):
    result = runner.invoke(
        app, ["run", "--repo", str(repo), "do something"], env=FAKE_ENV
    )
    assert result.exit_code == 0
    status = runner.invoke(app, ["status", "--repo", str(repo)])
    assert status.exit_code == 0
    assert "phase:" in status.output
    assert "DONE" in status.output


def test_console_guard_disables_rich_legacy_on_non_console():
    """Non-console stdout must never let rich use Win32 console APIs."""
    from agent_review.cli import _guard_console_output

    _guard_console_output()  # pytest captures stdout -> not a real console
    import rich.console

    console = rich.console.Console()
    assert console.legacy_windows is False
