"""V0.1-RC3 regressions: B201/B202/B203 (see docs/V0_1_RC3_FIX_SPEC.md).

- B201: every final CLI free-text exit summary crosses the same
  host-owned ``sanitize_line`` boundary as the progress renderer.
- B202: ``review show`` validates session state before emitting any
  artifact — a corrupt session fails closed even when the artifact exists.
- B203: new session ids stamp host LOCAL wall-clock time while persisted
  ``created_at`` stays the authoritative ordering truth.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from typer.testing import CliRunner

from agent_review.agents.base import AgentError
from agent_review.agents.fakes import FakeCodexAdapter, FakePiAdapter
from agent_review.cli import app
from agent_review.config import Config
from agent_review.models import ExitCode, InvestigationResult, RootCauseStatus
from agent_review.orchestrator import Orchestrator
from agent_review.storage import StateStore

runner = CliRunner()

HOSTILE_REASON = (
    'agent stderr:\nTraceback (most recent call last)\n\tFile "worker.py", '
    "line 3\x1b[31m RED\x1b[0m\x00"
)
# Hostile text after the host-owned boundary: whitespace runs collapse to
# single spaces, control/escape bytes (ESC, NUL) drop, words stay separated.
HOSTILE_REASON_COLLAPSED = (
    'agent stderr: Traceback (most recent call last) File "worker.py", '
    "line 3[31m RED[0m"
)

HOSTILE_MISSING = "fact A missing\nfact B\tunresolved \x1b[31mRED\x1b[0m"
HOSTILE_MISSING_COLLAPSED = "fact A missing fact B unresolved [31mRED[0m"


class NonInteractiveUI:
    def is_interactive(self) -> bool:
        return False

    def echo(self, text: str) -> None:
        pass

    def ask(self, prompt: str) -> str:  # pragma: no cover
        return ""


def _patch_adapters(monkeypatch, pi, codex=None) -> None:
    """Route CLI-run adapter construction to scripted fakes."""
    import agent_review.agents as agents_pkg

    monkeypatch.setattr(
        agents_pkg,
        "build_adapters",
        lambda cfg, repository=None, store=None: (pi, codex or FakeCodexAdapter()),
    )


def _session_dir_from_output(repo, output: str):
    sid = re.search(r"^Session: (\S+)", output, re.MULTILINE).group(1)
    return sid, repo / ".review" / sid


# ---------------------------------------------------------------------------
# B201: CLI final exit summaries cross the shared presentation boundary
# ---------------------------------------------------------------------------


def test_cli_failed_summary_single_line_full_report_path(repo, monkeypatch):
    """FAILED summary with multiline/tab/ANSI/control reason -> one safe line."""
    _patch_adapters(
        monkeypatch, FakePiAdapter(script={"discover": [AgentError(HOSTILE_REASON)]})
    )
    result = runner.invoke(app, ["run", "fix the worker crash", "--repo", str(repo)])
    assert result.exit_code == int(ExitCode.FAILED)
    lines = result.output.splitlines()
    expected = f"FAILED: {HOSTILE_REASON_COLLAPSED}"
    assert expected in lines  # exact single collapsed summary line
    # No escape bytes or NUL anywhere; every line is printable text.
    assert "\x1b" not in result.output
    assert "\x00" not in result.output
    assert all(line == "".join(ch for ch in line if ch.isprintable()) for line in lines)


def test_cli_handoff_summary_single_line_full_report_path(repo, monkeypatch):
    """HUMAN_HANDOFF summary embedding hostile agent text -> one safe line."""
    hostile_investigation = InvestigationResult(
        root_cause="",
        root_cause_status=RootCauseStatus.UNRESOLVED,
        missing_evidence=[HOSTILE_MISSING],
        human_candidates=[],
    ).model_dump_json()
    _patch_adapters(
        monkeypatch, FakePiAdapter(script={"investigate": [hostile_investigation]})
    )
    result = runner.invoke(
        app, ["run", "--kind", "problem", "worker randomly stalls", "--repo", str(repo)]
    )
    assert result.exit_code == int(ExitCode.HUMAN_HANDOFF)
    sid, session_dir = _session_dir_from_output(repo, result.output)
    expected = (
        "HUMAN_HANDOFF: root cause UNRESOLVED, missing facts materially "
        f"affect fix direction: {HOSTILE_MISSING_COLLAPSED} (session: {session_dir})"
    )
    assert expected in result.output.splitlines()
    assert "\x1b" not in result.output
    assert "\x00" not in result.output
    assert all(line == "".join(ch for ch in line if ch.isprintable()) for line in result.output.splitlines())


def test_cli_summary_and_progress_event_share_boundary(repo, monkeypatch):
    """B201 acceptance 3: rendered event line and exit summary obey one rule."""
    _patch_adapters(
        monkeypatch, FakePiAdapter(script={"discover": [AgentError(HOSTILE_REASON)]})
    )
    result = runner.invoke(app, ["run", "fix the worker crash", "--repo", str(repo)])
    lines = result.output.splitlines()
    summary = [ln for ln in lines if ln.startswith("FAILED: ")]
    event = [ln for ln in lines if "FAILED ·" in ln]
    assert len(summary) == 1 and len(event) == 1
    assert HOSTILE_REASON_COLLAPSED in summary[0]
    assert HOSTILE_REASON_COLLAPSED in event[0]
    # Neither surface leaked the raw multiline/escape payload.
    assert "\x1b" not in result.output
    assert "Traceback (most recent call last)\n" not in result.output


def test_cli_failed_summary_preserves_cjk_reason(repo, monkeypatch):
    """Normal Chinese reasons stay readable after normalization."""
    _patch_adapters(
        monkeypatch,
        FakePiAdapter(script={"discover": [AgentError("同步任务失败：缺少必要参数")]}),
    )
    result = runner.invoke(app, ["run", "修复同步任务", "--repo", str(repo)])
    assert result.exit_code == int(ExitCode.FAILED)
    assert "FAILED: 同步任务失败：缺少必要参数" in result.output.splitlines()


# ---------------------------------------------------------------------------
# B202: review show fails closed on corrupt session state, artifact or not
# ---------------------------------------------------------------------------


def _done_session_with_final(repo) -> str:
    o = Orchestrator.create(
        repository=repo,
        request="给同步任务增加暂停能力，尽量最小改动",
        config=Config(),
        pi=FakePiAdapter(),
        codex=FakeCodexAdapter(),
        ui=NonInteractiveUI(),
    )
    assert o.run() == int(ExitCode.DONE)
    return o.state.session_id


def _corrupt_state(repo, sid: str) -> None:
    (repo / ".review" / sid / "state.json").write_text(
        "{ this is not json", encoding="utf-8"
    )


def test_show_final_fails_closed_when_state_corrupt_despite_artifact(repo):
    """B202 acceptance 1: valid final.md + corrupt state.json -> exit 30, no body."""
    sid = _done_session_with_final(repo)
    final_path = repo / ".review" / sid / "final.md"
    final_body = final_path.read_text(encoding="utf-8")
    assert final_body.startswith("# Final Design")  # the artifact genuinely exists
    _corrupt_state(repo, sid)

    result = runner.invoke(app, ["show", "final", sid, "--repo", str(repo)])
    assert result.exit_code == int(ExitCode.FAILED)
    assert "Corrupt session state" in result.output
    assert "Traceback" not in result.output
    # No artifact body leaked before the corruption was detected.
    assert "# Final Design" not in result.output
    assert result.output.count("Session:") == 0  # no session header either


def test_show_events_fails_closed_when_state_corrupt_despite_artifact(repo):
    """B202 acceptance 2: existing events.jsonl + corrupt state -> exit 30."""
    sid = _done_session_with_final(repo)
    events_path = repo / ".review" / sid / "events.jsonl"
    assert events_path.is_file()  # events always exist for a real session
    _corrupt_state(repo, sid)

    result = runner.invoke(app, ["show", "events", sid, "--repo", str(repo)])
    assert result.exit_code == int(ExitCode.FAILED)
    assert "Corrupt session state" in result.output
    assert "Traceback" not in result.output
    # The event stream (which contains SESSION_CREATED etc.) never leaked.
    assert "SESSION_CREATED" not in result.output
    assert "DISCOVER_COMPLETED" not in result.output


def test_show_all_kinds_fail_closed_before_artifact_output(repo):
    """State validation precedes artifact output for every show kind."""
    sid = _done_session_with_final(repo)
    session_dir = repo / ".review" / sid
    # Make every artifact exist with an unmistakable sentinel body.
    sentinel = "SENTINEL-ARTIFACT-BODY"
    for name in ("final.md", "human-gate.md", "task.md", "proposal.md", "issues.json", "events.jsonl"):
        (session_dir / name).write_text(sentinel, encoding="utf-8")
    _corrupt_state(repo, sid)

    for what in ("final", "gate", "task", "proposal", "issues", "events"):
        result = runner.invoke(app, ["show", what, sid, "--repo", str(repo)])
        assert result.exit_code == int(ExitCode.FAILED), what
        assert "Corrupt session state" in result.output, what
        assert "Traceback" not in result.output, what
        assert sentinel not in result.output, what


def test_show_healthy_sessions_unchanged(repo):
    """B202 acceptance 4: healthy sessions keep existing show behavior."""
    sid = _done_session_with_final(repo)
    result = runner.invoke(app, ["show", "final", sid, "--repo", str(repo)])
    assert result.exit_code == int(ExitCode.DONE)
    assert f"Session: {sid}" in result.output
    assert "# Final Design" in result.output
    assert result.output.count("Session:") == 1

    events = runner.invoke(app, ["show", "events", sid, "--repo", str(repo)])
    assert events.exit_code == int(ExitCode.DONE)
    assert "SESSION_CREATED" in events.output

    # A healthy session without the artifact still gets the clean message.
    (repo / ".review" / sid / "proposal.md").unlink()
    missing = runner.invoke(app, ["show", "proposal", sid, "--repo", str(repo)])
    assert missing.exit_code == int(ExitCode.FAILED)
    assert "'proposal' not available yet" in missing.output


# ---------------------------------------------------------------------------
# B203: local wall-clock session ids; created_at stays authoritative
# ---------------------------------------------------------------------------

UTC_PLUS_9 = timezone(timedelta(hours=9))


def test_session_id_reflects_injected_local_clock(repo, monkeypatch):
    """B203 acceptance 1/7: controlled non-UTC local clock -> local wall time."""
    import agent_review.storage as storage

    # 12:34:56 at UTC+9 == 03:34:56 UTC: the id must show the LOCAL fields.
    monkeypatch.setattr(
        storage,
        "local_now",
        lambda: datetime(2026, 1, 2, 12, 34, 56, tzinfo=UTC_PLUS_9),
    )
    store = storage.StateStore.create_session(repo, "本地时钟会话")
    assert store.session_id.startswith("20260102-123456-")
    assert not store.session_id.startswith("20260102-033456-")  # not UTC
    assert re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{4}", store.session_id)


def test_new_session_id_injection_and_compact_format():
    from agent_review.storage import new_session_id

    sid = new_session_id(datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone.utc))
    assert sid.startswith("20260304-050607-")
    assert re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{4}", sid)
    # Uninjected call still honors the format (host-local clock).
    assert re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{4}", new_session_id())


def test_created_at_remains_timezone_aware_authoritative(repo, monkeypatch):
    """B203 acceptance 5: persisted metadata stays tz-aware and authoritative."""
    import agent_review.storage as storage

    monkeypatch.setattr(
        storage,
        "local_now",
        lambda: datetime(2026, 1, 2, 12, 34, 56, tzinfo=UTC_PLUS_9),
    )
    store = storage.StateStore.create_session(repo, "本地时钟会话")
    state = store.load_state()
    assert state.created_at.tzinfo is not None
    assert state.created_at.utcoffset() == timedelta(0)  # persisted in UTC
    # Ordering policy reads persisted metadata, never the id clock.
    assert storage.StateStore._creation_ordered(repo)[-1][2] == store.session_id


def test_ordering_follows_created_at_not_visible_id_time(repo, monkeypatch):
    """B203 acceptance 6: visible id times lie; created_at still wins."""
    import agent_review.storage as storage

    stamps = iter(["20260103-000000-aaaa", "20260102-235959-bbbb"])
    monkeypatch.setattr(
        storage, "new_session_id", lambda: f"{next(stamps)}"
    )
    first = storage.StateStore.create_session(repo, "created first")  # id looks newer
    second = storage.StateStore.create_session(repo, "created second")  # id looks older
    first_created = first.load_state().created_at
    second_created = second.load_state().created_at
    assert first_created < second_created  # real ordering truth
    assert storage.StateStore.latest_session(repo, unfinished_only=False) == second.session_id

    listing = runner.invoke(app, ["status", "--repo", str(repo), "--list"])
    assert listing.exit_code == int(ExitCode.DONE)
    rows = [
        ln
        for ln in listing.output.splitlines()
        if ln.startswith(("20260103-000000-aaaa", "20260102-235959-bbbb"))
    ]
    assert rows[0].startswith(second.session_id)  # newest first == created_at order
    # Sanity: the visible id clock would have claimed the opposite.
    assert first.session_id > second.session_id
