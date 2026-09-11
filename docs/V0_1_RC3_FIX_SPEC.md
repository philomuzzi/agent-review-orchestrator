# Agent Review Orchestrator V0.1 RC3 Remediation Specification

**Status:** Required before final Shopify product validation
**Baseline:** V0.1-RC2 (`21dca9d020c4003adfc6346b3385ccab0faf6619`)
**Scope:** Three remaining runtime/session presentation defects found after RC2 review

---

## 1. Goal

V0.1-RC2 resolved the RC1 blockers around session selection, review-progress truth, and task-title safety. A follow-up review found three remaining inconsistencies in the human-facing runtime/session layer.

RC3 must close these gaps without changing V0 workflow semantics, PASS rules, Human Authority, Issue lifecycle, budgets, recovery semantics, or agent permissions.

The guiding rule is:

> Human-facing presentation may be derived from workflow state, but every terminal surface must obey the same host-owned safety and consistency boundaries.

---

## 2. Blocking Findings

### B201 — CLI final exit summary bypasses the presentation safety boundary

#### Problem

`ProgressRenderer` sanitizes free-text event payloads through the host-owned one-line presentation boundary, but the CLI `_report()` path renders `state.handoff_reason` and `state.error` directly when printing final exit summaries.

This creates two presentation paths with different guarantees:

```text
Event -> ProgressRenderer -> sanitized
State -> CLI _report()     -> raw free text
```

A failure or handoff reason may contain agent-derived text such as stderr tails or unresolved evidence. Newlines, tabs, control characters, or terminal escape sequences can therefore reappear in the final CLI summary even when the corresponding progress event was rendered safely.

#### Required correction

Create or reuse one public host-owned terminal-text normalization helper and apply it consistently to all free-text terminal presentation paths, including final exit summaries.

At minimum:

- `FAILED` summary reason must be normalized;
- `HUMAN_HANDOFF` summary reason must be normalized;
- any terminal summary that embeds externally derived/state-carried free text must use the same boundary;
- do not duplicate subtly different sanitization logic in multiple modules.

The helper must preserve normal Unicode/CJK text while collapsing multiline/control content into safe single-line output.

#### Acceptance criteria

1. A `FAILED` reason containing `\n`, `\t`, control characters, or ANSI escape bytes produces one safe final CLI summary line.
2. A `HUMAN_HANDOFF` reason with equivalent hostile content also produces one safe final CLI summary line.
3. The rendered progress event and the final CLI exit summary obey the same safety rules.
4. Normal Chinese/English reasons remain readable.
5. Deterministic CLI-level regression tests exercise the complete `_report()` path, not only `ProgressRenderer` replay.

---

### B202 — `review show` does not truly fail closed for corrupt session state

#### Problem

RC2 made `load_state()` fail closed and added clean corrupt-session handling, but `review show` currently reads the requested artifact before validating session state.

This means a corrupt session can still return success when the artifact exists:

```text
valid final.md / events.jsonl
+
corrupt state.json

review show final <session>
```

The existing corrupt-session test can pass simply because the requested artifact is absent, so it does not prove the intended state-integrity boundary.

#### Required correction

For session-oriented `show` commands, validate the selected session state before emitting the requested artifact.

At minimum:

- explicit corrupt session -> clean exit 30;
- no traceback;
- no artifact body emitted before the corruption is detected;
- behavior must be consistent for `final`, `gate`, `task`, `proposal`, `issues`, and `events` unless a future explicit recovery/debug command is designed separately.

Do not attempt automatic state repair in RC3.

#### Acceptance criteria

1. Create a valid completed session with an existing `final.md`, then corrupt `state.json`; `review show final <id>` exits 30 and emits no final artifact body.
2. Repeat with another existing artifact such as `events.jsonl`; it also fails closed.
3. Missing/corrupt state produces a concise explicit message with no traceback.
4. Healthy sessions keep existing `show` behavior unchanged.
5. Regression tests prove state validation happens before artifact output.

---

### B203 — Session ID timestamp must use host local time, not UTC wall-clock text

#### Problem

The compact session id is human-facing presentation metadata:

```text
YYYYMMDD-HHMMSS-xxxx
```

