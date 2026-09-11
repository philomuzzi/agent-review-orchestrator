# Agent Review Orchestrator V0.1 Implementation Audit

**Status:** V0.1-RC2 implementation; real-agent validated
**Audit Type:** Static + dynamic implementation review against `V0_1_RUNTIME_PROGRESS_VISIBILITY_SPEC.md` and the V0 safety boundary (PASS rule, Human Authority, Issue lifecycle, budgets, recovery, read-only agents)

**RC1 baseline:** commit `24eb2b5` ("feat: implement V0.1 runtime progress visibility + session presentation").

## RC2 remediation record — 2026-09-11

The RC1 findings below are retained as the audit baseline. B001–B003 are
addressed in code with deterministic regression coverage in
`tests/unit/test_v01_rc2_regressions.py`. No V0 workflow semantics, safety
boundaries, event-source architecture or rendering levels were redesigned;
all fixes are host-side sanitization, fail-closed lookup hardening and
local convenience additions.

| Finding / family | Confirmed root cause (verified by probe) | RC2 correction | Remaining boundary |
| --- | --- | --- | --- |
| B001 / presentation trust | `DiscoveryResult.task_title` (agent free text) and `--name` were persisted unsanitized; a probe session persisted a 317-char title containing `\n`/`\t`, splitting `status --list` rows and the banner/header blocks. | Host-owned `sanitize_title()` (single printable line, whitespace collapsed, control chars removed, ≤80 chars) applied at both ingestion points (`discover` phase, `StateStore.create_session`); `display_title()` re-sanitizes on render so legacy/edited states stay safe. | The title is still agent-derived text; the host bounds its form, not its truth. Title edits remain presentation-only (regression-tested). |
| B002 / renderer line-safety | Event payloads with newlines (e.g. `SESSION_FAILED` reasons embedding codex stderr tails) rendered one event as 3 terminal lines, breaking the one-line-per-fact contract in every level including `--quiet`. | `_one_line()` (whitespace collapse + control-char strip, list-aware) applied to every free-text render field (reasons, errors, titles) and to the verbose fallback dump. | Payload text is bounded to one line, not semantically rewritten. |
| B003 / lookup resilience | `StateStore.load_state()` raised on corrupt `state.json`; `load_state_of()` caught only `FileNotFoundError` — one corrupt session crashed `review status`, `status --list` (the "(corrupt state)" row was dead code), `show` and `resume` with tracebacks. | `load_state()`/`load_state_of()` return `None` for missing/unreadable/invalid state (fail closed); CLI `resume` catches `AgentError`/`ValueError` from construction into a clean exit 30; `step()` keeps the last known-good in-memory state when a post-recovery reload fails; `load_proposal()` treats unknown revision state as "no active design". `recover_phase()` still hard-fails on an invalid checkpoint (V0-RC2 semantics unchanged). | A corrupt session is reported, not repaired; recovery truth remains the phase checkpoint. |
| N002 / id format | Same-second id collision appended `-2` (`20260911-010101-aaaa-2`), breaking the compact-format invariant. | Collision retry regenerates a fresh `YYYYMMDD-HHMMSS-xxxx` id (bounded loop). | Random suffix; collision probability unchanged (~2^-16 per pair). |
| N001 / convenience | `review --version` exited 2 with a usage error; no way to inspect the event stream per session. | `review --version` prints package name+version (exit 0); `review show events` prints `events.jsonl`. Both recorded as V0 lessons §7.3 candidates. | — |
| N003 / CLI parity | `review resume` ignored a config file argument (`run` had `--config`, resume did not). | `resume --config PATH` accepted, same resolution order. | Config is still not persisted per session (V0 audit N003 stays deferred). |

Regression coverage added (19 tests): title sanitization unit matrix; evil
DISCOVER title sanitized before persist (state + `TASK_TITLE_SET` event);
sanitized `--name`; hostile legacy state re-sanitized on display;
`status --list`/`status` rows stay single-line under a newline title;
renderer collapse at default/quiet/verbose for FAILED/HANDOFF/agent-failure
/title/verbose-fallback payloads; corrupt-session degradation for
`status --list` / `status` / `show` / `resume` (clean exit 30, no
traceback); `load_state` lenient vs `recover_phase` strict; collision-safe
compact id; `--version`; `show events`; `resume --config`; title rename
never changes session identity or phase.

Final deterministic verification: `python -m pytest --basetemp=.test-tmp/rc2-final
-p no:cacheprovider` passed **171 tests** (152 RC1 + 19 RC2 regressions),
**2 opt-in real smoke tests skipped** (17.5s). `review --version`,
`review --help`, and `git diff --check` passed.

