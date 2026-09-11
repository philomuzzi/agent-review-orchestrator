"""Runtime progress rendering (V0.1).

The orchestrator's event stream is the single progress source: both the
CLI renderer and ``events.jsonl`` consume the same events. The renderer
is a pure projection of workflow facts; it never owns state, never
streams raw agent reasoning and never invents percentage progress.

Output levels (spec 8):

- DEFAULT: session banner, phase transitions, agent calls, heartbeats,
  phase result summaries, issue counts, Human Gate, retries, outcome.
- VERBOSE: DEFAULT plus artifact paths, issue IDs, task revision,
  protocol retry details, budget/state changes.
- QUIET: Human Gate / Handoff, errors and the final result only.
"""

from __future__ import annotations

import re
import sys
import threading
from datetime import datetime, timezone
from enum import Enum
from typing import IO, Any

# Neutral placeholder shown before a semantic task title exists (spec 4.2).
PLACEHOLDER_TITLE = "Current request"

# Presentation titles are bounded, single-line text regardless of what the
# agent or the user supplied (spec 3.3/4.2: the title is a projection, never
# free-form agent output). 80 chars comfortably exceeds the recommended
# 10-20 CJK characters while keeping tables and banners scannable.
MAX_TITLE_LENGTH = 80

SYMBOL_START = "→"
SYMBOL_DONE = "✓"
SYMBOL_GATE = "!"
SYMBOL_FAIL = "✗"
SYMBOL_RETRY = "↻"

# Deterministic agent-activity line per phase (no agent-invented text).
AGENT_ACTIVITY: dict[str, str] = {
    "DISCOVER": "Pi inspecting repository...",
    "INVESTIGATE": "Pi investigating root cause...",
    "DESIGN": "Pi designing...",
    "REVISION": "Pi revising design...",
    "ABLATION": "Pi simplifying the design (ablation)...",
    "INITIAL_REVIEW": "Codex reviewing proposal...",
    "CLOSURE_REVIEW": "Codex verifying revisions...",
    "FINAL_REVIEW": "Codex reviewing the ablated design...",
}

AGENT_NAMES = {"pi": "Pi", "codex": "Codex"}

# Terminal-session events always worth one line, even in --quiet.
QUIET_EVENTS = {
    "HUMAN_GATE_CREATED",
    "CONVERGENCE_GATE_CREATED",
    "HUMAN_GATE_WAITING_NONINTERACTIVE",
    "SESSION_DONE",
    "SESSION_HUMAN_HANDOFF",
    "SESSION_FAILED",
    "SESSION_INTERRUPTED",
}


class OutputLevel(str, Enum):
    DEFAULT = "default"
    VERBOSE = "verbose"
    QUIET = "quiet"


def sanitize_line(text: Any) -> str:
    """Coerce any value to safe single-line printable terminal text.

    This is the ONE host-owned presentation safety boundary for free text
    on the terminal (V0.1-RC3 B201): both the progress renderer and every
    CLI final exit summary normalize through this helper, so event-driven
    output and state-carried output can never obey different rules.

    Event payloads and state fields occasionally carry externally derived
    text (agent stderr tails in failure reasons, task titles, handoff
    reasons). Rendering must keep the one-line-per-fact contract: collapse
    all whitespace runs (newlines/tabs included) to single spaces, then drop
    any remaining control/non-printable characters (including ANSI escape
    bytes), keeping words separated. Normal Unicode/CJK text is preserved.
    """
    if isinstance(text, (list, tuple, set)):
        return " ".join(sanitize_line(item) for item in text)
    if not isinstance(text, str):
        text = str(text)
    # Collapse whitespace (newlines/tabs) to spaces first, then drop any
    # remaining control characters, keeping words separated.
    text = re.sub(r"\s+", " ", text)
    text = "".join(ch for ch in text if ch.isprintable())
    return re.sub(r"\s+", " ", text).strip()