RC2 currently generates the timestamp portion from UTC. For a user running the CLI in a non-UTC timezone, the directory/session id appears to show the wrong clock time even though the underlying session is correct.

This is especially confusing because the timestamp has no timezone suffix and visually reads like local wall-clock time.

#### Required correction

Generate the timestamp portion of new session ids from the **host machine's local wall-clock time**.

Recommended implementation shape:

```python
datetime.now().astimezone()
```

or an equivalent injectable/testable local-clock helper.

Important separation of concerns:

- session id timestamp = human-readable local wall-clock presentation;
- `state.created_at` / `updated_at` = authoritative timezone-aware persisted timestamps used for ordering, recovery decisions, and future telemetry;
- session resolution must continue to sort by persisted metadata, never by the session-id timestamp or directory name.

Changing the session-id clock must not alter existing session ordering semantics.

#### Acceptance criteria

1. In a non-UTC timezone, a newly generated session id reflects the host local date/time, not UTC wall time.
2. Format remains exactly `YYYYMMDD-HHMMSS-xxxx`.
3. The random suffix and collision handling remain unchanged in semantics.
4. Existing sessions are not renamed or migrated.
5. `state.created_at` remains timezone-aware and authoritative for recency ordering.
6. `latest_session`, default `resume/status/show`, and `status --list` continue to resolve by persisted metadata rather than the visible session-id clock.
7. Tests use an injected/controlled local timezone or clock and do not depend on the CI machine's timezone.

---

## 3. Implementation Constraints

RC3 must preserve:

- deterministic Orchestrator workflow control;
- mechanical PASS semantics;
- Human Gate and Human Authority rules;
- Issue lifecycle;
- revision / ablation / human / protocol budgets;
- phase checkpoint recovery;
- read-only Pi/Codex guarantees;
- V0.1 progress event model and output levels;
- short stable session IDs;
- semantic `task_title` behavior;
- existing Windows console hardening.

Do not solve these findings by broad CLI or state-machine redesign.

---

## 4. Tests Required

Add focused deterministic regressions for all three blockers.

Minimum coverage:

```text
B201
- full CLI FAILED exit summary with multiline/control reason
- full CLI HUMAN_HANDOFF summary with multiline/control reason

B202
- completed session + existing final.md + corrupt state.json -> show final fails closed
- existing events.jsonl + corrupt state.json -> show events fails closed
- healthy show paths still work

B203
- controlled non-UTC local clock -> session id uses local wall time
- session id retains compact format
- persisted created_at remains timezone-aware
- ordering still follows created_at when visible id times/suffixes would suggest otherwise
```

Run the complete deterministic suite after the focused regressions.

Where the environment supports it, rerun real Pi/Codex smoke. A new full business E2E is not required solely for these local RC3 fixes; the next real Shopify workflow is the product-validation gate after RC3 review.

---

## 5. Documentation Updates

When RC3 is complete:

1. Append an RC3 remediation/verification record to `docs/V0_1_IMPLEMENTATION_AUDIT.md`.
2. Add any reusable implementation lesson to `docs/V0_LESSONS_LEARNED.md`.
3. If CLI-visible behavior changed materially, update `README.md` only where needed.

The RC1/RC2 history must remain intact rather than being rewritten away.

---

## 6. RC3 Exit Criteria

V0.1-RC3 is complete when all of the following are true:

1. Every terminal free-text exit summary crosses one shared host-owned presentation safety boundary.
2. `review show` cannot emit session artifacts from a corrupt session state.
3. New session ids display the host machine's local wall-clock time.
4. Persisted timestamps remain authoritative for recency/session resolution.
5. Focused RC3 regressions pass.
6. The full deterministic suite passes with no V0/V0.1 regression.
7. Real Pi/Codex smoke remains healthy when available.
8. Audit and lessons documents contain the RC3 remediation record.

After these criteria are met, V0.1 should proceed directly to a real Shopify product-validation run rather than adding more speculative scope.

---

## 7. Non-Goals

RC3 does not implement:

- V0.3 telemetry aggregation;
- heartbeat/renderer decoupling (deferred N102);
- phase-attempt commit/rollback telemetry semantics (deferred N104);
- NEED_HUMAN decision packets;
- session migration or renaming of existing directories;
- timezone configuration UI;
- automatic model/role routing;
- multi-reviewer support.