Real smoke (`AGENT_REVIEW_SMOKE=1`): **2 passed** in 148.5s against
pi 0.85.1 and codex-cli 0.154.0 (capability probes, RPC framing, exec
schema validation, read-only probes).

Real-agent E2E (pi 0.85.1 + codex 0.154.0, real adapters, real renderer,
only the human gate keystrokes scripted):

1. `20260911-014137-2ed9` (named「同步任务步骤重试上限」): capability
   checks visible with heartbeats (pi 8s, codex 64s incl. 15/30/45s
   beats) → DISCOVER heartbeats → 5 candidates, REQUIREMENT_TOO_AMBIGUOUS
   asked 3, gate answered → task revision 2 rendered (↻ STALE archive
   notice) → deferred candidates re-surfaced as gate 2 (budget 2/2),
   answered → task revision 3 → DESIGN with 15s cadence heartbeats →
   INITIAL_REVIEW 2 blocking → R001 (FACT blocker) classified NEED_HUMAN
   → HUMAN_HANDOFF exit 10. Correct V0 boundary behavior: reviewer
   semantics the agent may not answer; handoff preserved the scene and
   `status` reports it scan-friendly.
2. `20260911-014955-a907` (no `--name`): banner showed the
   `Current request` placeholder before DISCOVER, then persisted the
   semantic title 「README 补充 run_steps 参数行为说明」(13 chars, semantic,
   not request truncation) → one SCOPE gate (docs language) answered →
   revision 2 → DESIGN → INITIAL_REVIEW 0 blocking → FINALIZE →
   **DONE exit 0**; `status --list` shows both sessions (id, title,
   outcome) and the new `show events` streams the real event log.

Both Windows console guards (rich legacy Win32, UTF-8 stdio) held across
all rendered output paths; no Errno 22, no native crash, no mojibake in
console or redirected files.

V0.1-RC2 is ready for the next validation gate: a real Shopify repository
session. Known limitations are listed under "Remaining limitations" below;
none blocks that gate.

N004–N008 remain deferred as recorded below. No V0.1 non-goal was added.

## Conclusion

The V0.1 implementation has the correct architecture, confirmed unchanged
in RC2:

- single event source (`Orchestrator.event()` → `events.jsonl` + renderer,
  adapter protocol retries via `event_sink`);
- orchestrator-owned heartbeats (stop-event daemon thread per agent call,
  capability probes included);
- renderer as a pure projection with deterministic level filtering;
- session identity (`YYYYMMDD-HHMMSS-xxxx`) fully separated from the
  presentation title (`--name` > DISCOVER > placeholder).

The RC1 gaps were all in the trust boundary between agent-supplied text
and persisted/rendered presentation metadata, plus fail-closed lookup
behavior around corrupt sessions — exactly the class of defect the V0
audit pattern predicts for any new data path into the CLI surface.

## Blocking Issues (RC1 baseline)

## B001 — Agent-supplied task_title persisted without host sanitization

**Problem**

`discover` persists `result.task_title` verbatim into `state.json`, and
`--name` is only `.strip()`ed. Verified by probe: a scripted DISCOVER
reply produced a 317-character title containing `\n` and `\t`, which then
split `status --list` rows and `status`/banner header blocks into
multiple lines.

Why blocking: the title is rendered by every session-oriented command
(spec 4.4) and `status --list` is the scan surface (spec AC12). Agent
free text must never control terminal formatting (spec 3.3: default
output displays workflow facts; presentation is a projection).

**Expected behavior**

- The host deterministically bounds the title before persistence: single
  printable line, whitespace collapsed, control characters removed,
  length capped.
- Empty-after-sanitize falls back to the placeholder, never to request
  truncation.

## B002 — Renderer emits multi-line output for single events

**Problem**

`_on_session_failed` / `_on_session_human_handoff` /
`_on_agent_call_failed` / `_on_task_title_set` interpolate payload strings
directly. Failure reasons embed agent stderr tails (e.g. codex exec
error output), which contain newlines. Verified by probe: one
`SESSION_FAILED` event rendered as 3 terminal lines at default level;
`--quiet` is equally affected.

Why blocking: violates the spec §6/§8 information model (one concise line
per workflow fact) and the deterministic-output guarantee (AC6) that CI
consumers rely on.

**Expected behavior**

- Every rendered event occupies exactly one line regardless of payload
  content; whitespace collapses to single spaces, control characters are
  dropped.

