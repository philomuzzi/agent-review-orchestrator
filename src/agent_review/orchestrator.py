"""The deterministic orchestration loop.

Owns process state, dispatches phase modules, enforces the state machine,
exit codes and interruption/failure persistence. V0.1: also owns runtime
progress — every workflow fact flows through ``event()`` into one stream
feeding both ``events.jsonl`` and the CLI renderer.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Optional, Protocol

from agent_review.agents.base import AgentError, ProtocolError
from agent_review.config import Config, load_config
from agent_review.models import (
    ExitCode,
    Phase,
    SessionState,
    SessionStatus,
    TaskKind,
)
from agent_review.progress import NullRenderer, ProgressRenderer
from agent_review.state_machine import assert_transition
from agent_review.storage import StateStore

MAX_STEPS = 200


class UI(Protocol):
    def is_interactive(self) -> bool: ...
    def echo(self, text: str) -> None: ...
    def ask(self, prompt: str) -> str: ...


class ConsoleUI:
    """Real terminal UI; falls back to non-interactive when stdin is not a TTY."""

    def is_interactive(self) -> bool:
        try:
            return sys.stdin.isatty()
        except Exception:  # pragma: no cover - exotic stdin
            return False

    def echo(self, text: str) -> None:
        print(text, flush=True)

    def ask(self, prompt: str) -> str:
        return input(prompt)


class Orchestrator:
    def __init__(
        self,
        store: StateStore,
        state: SessionState,
        pi,
        codex,
        config: Config | None = None,
        ui: UI | None = None,
        renderer: ProgressRenderer | None = None,
    ):
        self.store = store
        self.state = state
        self.pi = pi
        self.codex = codex
        self.config = config or load_config()
        self.ui = ui or ConsoleUI()
        self.renderer = renderer or NullRenderer()
        self.renderer.session_dir = str(store.dir)
        # Adapter protocol-retry events flow into the same event stream.
        for adapter in (self.pi, self.codex):
            if hasattr(adapter, "event_sink"):
                adapter.event_sink = self._adapter_event
        self._protocol_retries_base = state.budgets.protocol_retries_used
        self._protocol_retries_start = sum(
            getattr(adapter, "protocol_retries_used", 0) for adapter in (pi, codex)
        )

    # -- construction -------------------------------------------------------

    @classmethod
    def create(
        cls,
        repository: Path | str,
        request: str,
        task_kind_explicit: str | None = None,
        config: Config | None = None,
        pi=None,
        codex=None,
        ui: UI | None = None,
        renderer: ProgressRenderer | None = None,
        name: str | None = None,
    ) -> "Orchestrator":
        cfg = config or load_config()
        store = StateStore.create_session(
            repository,
            request,
            task_kind_explicit=task_kind_explicit,
            limits=cfg.budgets,
            name=name,
        )
        state = store.load_state()
        assert state is not None
        if pi is not None and codex is not None:
            pi_adapter, codex_adapter = pi, codex
        else:
            from agent_review.agents import build_adapters  # noqa: PLC0415

            pi_adapter, codex_adapter = build_adapters(
                cfg, repository=Path(store.repository), store=store
            )
        return cls(store, state, pi_adapter, codex_adapter, cfg, ui, renderer)

    @classmethod
    def resume(
        cls,
        repository: Path | str,
        session_id: str,
        config: Config | None = None,
        pi=None,
        codex=None,
        ui: UI | None = None,
        renderer: ProgressRenderer | None = None,
    ) -> "Orchestrator":
        cfg = config or load_config()
        store = StateStore(repository, session_id)
        store.recover_phase()
        state = store.load_state()
        if state is None:
            raise AgentError(f"session state missing or corrupt: {store.dir}")
        if pi is not None and codex is not None:
            pi_adapter, codex_adapter = pi, codex
        else:
            from agent_review.agents import build_adapters  # noqa: PLC0415

            pi_adapter, codex_adapter = build_adapters(
                cfg, repository=Path(state.repository), store=store
            )
        return cls(store, state, pi_adapter, codex_adapter, cfg, ui, renderer)

    # -- primitives ----------------------------------------------------------

    def event(self, name: str, **data) -> None:
        """Single progress/audit source: events.jsonl + CLI renderer."""
        finalized = self.store.append_event({"event": name, **data})
        self.renderer.handle(finalized)

    def _adapter_event(self, name: str, data: dict) -> None:
        self.event(name, **data)

    def agent_call(self, agent: str, action: str, fn):
        """Run one agent call with progress events and a heartbeat.

        The heartbeat only says the orchestrator is still waiting on a
        live call; it never implies model progress or success odds.
        """
        phase = self.state.phase.value
        started = time.monotonic()
        self.event("AGENT_CALL_STARTED", phase=phase, agent=agent, action=action)
        stop = threading.Event()

        def _beat() -> None:
            interval = self.renderer.heartbeat_interval
            if interval <= 0:
                return
            while not stop.wait(interval):
                self.event(
                    "AGENT_CALL_HEARTBEAT",
                    phase=phase,
                    agent=agent,
                    action=action,
                    seconds=round(time.monotonic() - started, 1),
                )

        thread = threading.Thread(target=_beat, daemon=True)
        thread.start()
        try:
            result = fn()
        except BaseException as exc:
            stop.set()
            thread.join(timeout=2.0)
            if isinstance(exc, KeyboardInterrupt):
                # User cancellation is not an agent failure (audit N101):
                # classify it separately so telemetry never counts Ctrl+C
                # as an agent-call failure.
                self.event(
                    "AGENT_CALL_INTERRUPTED",
                    phase=phase,
                    agent=agent,
                    action=action,
                    seconds=round(time.monotonic() - started, 1),
                )
            else:
                self.event(
                    "AGENT_CALL_FAILED",
                    phase=phase,
                    agent=agent,
                    action=action,
                    error=type(exc).__name__,
                    seconds=round(time.monotonic() - started, 1),
                )
            raise
        stop.set()
        thread.join(timeout=2.0)
        self.event(
            "AGENT_CALL_COMPLETED",
            phase=phase,
            agent=agent,
            action=action,
            seconds=round(time.monotonic() - started, 1),
        )
        return result

    def transition(self, new_phase: Phase, status: SessionStatus | None = None) -> None:
        assert_transition(self.state.phase, new_phase)
        self.state.phase = new_phase
        if status is not None:
            self.state.status = status
        self.store.save_state(self.state)

    def fail(self, reason: str) -> None:
        self.state.error = reason
        self.state.resume_phase = self.state.phase
        self.state.phase = Phase.FAILED
        self.state.status = SessionStatus.FAILED
        self.store.save_state(self.state)
        self.event("SESSION_FAILED", reason=reason)

    def handoff(self, reason: str, pending_questions=None) -> None:
        """Enter HUMAN_HANDOFF and persist a structured handoff package.

        V0.2 Capability E: the handoff is no longer only a one-line
        reason — ``handoff.md`` records why the workflow stopped, what
        the Human needs to decide or provide, the blocking issues, the
        relevant ACTIVE decisions, any derivable suggested options and
        the resumability boundary. It is an aid for the Human, never a
        mechanism for the orchestrator to invent decisions.
        """
        self.state.handoff_reason = reason
        self.state.phase = Phase.HUMAN_HANDOFF
        self.state.status = SessionStatus.HUMAN_HANDOFF
        self.store.save_state(self.state)
        self.event("SESSION_HUMAN_HANDOFF", reason=reason)
        try:
            from agent_review.rendering import render_handoff  # noqa: PLC0415

            issues = self.store.load_issues().issues
            decisions = self.store.load_decisions().decisions
            gate = self.store.load_gate_log().current
            package = render_handoff(
                self.state, issues, decisions, gate, reason,
                pending_questions=list(pending_questions or []),
            )
            self.store.write_text("handoff.md", package)
            self.event("HANDOFF_WRITTEN", path=str(self.store.dir / "handoff.md"))
        except Exception:
            # The handoff package is an aid; its failure must never mask
            # the terminal handoff state that is already persisted.
            pass

    def _handle_interrupt(self) -> None:
        # Best-effort child abort; adapters without processes no-op.
        for adapter in (self.pi, self.codex):
            try:
                adapter.abort()
            except Exception:
                pass
        resume_phase = self.state.phase
        self.state.resume_phase = resume_phase
        self.state.phase = Phase.INTERRUPTED
        self.state.status = SessionStatus.INTERRUPTED
        self.store.save_state(self.state)
        self.event("SESSION_INTERRUPTED", phase=resume_phase.value)

    # -- run loop -------------------------------------------------------------

    def run(self) -> int:
        # Idempotent terminal states.
        if self.state.phase == Phase.DONE and self.state.status == SessionStatus.DONE:
            return int(ExitCode.DONE)
        if (
            self.state.phase == Phase.HUMAN_HANDOFF
            and self.state.status == SessionStatus.HUMAN_HANDOFF
        ):
            return int(ExitCode.HUMAN_HANDOFF)

        self.renderer.banner(self.state)
        self._recover_if_needed()
        try:
            self._ensure_agent_capability()
            for _ in range(MAX_STEPS):
                code = self.step()
                self._sync_protocol_retries()
                if code is not None:
                    return int(code)
            self.fail("step budget exceeded (possible phase loop)")
            return int(ExitCode.FAILED)
        except KeyboardInterrupt:
            self._sync_protocol_retries()
            self._handle_interrupt()
            return int(ExitCode.INTERRUPTED)
        except (AgentError, ProtocolError) as exc:
            self._sync_protocol_retries()
            self.fail(str(exc))
            return int(ExitCode.FAILED)
        except Exception as exc:  # fail closed on any unexpected error
            self._sync_protocol_retries()
            self.fail(f"unexpected {type(exc).__name__}: {exc}")
            return int(ExitCode.FAILED)

    def _sync_protocol_retries(self) -> None:
        total = self._protocol_retries_base - self._protocol_retries_start
        for adapter in (self.pi, self.codex):
            total += getattr(adapter, "protocol_retries_used", 0)
        if total != self.state.budgets.protocol_retries_used:
            self.state.budgets.protocol_retries_used = total
            self.store.save_state(self.state)

    def _ensure_agent_capability(self) -> None:
        """Startup capability detection; skipped when only human input remains."""
        if self.state.phase in (
            Phase.WAITING_FOR_HUMAN,
            Phase.DONE,
            Phase.HUMAN_HANDOFF,
            Phase.FAILED,
            Phase.INTERRUPTED,
        ):
            return
        for adapter, agent in ((self.pi, "pi"), (self.codex, "codex")):
            ensure = getattr(adapter, "ensure_capability", None)
            if ensure is not None:
                self.agent_call(agent, "capability", ensure)

    def _recover_if_needed(self) -> None:
        status = self.state.status
        if status in (SessionStatus.INTERRUPTED, SessionStatus.FAILED):
            target = self.state.resume_phase or Phase.INIT
            self.state.phase = target
            self.state.status = SessionStatus.RUNNING
            self.state.resume_phase = None
            self.state.error = None
            self.store.save_state(self.state)
            self.event("SESSION_RESUMED", phase=target.value)

    def step(self) -> Optional[int]:
        self.store.begin_phase()
        try:
            code = self._step()
            self.store.commit_phase()
            return code
        except BaseException:
            self.store.recover_phase()
            # Keep the last known-good in-memory state when the reload itself
            # fails (corrupt/missing state.json): recovery already restored
            # the durable copy, and the original exception is re-raised below.
            reloaded = self.store.load_state()
            if reloaded is not None:
                self.state = reloaded
            raise

    def _step(self) -> Optional[int]:
        phase = self.state.phase
        if phase == Phase.DONE:
            return int(ExitCode.DONE)
        if phase == Phase.HUMAN_HANDOFF:
            return int(ExitCode.HUMAN_HANDOFF)
        if phase == Phase.FAILED:
            return int(ExitCode.FAILED)
        if phase == Phase.INTERRUPTED:
            return int(ExitCode.INTERRUPTED)

        self.event("PHASE_STARTED", phase=phase.value)
        if phase == Phase.INIT:
            from agent_review.phases import discover

            return discover.run_init(self)
        if phase == Phase.DISCOVER:
            from agent_review.phases import discover

            return discover.run(self)
        if phase == Phase.INVESTIGATE:
            from agent_review.phases import investigate

            return investigate.run(self)
        if phase == Phase.INTAKE:
            from agent_review.phases import intake

            return intake.run(self)
        if phase == Phase.WAITING_FOR_HUMAN:
            from agent_review.phases import human_gate

            return human_gate.run(self)
        if phase == Phase.DESIGN:
            from agent_review.phases import design

            return design.run(self)
        if phase == Phase.INITIAL_REVIEW:
            from agent_review.phases import review

            return review.run_initial(self)
        if phase == Phase.REVISION:
            from agent_review.phases import revision

            return revision.run(self)
        if phase == Phase.CLOSURE_REVIEW:
            from agent_review.phases import review

            return review.run_closure(self)
        if phase == Phase.ABLATION:
            from agent_review.phases import ablation

            return ablation.run(self)
        if phase == Phase.FINAL_REVIEW:
            from agent_review.phases import review

            return review.run_final(self)
        if phase == Phase.FINALIZE:
            from agent_review.phases import finalize

            return finalize.run(self)
        raise AgentError(f"unhandled phase: {phase}")
