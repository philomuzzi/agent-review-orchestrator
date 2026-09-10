"""Typer CLI: the ``review`` command family.

The binary maps the invocation style required by the V0 contract:

- ``review "<request>"``           -> default ``run`` command
- ``review --repo PATH "<request>"``
- ``review --kind change "<request>"``
- ``review resume [session-id]``
- ``review status [session-id]``
- ``review show [final|gate|task|proposal|issues] [session-id]``
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import typer

from agent_review.config import Config, load_config
from agent_review.models import ExitCode, Phase, SessionStatus
from agent_review.storage import StateStore, review_root

app = typer.Typer(
    add_completion=False,
    help="Agent Review Orchestrator: converge design changes through "
    "a Pi Author + Codex Reviewer + Human Gate workflow.",
)

SHOW_KINDS = ("final", "gate", "task", "proposal", "issues")


def _repo_path(repo: str | None) -> Path:
    path = Path(repo).resolve() if repo else Path.cwd()
    if not path.is_dir():
        typer.secho(f"Repository path does not exist: {path}", fg=typer.colors.RED)
        raise typer.Exit(ExitCode.FAILED)
    return path


def _resolve_session(repo: Path, session_id: str | None) -> str | None:
    if session_id:
        if session_id not in StateStore.list_sessions(repo):
            typer.secho(
                f"Session not found: {session_id}", fg=typer.colors.RED
            )
            raise typer.Exit(ExitCode.FAILED)
        return session_id
    sid = StateStore.latest_session(repo, unfinished_only=True)
    if sid is None:
        sid = StateStore.latest_session(repo, unfinished_only=False)
    return sid


def _echo_exit(code: ExitCode, message: str) -> None:
    color = {
        ExitCode.DONE: typer.colors.GREEN,
        ExitCode.HUMAN_HANDOFF: typer.colors.YELLOW,
        ExitCode.WAITING_FOR_HUMAN: typer.colors.YELLOW,
        ExitCode.FAILED: typer.colors.RED,
        ExitCode.INTERRUPTED: typer.colors.YELLOW,
    }.get(code, typer.colors.WHITE)
    typer.secho(message, fg=color)
    raise typer.Exit(int(code))


@app.command()
def run(
    request: str = typer.Argument(..., help="Natural-language review request."),
    repo: str = typer.Option(
        None, "--repo", help="Target repository (default: current directory)."
    ),
    kind: str = typer.Option(
        None,
        "--kind",
        help="Task kind: change | problem (default: discovered automatically).",
    ),
    config_path: str = typer.Option(
        None, "--config", help="Path to config TOML (default: auto-detect)."
    ),
) -> None:
    """Start a new review session for REQUEST."""
    if kind is not None and kind.lower() not in ("change", "problem"):
        typer.secho("--kind must be 'change' or 'problem'", fg=typer.colors.RED)
        raise typer.Exit(ExitCode.FAILED)

    repo_path = _repo_path(repo)
    config: Config = load_config(config_path)

    from agent_review.orchestrator import Orchestrator  # deferred: keeps --help fast

    orchestrator = Orchestrator.create(
        repository=repo_path,
        request=request,
        task_kind_explicit=kind,
        config=config,
    )
    _report(orchestrator, repo_path)


@app.command()
def resume(
    session_id: str = typer.Argument(None, help="Session id (default: latest unfinished)."),
    repo: str = typer.Option(None, "--repo", help="Target repository."),
) -> None:
    """Resume an interrupted or Human-Gate session."""
    repo_path = _repo_path(repo)
    sid = _resolve_session(repo_path, session_id)
    if sid is None:
        _echo_exit(ExitCode.FAILED, "No sessions found under .review/")
    config: Config = load_config(None)

    from agent_review.orchestrator import Orchestrator

    orchestrator = Orchestrator.resume(repository=repo_path, session_id=sid, config=config)
    _report(orchestrator, repo_path)


def _report(orchestrator, repo_path: Path) -> None:
    """Run the orchestrator, print a per-exit-code summary and exit."""
    code = orchestrator.run()
    state = orchestrator.state
    session_dir = review_root(repo_path) / state.session_id
    if code == ExitCode.DONE:
        _echo_exit(code, f"DONE: {session_dir / 'final.md'}")
    if code == ExitCode.WAITING_FOR_HUMAN:
        _echo_exit(
            code,
            "WAITING_FOR_HUMAN: answer the gate via 'review resume' "
            f"(packet: {session_dir / 'human-gate.md'})",
        )
    if code == ExitCode.HUMAN_HANDOFF:
        reason = state.handoff_reason or "task-level boundary reached"
        _echo_exit(code, f"HUMAN_HANDOFF: {reason} (session: {session_dir})")
    if code == ExitCode.INTERRUPTED:
        _echo_exit(code, f"INTERRUPTED: resume with 'review resume {state.session_id}'")
    _echo_exit(code, f"FAILED: {state.error or 'unexpected failure'}")


@app.command()
def status(
    session_id: str = typer.Argument(None, help="Session id (default: latest unfinished)."),
    repo: str = typer.Option(None, "--repo", help="Target repository."),
) -> None:
    """Report phase, blockers and budgets for a session."""
    repo_path = _repo_path(repo)
    sid = _resolve_session(repo_path, session_id)
    if sid is None:
        _echo_exit(ExitCode.FAILED, "No sessions found under .review/")
    store = StateStore(repo_path, sid)
    state = store.load_state()
    if state is None:
        _echo_exit(ExitCode.FAILED, f"Corrupt session state: {store.dir}")

    issues = store.load_issues().issues
    open_blocking = [i.id for i in issues if i.severity.value == "BLOCKING" and i.status.value == "OPEN"]
    addressed = [i.id for i in issues if i.severity.value == "BLOCKING" and i.status.value == "ADDRESSED"]
    need_human = [i.id for i in issues if i.status.value == "NEED_HUMAN"]

    typer.echo(f"session:        {state.session_id}")
    typer.echo(f"repository:     {state.repository}")
    typer.echo(f"task kind:      {state.task_kind.value}")
    typer.echo(f"phase:          {state.phase.value}")
    typer.echo(f"status:         {state.status.value}")
    typer.echo(f"task revision:  {state.task_revision}")
    typer.echo(f"review round:   {state.round}")
    typer.echo(f"active gate:    {state.active_gate or '-'}")
    typer.echo(
        "blockers:       "
        f"open={open_blocking or '-'} addressed={addressed or '-'} need_human={need_human or '-'}"
    )
    b = state.budgets
    lim = state.limits
    typer.echo(
        f"budgets:        revision {b.revision_used}/{lim.max_revision_rounds}, "
        f"ablation {b.ablation_used}/{lim.max_ablation_rounds}, "
        f"human gates {b.human_interruptions_used}/{lim.max_human_interruptions}, "
        f"protocol retries {b.protocol_retries_used}/{lim.max_protocol_retries}"
    )
    if state.phase == Phase.WAITING_FOR_HUMAN:
        typer.echo("hint:           answer with 'review resume'")
    raise typer.Exit(ExitCode.DONE)


@app.command()
def show(
    what: str = typer.Argument(
        "final", help=f"One of: {', '.join(SHOW_KINDS)}."
    ),
    session_id: str = typer.Argument(None, help="Session id (default: latest unfinished)."),
    repo: str = typer.Option(None, "--repo", help="Target repository."),
) -> None:
    """Show a session artifact (final.md, gate, task, proposal, issues)."""
    if what not in SHOW_KINDS:
        _echo_exit(ExitCode.FAILED, f"Unknown artifact '{what}'. Use one of: {', '.join(SHOW_KINDS)}")
    repo_path = _repo_path(repo)
    sid = _resolve_session(repo_path, session_id)
    if sid is None:
        _echo_exit(ExitCode.FAILED, "No sessions found under .review/")
    store = StateStore(repo_path, sid)

    files = {
        "final": ("final.md", "text"),
        "gate": ("human-gate.md", "text"),
        "task": ("task.md", "text"),
        "proposal": ("proposal.md", "text"),
        "issues": ("issues.json", "json"),
    }
    filename, kind = files[what]
    if what == "final":
        content = store.read_text("final.md")
    else:
        content = store.read_text(filename)
    if content is None:
        _echo_exit(ExitCode.FAILED, f"'{what}' not available yet for session {sid}")
    typer.echo(content.rstrip())
    raise typer.Exit(ExitCode.DONE)


def _harness_windows_stdio() -> None:
    """Avoid GBK multi-byte flush failures (EINVAL) on msys/console pipes."""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream.encoding and stream.encoding.lower().replace("-", "") != "utf8":
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _guard_console_output() -> None:
    """Prevent rich from driving Win32 console APIs on a non-console stdout.

    When stdout is redirected or detached (PowerShell pipelines, msys
    pipes, some terminal hosts), rich's legacy-windows renderer calls
    kernel32 console functions on an invalid handle: at best
    ``OSError: [Errno 22]``, at worst a native access violation that
    crashes python.exe (crash dialog reading 0xFFFFFFFFFFFFFFFF).
    If stdout is not a real Windows console, force the plain path.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        real_console = kernel32.GetConsoleMode(handle, ctypes.byref(mode)) != 0
    except Exception:
        return
    if real_console:
        return
    try:
        import rich.console

        rich.console.detect_legacy_windows = lambda: False  # type: ignore[assignment]
    except Exception:
        pass
    os.environ.setdefault("NO_COLOR", "1")


def main() -> None:
    """Entry point routing the spec'd invocation styles onto the Typer app."""
    _harness_windows_stdio()
    _guard_console_output()
    argv = sys.argv[1:]
    subcommands = {"run", "resume", "status", "show"}
    if not argv:
        app(["--help"])
        return
    if argv[0] in subcommands or argv[0] in ("--help", "-h", "--version"):
        app()
        return
    # Default command: `review "<request>" [--repo ...] [--kind ...]`
    sys.argv = [sys.argv[0], "run", *argv]
    app()


if __name__ == "__main__":
    main()