## B003 — A corrupt session crashes all session lookup paths

**Problem**

`StateStore.load_state()` raises on unparseable `state.json`;
`load_state_of()` caught only `FileNotFoundError`. Verified by probe:
with one corrupt session present, `review status` and `review
status --list` exit 1 with an unhandled exception; the "(corrupt state)"
list row was unreachable dead code; `show` and `resume` traceback the
same way.

Why blocking: V0's fail-closed discipline requires clean, explicit
failure messages, and V0.1's own acceptance criterion (AC12, scan-friendly
recent sessions) requires one bad session not to hide the others.

**Expected behavior**

- Missing/unreadable/invalid state is surfaced as `None` to lookup paths;
  CLI commands degrade to explicit FAILED messages (exit 30);
  `status --list` keeps listing valid sessions and marks corrupt ones;
  checkpoint recovery keeps hard-failing on invalid checkpoints.

# Non-blocking Improvements

## N001 — Convenience commands (addressed in RC2)

`review --version` (exit-2 usage error in RC1) and a per-session event
viewer. Both were recorded as candidates in V0 lessons §7.3. Added:
`review --version`, `review show events`.

## N002 — Session-id collision fallback broke the compact format (addressed in RC2)

The RC1 fallback appended `-2`, producing ids that violate the
`YYYYMMDD-HHMMSS-xxxx` invariant the tests and presentation rely on.
RC2 regenerates a fresh random suffix instead.

## N003 — `resume` config parity (addressed in RC2)

`review resume` now accepts `--config PATH` like `review run`. Persisting
the creation config inside the session remains deferred (V0 audit N003).

## N004 — Event-name mapping vs spec §5 (documented, no change)

The spec's event list is illustrative; the implementation emits a stable
superset with different names: `HUMAN_GATE_CREATED` (vs
`HUMAN_GATE_OPENED`), `SESSION_DONE` (vs `SESSION_COMPLETED`),
`SESSION_HUMAN_HANDOFF` (vs `SESSION_HANDOFF`), and per-phase
`*_COMPLETED` events (vs a generic `PHASE_COMPLETED`). Renaming now would
churn the event-stream contract for zero behavioral gain; V0.3 telemetry
consumes the implemented names. Recorded here as the authoritative
mapping.

## N005 — Heartbeat volume in events.jsonl (deferred to V0.3)

Heartbeats are deliberately persisted (single event source, spec 3.5).
~230 events per real session is acceptable for V0.1; sampling/throttling
policy is a telemetry aggregation decision → V0.3.

## N006 — Telemetry aggregation (deferred to V0.3)

Phase/agent duration distributions, retry concentration by schema/phase,
heartbeat-density vs stuck-call discrimination, resume success rates.
The event stream already carries the required fields; building the
aggregator is V0.3 scope.

## N007 — NEED_HUMAN decision-option packets (deferred)

Reviewer NEED_HUMAN issues carry no option packet, so V0 hands off
instead of opening a resumable gate (observed again in the RC2 real E2E,
session `20260911-014137-2ed9`, R001). Letting reviewers attach decision
options changes the issue protocol and reviewer responsibilities → defer
to the V0.5 role-assignment work stream, per V0 lessons §5.3.

## N008 — PowerShell 5.1 OEM(936) pipe decoding (documented platform boundary)

PS `| Select-Object` decodes UTF-8 bytes as GBK; emitter-side cannot
satisfy msys (UTF-8) and PS pipes simultaneously. Unchanged; see V0
lessons §7.3.2.

# Remaining limitations (RC2)

1. Heartbeat-vs-terminal-event ordering: a final heartbeat may land after
   the terminal event (thread timing); cosmetic, semantics unaffected.
2. One workflow owner per session; no concurrent-writer or power-loss
   guarantee beyond atomic single-file writes + phase checkpoints (V0
   boundary).
3. Sessions with status FAILED remain resumable by design; lookup prefers
   RUNNING sessions for the default target.
4. Corrupt sessions are reported, never repaired; recovery truth is the
   phase checkpoint.
5. NEED_HUMAN handoffs still require a human to read `issues.json`
   (N007).

# Next Validation Gate

Run one real Shopify repository session through the installed CLI:

```bash
cd <shopify-repo>
review --name "<short title>" "<well-scoped change request>"
```

Validate that: progress remains continuously readable in a long real
run (heartbeats ≤15s cadence), gates/packets are answerable via
`review resume`, `status --list` and `show events` make the session
recognizable later without reading the original request, and any
handoff/protocol failure resumes cleanly.