def sanitize_title(raw: str | None) -> str:
    """Host-owned deterministic title normalization (spec 4.2).

    Applied before persistence: the semantic title and the user-supplied
    ``--name`` are presentation metadata, so the host bounds them to a
    single printable line of at most ``MAX_TITLE_LENGTH`` characters.
    Returns "" when nothing presentable remains (placeholder is used).
    """
    return sanitize_line(raw or "")[:MAX_TITLE_LENGTH]


def display_title(state) -> str:
    """Human-facing session label: explicit name > semantic title > placeholder."""
    return sanitize_title(getattr(state, "task_title", None)) or PLACEHOLDER_TITLE


def format_elapsed(seconds: float) -> str:
    """Wall-clock session elapsed as ``[mm:ss]`` (``[h:mm:ss]`` past an hour)."""
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"[{hours}:{minutes:02d}:{secs:02d}]"
    return f"[{minutes:02d}:{secs:02d}]"


def _parse_ts(ts: Any) -> datetime | None:
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts)
        except ValueError:
            return None
    if isinstance(ts, datetime):
        return ts
    return None


class ProgressRenderer:
    """Renders workflow events onto a terminal stream.

    Thread-safe: heartbeats arrive from a background thread while the
    main thread renders phase transitions.
    """

    def __init__(
        self,
        level: OutputLevel = OutputLevel.DEFAULT,
        stream: IO[str] | None = None,
        heartbeat_interval: float = 15.0,
        session_dir: str | None = None,
    ):
        self.level = level
        self.stream = stream  # None -> sys.stdout at write time
        self.heartbeat_interval = max(0.0, float(heartbeat_interval))
        self.session_dir = session_dir
        self._lock = threading.Lock()
        self._session_start: datetime | None = None
        self._phase_header_shown = False

    # -- plumbing -------------------------------------------------------------

    def _write(self, text: str) -> None:
        stream = self.stream if self.stream is not None else sys.stdout
        try:
            print(text, file=stream, flush=True)
        except Exception:
            # Rendering must never break the workflow (exotic consoles,
            # closed pipes). The event log remains authoritative.
            pass

    def banner(self, state) -> None:
        """Session header block (spec 6). Shown at run/resume start."""
        if self.level == OutputLevel.QUIET:
            return
        with self._lock:
            start = getattr(state, "created_at", None)
            if isinstance(start, datetime):
                self._session_start = (
                    start if start.tzinfo else start.replace(tzinfo=timezone.utc)
                )
            lines = [
                "Agent Review",
                f"Session: {state.session_id}",
                f"Task:    {display_title(state)}",
                f"Repo:    {state.repository}",
                f"Mode:    {state.task_kind.value}",
                "Author:  Pi",
                "Reviewer: Codex",
                "",
            ]
            self._write("\n".join(lines))

    def handle(self, event: dict) -> None:
        name = event.get("event", "")
        if self.level == OutputLevel.QUIET and name not in QUIET_EVENTS:
            return
        handler = getattr(self, f"_on_{name.lower()}", None)
        with self._lock:
            try:
                if handler is not None:
                    handler(event)
                else:
                    self.handle_verbose_fallback(event)
            except Exception:
                pass  # never let rendering break the workflow

    # -- helpers ----------------------------------------------------------------

    def _stamp(self, event: dict) -> str:
        ts = _parse_ts(event.get("ts"))
        if ts is None:
            ts = datetime.now(timezone.utc)
        if self._session_start is None:
            self._session_start = ts
        start = self._session_start
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        return format_elapsed((ts - start).total_seconds())

    def _artifact(self, name: str) -> str:
        if self.session_dir:
            from pathlib import Path

            return str(Path(self.session_dir) / name)
        return name

    def _verbose(self) -> bool:
        return self.level == OutputLevel.VERBOSE

    def _phase_line(self, event: dict, phase: str, symbol: str, summary: str = "") -> None:
        line = f"{self._stamp(event)} {symbol} {phase}"
        if summary:
            line += f" · {summary}"
        self._write(line)

    def _ensure_phase_header(self, event: dict, phase: str) -> None:
        if not self._phase_header_shown:
            self._phase_line(event, phase, SYMBOL_START)
            self._phase_header_shown = True

    # -- session lifecycle --------------------------------------------------------

    def _on_session_created(self, event: dict) -> None:
        self._session_start = _parse_ts(event.get("ts")) or self._session_start

    def _on_session_resumed(self, event: dict) -> None:
        phase = str(event.get("phase", ""))
        self._phase_header_shown = False
        self._write(f"{self._stamp(event)} {SYMBOL_START} resuming at {phase}")

    def _on_session_done(self, event: dict) -> None:
        self._phase_header_shown = False
        self._write(f"{self._stamp(event)} {SYMBOL_DONE} DONE · final.md generated")

    def _on_session_human_handoff(self, event: dict) -> None:
        self._phase_header_shown = False
        reason = sanitize_line(event.get("reason", "task-level boundary reached"))
        self._write(f"{self._stamp(event)} {SYMBOL_GATE} HUMAN_HANDOFF · {reason}")

    def _on_session_failed(self, event: dict) -> None:
        self._phase_header_shown = False
        reason = sanitize_line(event.get("reason", "unexpected failure"))
        self._write(f"{self._stamp(event)} {SYMBOL_FAIL} FAILED · {reason}")

    def _on_session_interrupted(self, event: dict) -> None:
        self._phase_header_shown = False
        phase = str(event.get("phase", ""))
        self._write(
            f"{self._stamp(event)} {SYMBOL_FAIL} INTERRUPTED during {phase} "
            "(Ctrl+C); state persisted, resume with 'review resume'"
        )

    # -- phases ---------------------------------------------------------------------

    def _on_phase_started(self, event: dict) -> None:
        phase = str(event.get("phase", ""))
        if phase in ("INIT", "WAITING_FOR_HUMAN"):
            return  # bookkeeping phase / rendered by the gate events
        self._phase_line(event, phase, SYMBOL_START)
        self._phase_header_shown = True

    def _on_discover_completed(self, event: dict) -> None:
        self._phase_header_shown = False
        components = event.get("components", 0)
        kind = event.get("task_kind", "")
        self._phase_line(
            event, "DISCOVER", SYMBOL_DONE, f"{components} relevant components · {kind}"
        )

    def _on_investigate_completed(self, event: dict) -> None:
        self._phase_header_shown = False
        status = event.get("root_cause_status", "")
        self._phase_line(event, "INVESTIGATE", SYMBOL_DONE, f"root cause {status}")

    def _on_task_contract_created(self, event: dict) -> None:
        self._phase_header_shown = False
        revision = event.get("task_revision", "")
        summary = "change contract assembled"
        if self._verbose():
            summary += f" · task revision {revision} · {self._artifact('task.md')}"
        self._phase_line(event, "INTAKE", SYMBOL_DONE, summary)

    def _on_proposal_created(self, event: dict) -> None:
        self._phase_header_shown = False
        revision = event.get("based_on_task_revision", "")
        summary = "proposal.md generated"
        if self._verbose():
            summary += f" · based on task revision {revision} · {self._artifact('proposal.md')}"
        self._phase_line(event, "DESIGN", SYMBOL_DONE, summary)

    def _on_revision_completed(self, event: dict) -> None:
        self._phase_header_shown = False
        addressed = event.get("addressed", 0)
        self._phase_line(event, "REVISION", SYMBOL_DONE, f"{addressed} issue(s) addressed")

    def _on_ablation_completed(self, event: dict) -> None:
        self._phase_header_shown = False
        removed = event.get("removed", 0)
        self._phase_line(event, "ABLATION", SYMBOL_DONE, f"{removed} item(s) removed")

    def _on_initial_review_completed(self, event: dict) -> None:
        self._phase_header_shown = False
        self._phase_line(event, "INITIAL_REVIEW", SYMBOL_DONE, self._issue_summary(event))

    def _on_closure_review_completed(self, event: dict) -> None:
        self._phase_header_shown = False
        resolved = event.get("resolved")
        outcomes = event.get("outcomes", 0)
        new_blocking = int(event.get("new_blocking", 0))
        remaining = event.get("remaining")
        if resolved is not None and new_blocking == 0 and remaining == 0:
            summary = f"{resolved} of {outcomes} blocker(s) verified resolved"
        else:
            # Post-PASS truth: include new blockers and unresolved ones so a
            # closure that verifies everything but introduces a regression
            # never renders as an unqualified success.
            parts = [f"{resolved if resolved is not None else 0} of {outcomes} verified"]
            if new_blocking:
                parts.append(f"{new_blocking} new blocker(s)")
            if remaining:
                parts.append(f"{remaining} blocker(s) unresolved")
            summary = " · ".join(parts)
        self._phase_line(event, "CLOSURE_REVIEW", SYMBOL_DONE, summary)

    def _on_final_review_completed(self, event: dict) -> None:
        self._phase_header_shown = False
        # Workflow truth, not the reviewer verdict: PASS requires the
        # mechanical rule too, so "requirement satisfied" can only appear
        # when the orchestrator has actually computed a pass.
        passed = event.get("passed")
        remaining = event.get("remaining")
        if passed:
            summary = "requirement satisfied · PASS"
        else:
            summary = "requirement check not passed"
            if remaining:
                summary += f" · {remaining} blocker(s) unresolved"
        if self._verbose() and event.get("satisfies_requirement") is not None:
            summary += (
                f" · reviewer verdict: {'satisfied' if event['satisfies_requirement'] else 'not satisfied'}"
            )
        symbol = SYMBOL_DONE if passed else SYMBOL_GATE
        self._phase_line(event, "FINAL_REVIEW", symbol, summary)

    def _on_final_md_written(self, event: dict) -> None:
        self._phase_header_shown = False
        summary = "final.md generated"
        if self._verbose():
            summary = self._artifact("final.md")
        self._phase_line(event, "FINALIZE", SYMBOL_DONE, summary)

    def _issue_summary(self, event: dict) -> str:
        blocking = event.get("blocking")
        non_blocking = event.get("non_blocking")
        if blocking is None or non_blocking is None:
            issues = event.get("issues", 0)
            return f"{issues} issue(s) raised"
        summary = f"{blocking} blocking · {non_blocking} non-blocking"
        if self._verbose() and event.get("issue_ids"):
            summary += f" ({', '.join(event['issue_ids'])})"
        return summary

    # -- agent calls ------------------------------------------------------------------

    def _on_agent_call_started(self, event: dict) -> None:
        phase = str(event.get("phase", ""))
        agent = AGENT_NAMES.get(str(event.get("agent", "")), "Agent")
        action = str(event.get("action", ""))
        if action == "capability":
            self._write(f"{self._stamp(event)} {SYMBOL_START} checking {agent} availability...")
            return
        if action == "human_authority_check":
            self._ensure_phase_header(event, phase)
            self._write(f"         {agent} checking human authority coverage...")
            return
        if phase in AGENT_ACTIVITY:
            self._ensure_phase_header(event, phase)
            self._write(f"         {AGENT_ACTIVITY[phase]}")

    def _on_agent_call_completed(self, event: dict) -> None:
        if self._verbose():
            action = str(event.get("action", ""))
            agent = AGENT_NAMES.get(str(event.get("agent", "")), "agent")
            seconds = event.get("seconds", 0)
            if action == "capability":
                self._write(f"         {agent} ready ({seconds}s)")
            else:
                self._write(f"         {agent} call finished ({seconds}s)")

    def _on_agent_call_heartbeat(self, event: dict) -> None:
        # Heartbeat means ONLY: the orchestrator is still waiting on a live
        # agent call. No progress percentage, no success probability.
        agent = AGENT_NAMES.get(str(event.get("agent", "")), "Agent")
        seconds = int(event.get("seconds", 0))
        action = str(event.get("action", ""))
        if action == "capability":
            self._write(f"{self._stamp(event)} {agent} availability check... {seconds}s")
            return
        phase = str(event.get("phase", ""))
        self._write(f"{self._stamp(event)} {phase} · {agent} still working... {seconds}s")

    def _on_agent_call_failed(self, event: dict) -> None:
        agent = AGENT_NAMES.get(str(event.get("agent", "")), "Agent")
        error = sanitize_line(event.get("error", ""))
        self._write(f"{self._stamp(event)} {SYMBOL_FAIL} {agent} call failed: {error}")

    def _on_agent_call_interrupted(self, event: dict) -> None:
        # User cancellation is not an agent failure (N101); the terminal
        # SESSION_INTERRUPTED line carries the user-facing notice.
        if not self._verbose():
            return
        agent = AGENT_NAMES.get(str(event.get("agent", "")), "Agent")
        self._write(
            f"         {agent} call interrupted by user after "
            f"{event.get('seconds', 0)}s"
        )

    # -- issues / retry / gates ---------------------------------------------------------

    def _on_issues_ingested(self, event: dict) -> None:
        if not self._verbose():
            return
        blocking = event.get("blocking", 0)
        non_blocking = event.get("non_blocking", 0)
        provenance = event.get("provenance", "")
        ids = ", ".join(event.get("issue_ids", [])) or "-"
        self._write(
            f"         issues ingested ({provenance}): {blocking} blocking, "
            f"{non_blocking} non-blocking [{ids}]"
        )

    def _on_issue_created(self, event: dict) -> None:
        if not self._verbose():
            return
        issue_id = event.get("issue_id", "")
        severity = event.get("severity", "")
        category = event.get("category", "")
        self._write(f"         issue {issue_id}: {severity} {category}")

    def _on_issue_resolved(self, event: dict) -> None:
        if not self._verbose():
            return
        self._write(f"         issue {event.get('issue_id', '')} RESOLVED")

    def _on_protocol_retry(self, event: dict) -> None:
        attempt = event.get("next_attempt", "?")
        agent = AGENT_NAMES.get(str(event.get("agent", "")), "agent")
        phase = event.get("phase", "")
        line = (
            f"{self._stamp(event)} {SYMBOL_RETRY} PROTOCOL RETRY · {phase}: "
            f"re-requesting structured output from {agent} (attempt {attempt})"
        )
        if self._verbose() and event.get("schema"):
            line += f" · schema {event['schema']}"
        self._write(line)

    def _on_protocol_retry_succeeded(self, event: dict) -> None:
        if not self._verbose():
            return
        agent = AGENT_NAMES.get(str(event.get("agent", "")), "agent")
        self._write(
            f"         protocol repair succeeded for {agent} "
            f"(attempt {event.get('attempt', '?')})"
        )

    def _on_protocol_retry_exhausted(self, event: dict) -> None:
        self._write(
            f"{self._stamp(event)} {SYMBOL_FAIL} protocol repair budget exhausted "
            f"({event.get('attempts', '?')} attempt(s))"
        )

    def _on_human_gate_created(self, event: dict) -> None:
        self._phase_header_shown = False
        questions = event.get("questions", [])
        gate_id = event.get("gate_id", "")
        line = f"{self._stamp(event)} {SYMBOL_GATE} HUMAN GATE · {len(questions)} decision(s) required"
        if self._verbose():
            line += f" [{gate_id}: {', '.join(questions)}]"
        self._write(line)

    def _on_convergence_gate_created(self, event: dict) -> None:
        # V0.2: a review-discovered Human decision re-enters a bounded
        # gate instead of terminating the session.
        self._phase_header_shown = False
        gate_id = event.get("gate_id", "")
        questions = event.get("questions", [])
        source = event.get("source_issue_ids", [])
        semantics = sanitize_line(event.get("resume_semantics", ""))
        line = (
            f"{self._stamp(event)} {SYMBOL_GATE} CONVERGENCE GATE · "
            f"{len(questions)} decision(s) from review issue(s) "
            f"{', '.join(source) or '-'}"
        )
        if semantics:
            line += f" · establishes {semantics} decision(s)"
        if self._verbose():
            line += f" [{gate_id}: {', '.join(questions)}]"
        self._write(line)

    def _on_issue_need_human(self, event: dict) -> None:
        # Routing fact (V0.2 audit): OPEN -> NEED_HUMAN never happens
        # silently; the line makes the authority question visible.
        issue_id = event.get("issue_id", "")
        category = event.get("category", "")
        self._write(
            f"{self._stamp(event)} {SYMBOL_GATE} issue {issue_id} requires "
            f"human authority ({category}) — checking decision coverage"
        )

    def _on_issue_covered_by_decision(self, event: dict) -> None:
        # The PROD-001 trust fix: requirement blockers already decided by
        # ACTIVE Human Decisions route to revision, not to termination.
        issue_id = event.get("issue_id", "")
        decision_ids = event.get("decision_ids", [])
        self._write(
            f"{self._stamp(event)} {SYMBOL_DONE} issue {issue_id} already "
            f"decided by {', '.join(decision_ids) or '-'} · routed as a "
            "solution gap"
        )

    def _on_handoff_write_failed(self, event: dict) -> None:
        # N201: even the minimal fallback failed. The authoritative
        # HUMAN_HANDOFF state stays persisted; make the packaging gap
        # visible instead of silently losing the durable package.
        self._write(
            f"{self._stamp(event)} {SYMBOL_FAIL} handoff.md could not be "
            "written; HUMAN_HANDOFF state remains authoritative "
            "(see state.json / events.jsonl)"
        )

    def _on_human_gate_waiting_noninteractive(self, event: dict) -> None:
        self._write(
            f"{self._stamp(event)} {SYMBOL_GATE} HUMAN GATE waiting for answers "
            "(non-interactive); packet persisted — answer via 'review resume'"
        )

    def _on_human_gate_closed(self, event: dict) -> None:
        if not self._verbose():
            return
        self._write(f"         gate {event.get('gate_id', '')} closed")

    def _on_task_revision_incremented(self, event: dict) -> None:
        revision = event.get("task_revision", "")
        line = (
            f"{self._stamp(event)} {SYMBOL_RETRY} task revision {revision} · "
            "design basis changed"
        )
        # Render only facts that actually happened: the STALE archive notice
        # appears only when a proposal really was archived (N105).
        if event.get("archived"):
            line += " · old proposal archived STALE"
        self._write(line)

    def _on_task_title_set(self, event: dict) -> None:
        title = sanitize_line(event.get("title", ""))
        if title and title != PLACEHOLDER_TITLE:
            self._write(f"         task title: {title}")

    # -- verbose-only state/budget events ---------------------------------------------

    _VERBOSE_EVENTS = {
        "DECISION_APPLIED",
        "DECISION_SUPERSEDED",
        "CUSTOM_DECISION_CAPTURED",
        "HUMAN_CANDIDATE_SUPPRESSED",
        "REQUIREMENT_TOO_AMBIGUOUS",
        "HUMAN_GATE_ANSWERS_VALIDATED",
        "HUMAN_GATE_ASKING",
        "ISSUE_HUMAN_AUTHORITY_CHECK_STARTED",
        "HANDOFF_WRITTEN",
        "PROPOSAL_STALE",
        "ISSUE_ADDRESSED",
        "ISSUE_SUPERSEDED",
        "ABLATION_TRIGGERED",
        "PASS_COMPUTED",
        "SESSION_CREATED",
    }

    def handle_verbose_fallback(self, event: dict) -> None:
        """Generic one-line dump for verbose-only domain events."""
        if not self._verbose():
            return
        name = event.get("event", "")
        if name not in self._VERBOSE_EVENTS:
            return
        details = {
            k: v
            for k, v in event.items()
            if k not in ("event", "ts")
        }
        suffix = " ".join(f"{k}={sanitize_line(v)}" for k, v in sorted(details.items()))
        self._write(f"         · {name} {suffix}".rstrip())


class NullRenderer(ProgressRenderer):
    """No-op renderer: deterministic core tests stay silent by default."""

    def __init__(self) -> None:  # noqa: D107 - trivial
        super().__init__(level=OutputLevel.DEFAULT, stream=None, heartbeat_interval=0.0)

    def banner(self, state) -> None:
        return

    def handle(self, event: dict) -> None:
        return
