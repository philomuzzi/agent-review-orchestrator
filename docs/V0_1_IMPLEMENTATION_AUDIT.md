# Agent Review Orchestrator V0.1 Implementation Audit

**Status:** V0.1-RC2 — remediated; real-agent validated; ready for the real Shopify validation gate
**Audit type:** Static implementation review (+ RC2 dynamic verification)
**Implementation commit (RC1):** `24eb2b52fd2d18088edb0bbd258f331376ba45f1`
**Reviewed against:** `docs/V0_1_RUNTIME_PROGRESS_VISIBILITY_SPEC.md`

---

## RC2 remediation record — 2026-09-11

The RC1 findings below are retained as the audit baseline. **B101–B103 are
resolved** with deterministic regression coverage, alongside three
additional RC1 defects found during RC2 verification (R201–R203 below) and
the audit's recommended-in-scope non-blocking items N101/N103/N105. N102
and N104 are explicitly deferred to V0.3. No V0 semantics (PASS rule,
Human Authority, Issue lifecycle, budgets, crash recovery, read-only
agents), no event-source architecture and no output-level contract was
redesigned.

### Blocking findings

| Finding | Confirmed root cause | RC2 correction | Verification |
| --- | --- | --- | --- |
| B101 / session resolution | `latest_session()` derived recency from lexicographic directory names; the random 4-hex suffix has no temporal meaning within one second, and `unfinished_only` treated only `RUNNING` as resumable, hiding newer `FAILED`/`INTERRUPTED` sessions. | One shared policy: `StateStore._creation_ordered()` sorts every loadable session by persisted `created_at` (corrupt sessions excluded, deterministic id tie-break); `unfinished_only` selects the newest session in the canonical `RESUMABLE_STATUSES` set (RUNNING/INTERRUPTED/FAILED); `status --list` and default resolution now share this ordering; explicit ids remain authoritative. | Probed with same-second opposite-lexical suffixes; real 3-session repo: default `status` target == `status --list` top row == newest by `created_at`. Regressions: `test_same_second_sessions_resolve_by_created_at`, `test_latest_unfinished_includes_failed_and_interrupted`, `test_resolution_and_list_share_ordering`. |
| B102 / review progress truth | `CLOSURE_REVIEW_COMPLETED` reported verified resolutions without new blockers from the same review; `FINAL_REVIEW_COMPLETED` rendered the reviewer's `satisfies_requirement` directly, equating it with workflow PASS. | Both events are now emitted **after** ingest + lifecycle + mechanical PASS and carry post-processed truth: closure adds `new_blocking`/`remaining`; final adds `passed`/`remaining`. Rendering: closure with a regression shows `N of M verified · X new blocker(s) · Y unresolved`; final shows `requirement satisfied · PASS` only when the orchestrator actually computed a pass, else `! requirement check not passed · N blocker(s) unresolved`. | Regressions with scripted disagreement: closure regression case, final verdict-vs-PASS case, plus genuine-pass wording preserved (`test_closure_all_resolved_keeps_success_wording`, `test_final_review_pass_renders_satisfied`). |
| B103 / title presentation boundary | Agent-generated `task_title` (and `--name`) crossed into persistence/rendering with no host-side normalization. | Host-owned `sanitize_title()`: single printable line, whitespace collapsed, control/escape characters removed, hard 80-char cap, CJK preserved, no brittle semantic length rule; applied at both ingestion points; `display_title()` re-sanitizes on render (legacy/edited states stay safe); `--name` precedence unchanged. | `test_sanitize_title_*`, `test_discover_title_sanitized_before_persist`, `test_user_name_sanitized`, `test_display_title_sanitizes_hostile_legacy_state`, `test_status_list_rows_stay_single_line_with_evil_title`. |

### Additional RC1 defects found and fixed during RC2 verification

| Finding | Defect (probe-confirmed) | RC2 correction |
| --- | --- | --- |
| R201 / renderer line-safety | Event payloads with newlines (failure reasons embed agent stderr tails) rendered one event as multiple terminal lines, in every level including `--quiet`. | `_one_line()` collapse applied to all free-text render fields and the verbose fallback dump. |
| R202 / lookup resilience | One corrupt `state.json` crashed `status`, `status --list` (the "(corrupt state)" row was dead code), `show` and `resume` with tracebacks. | `load_state`/`load_state_of` fail closed to `None`; CLI `resume` converts construction errors to a clean exit 30; `step()` keeps the last known-good in-memory state when a post-recovery reload fails; `load_proposal()` treats unknown revision state as "no active design"; `recover_phase()` still hard-fails on invalid checkpoints. |
| R203 / id format invariant | The same-second collision fallback appended `-2`, producing ids outside the compact `YYYYMMDD-HHMMSS-xxxx` contract. | Collision retry regenerates a fresh random suffix (bounded loop). |

### Non-blocking items

| Item | Disposition |
| --- | --- |
| N101 interruption classification | **Fixed.** `KeyboardInterrupt` inside an agent call emits `AGENT_CALL_INTERRUPTED` (verbose-only rendering), never `AGENT_CALL_FAILED`; the terminal `SESSION_INTERRUPTED` line still carries the user-facing notice. |
| N103 canonical phase naming | **Fixed.** `canonical_phase()` in the shared `protocol_retry_reporter` maps adapter method names (`initial_review`) to the workflow Phase vocabulary (`INITIAL_REVIEW`, plus `CAPABILITY` for probes) at a single central point covering real and fake adapters. |
| N105 truthful task-revision messaging | **Fixed.** `TASK_REVISION_INCREMENTED` carries `archived=<bool>`; the `old proposal archived STALE` clause renders only when a proposal really was archived (`PROPOSAL_STALE` remains the dedicated event). Confirmed on a real run: a gate before any proposal now renders `↻ task revision 2 · design basis changed` with no archive claim. |
| N102 heartbeat coupled to renderer | **Deferred to V0.3.** Moving heartbeat production policy from the renderer into Orchestrator/config churns `agent_call` + CLI + the renderer contract for no V0.1 behavioral gain; recorded as the first V0.3 telemetry-infra task. |
| N104 attempt/commit event semantics | **Deferred to V0.3.** Raw `events.jsonl` counts can double-count rolled-back phase attempts until `phase_attempt_id` / `PHASE_COMMITTED` semantics exist; no V0.1 consumer aggregates the stream, so no behavior change now. |
| Convenience commands (V0 lessons §7.3 candidates) | **Added.** `review --version` (was an exit-2 usage error) and `review show events`; `review resume --config` parity with `review run`. |

### Verification summary

- Deterministic suite: **181 passed, 2 skipped** (~19s) — 152 RC1 tests plus
  **29 RC2 regressions** in `tests/unit/test_v01_rc2_regressions.py`,
  covering every acceptance criterion of B101–B103, R201–R203, N101, N103
  and N105. `git diff --check`, `review --help`, `review --version` clean.
- Real smoke (`AGENT_REVIEW_SMOKE=1`): **2 passed** (150s) against
  pi 0.85.1 and codex-cli 0.154.0.
- Real-agent E2E (pi + codex, real renderer; only gate keystrokes scripted):
  1. `20260911-014137-2ed9` (named): capability heartbeats → DISCOVER
     heartbeats → gate(3) answered → revision 2 → gate(2, budget 2/2)
     answered → revision 3 → DESIGN/INITIAL_REVIEW heartbeats → 2 blocking
     → FACT blocker → NEED_HUMAN → HUMAN_HANDOFF exit 10 (correct V0
     boundary; scene preserved and inspectable).
  2. `20260911-014955-a907`: placeholder → DISCOVER semantic title
     「README 补充 run_steps 参数行为说明」 → gate(1) → DONE exit 0.
  3. `20260911-021157-6c66` (post-RC2): N105 truthful revision line in a
     real run; DONE exit 0; default `status` resolution, `status --list`
     top row and persisted `created_at` all agree (B101 on real data).
- Windows console guards (rich legacy Win32, UTF-8 stdio) held across all
  rendered paths; no Errno 22, no native crash, no mojibake in console or
  redirected files.

### Exit-criteria status (§5)

1. Default session commands resolve deterministically by persisted
   metadata — **met** (B101).
2. Visible progress never overstates success relative to mechanical PASS —
   **met** (B102).
3. Agent/user titles cross a deterministic safety boundary — **met** (B103).
4. Deterministic regressions pass — **met** (181).
5. Real-agent smoke healthy — **met** (2/2).
6. Real run confirms perceptible execution and inspectable/resumable
   sessions — **met** (three real sessions).

**V0.1-RC2 is ready for the final product validation: one real Shopify
repository workflow** (the remaining limitation set below does not block
it).

### Remaining limitations

1. Final-heartbeat/terminal-event ordering: a last heartbeat may land
   after the terminal event (thread timing); cosmetic only.
2. N102/N104 deferred — V0.3 must not aggregate raw event counts without
   attempt/commit semantics.
3. One workflow owner per session; no concurrent-writer or power-loss
   guarantee beyond atomic writes + phase checkpoints (V0 boundary).
4. Corrupt sessions are reported, never repaired; recovery truth is the
   phase checkpoint.
5. NEED_HUMAN handoffs still require a human to read `issues.json`
   (option packets are future work, see V0 lessons §5.3).

---

## 1. Summary (RC1 baseline)

V0.1 is directionally correct and preserves the V0 architecture well:

- runtime progress is projected from Orchestrator-owned events;
- `events.jsonl` and CLI rendering share one event path;
- long agent calls emit heartbeats without fake percentage progress;
- raw agent reasoning is not streamed;
- session identity is separated from the human-facing task title;
- short request-independent session IDs are used;
- `--verbose`, `--quiet`, `--name`, and `status --list` are implemented;
- the implementation report records deterministic tests, real Pi/Codex smoke, and a real-agent E2E run.

The implementation should be treated as **V0.1-RC1**, not final, because several runtime-presentation paths can still present the wrong session or misleading workflow truth.

---

## 2. Blocking Findings

### B101 — Default session resolution can select the wrong session

#### Problem

V0.1 changed session IDs to:

```text
YYYYMMDD-HHMMSS-<random-4-hex>
```

`status --list` correctly sorts sessions by `state.created_at`, but the shared default resolver used by `review resume`, `review status`, and `review show` still delegates to `StateStore.latest_session()`, which derives recency from lexicographically sorted directory names.

Within the same second, the random suffix has no temporal meaning. Therefore the default commands can select the wrong session.

There is also a status-policy mismatch: `resume` is documented as selecting the latest unfinished session, but `latest_session(unfinished_only=True)` currently treats only `RUNNING` as unfinished. `FAILED` and `INTERRUPTED` sessions are resumable and may be newer than an older `RUNNING` session.

#### Impact

- `review resume` may resume the wrong task;
- `review status` / `review show` may inspect the wrong task;
- the new short random session-ID scheme makes the old directory-name ordering invalid.

#### Required correction

Create one shared session-resolution policy based on persisted session metadata, not directory-name ordering.

At minimum:

- sort by `state.created_at` or another authoritative persisted timestamp;
- define resumable / unfinished states explicitly;
- make `resume`, `status`, `show`, and `status --list` use compatible ordering semantics;
- keep explicit session IDs authoritative when provided.

#### Acceptance criteria

1. Two sessions created in the same second with opposite lexical random suffix ordering still resolve newest-first by persisted timestamp.
2. A newer `FAILED` or `INTERRUPTED` resumable session is not hidden by an older `RUNNING` session unless an explicit policy says otherwise.
3. `status --list` and default resolution share one well-defined ordering policy.
4. Regression tests cover same-second random suffixes and mixed session statuses.

---

### B102 — Review progress can display a stronger conclusion than the Orchestrator has established

#### Problem

V0.1 intends progress output to be trustworthy workflow truth, but some review completion lines are rendered from partial Reviewer outputs rather than the Orchestrator's post-processing result.

#### Closure Review case

`CLOSURE_REVIEW_COMPLETED` currently reports how many addressed blockers were verified resolved, but does not include blockers newly introduced during the same closure review.

This can produce output similar to:

```text
✓ CLOSURE_REVIEW · 2 of 2 blocker(s) verified resolved
```

while the same review has just introduced a new blocking regression.

#### Final Review case

`FINAL_REVIEW_COMPLETED` renders `satisfies_requirement` directly from the Reviewer result and may show:

```text
✓ FINAL_REVIEW · requirement satisfied
```

before the Orchestrator computes mechanical PASS. The workflow can then immediately fail PASS because blocking issues still exist and enter `HUMAN_HANDOFF`.

That violates the architecture principle:

> Agents provide judgments; the Orchestrator owns workflow truth.

#### Impact

The user may see a successful-looking statement immediately before the workflow reports failure or handoff. This undermines the exact trust problem V0.1 was introduced to solve.

#### Required correction

Progress summaries for review phases must reflect **post-ingestion, post-lifecycle, post-mechanical-PASS state**.

Possible direction:

```text
✓ CLOSURE_REVIEW · 2 existing blockers resolved · 1 new blocker · 1 blocker remains

✓ FINAL_REVIEW completed
! requirement check not passed · 1 blocking issue remains
```

The exact wording is not normative; the truth source is.

#### Acceptance criteria

1. Closure Review output includes any newly introduced blocker that affects current PASS state.
2. Final Review output never equates Reviewer `satisfies_requirement=true` with workflow PASS.
3. A user cannot see `requirement satisfied` when the Orchestrator will immediately fail PASS for unresolved blockers, active gate, or stale proposal state.
4. Tests cover a closure regression blocker and a final-review verdict/PASS disagreement.

---

### B103 — Agent-generated `task_title` crosses the presentation boundary without host sanitization

#### Problem

`task_title` is agent-generated text. The prompt asks Pi to produce a concise semantic title, but the persisted model currently accepts an arbitrary string and the host writes/displays it directly.

This relies on prompt compliance for presentation safety and readability.

Potential malformed outputs include:

- multiline text;
- excessive length;
- control characters;
- terminal escape/control sequences;
- accidental prose instead of a title.

The semantic quality can remain agent-owned, but structural presentation safety must be host-owned.

#### Required correction

Introduce a deterministic host-side title normalization boundary before persistence/display.

Suggested constraints:

- trim surrounding whitespace;
- normalize to a single line;
- remove control characters / terminal escape sequences;
- apply a reasonable hard maximum length;
- retain Unicode/CJK text;
- preserve explicit `--name` precedence, while applying equivalent display-safety normalization.

Do not enforce a brittle semantic rule such as exactly 10–20 Chinese characters; that remains prompt guidance, not a hard protocol constraint.

#### Acceptance criteria

1. Multiline agent titles render as one safe line.
2. Control/escape characters cannot affect terminal presentation.
3. Very long titles are bounded deterministically.
4. Normal Chinese/English semantic titles remain unchanged or minimally normalized.
5. Tests cover agent-generated titles and explicit `--name` values.

---

## 3. Non-blocking Improvements

### N101 — Ctrl+C is currently also emitted as `AGENT_CALL_FAILED`

`agent_call()` catches `BaseException`, so a `KeyboardInterrupt` first emits an agent-call failure and is later converted into `SESSION_INTERRUPTED` by the outer run loop.

For future telemetry this can incorrectly count a user cancellation as an agent failure.

Recommended: represent cancellation/interruption separately, or avoid emitting `AGENT_CALL_FAILED` for `KeyboardInterrupt` / cancellation paths.

---

### N102 — Heartbeat event production is coupled to the renderer

The Orchestrator reads `self.renderer.heartbeat_interval` to decide whether heartbeat events exist at all. With `NullRenderer`, no heartbeat events are produced.

This weakens the claim that the event stream is independent of presentation and may matter for V0.3 telemetry.

Recommended: heartbeat production policy should come from configuration / Orchestrator; Renderer should only decide whether to display an event.

---

### N103 — Phase naming is inconsistent across event families

Agent-call events use workflow phase names such as:

```text
INITIAL_REVIEW
```

Protocol retry events may carry adapter method names such as:

```text
initial_review
```

V0.3 aggregation will otherwise split one logical phase into multiple values.

Recommended: normalize event phase values to the canonical `Phase` enum vocabulary.

---

### N104 — V0.3 cannot safely aggregate raw `events.jsonl` without attempt/commit semantics

Crash recovery intentionally allows audit events from an uncommitted phase attempt to remain after rollback. A later resume may execute the same phase again.

Therefore raw event counts/durations can double-count rolled-back attempts.

Before V0.3 relies on the event stream for metrics, add enough semantics to distinguish committed vs rolled-back attempts, for example:

- `phase_attempt_id`;
- `PHASE_COMMITTED` / `PHASE_ROLLED_BACK`;
- or an equivalent deterministic mechanism.

No V0.1 behavior change is required if this is explicitly deferred to V0.3.

---

### N105 — `TASK_REVISION_INCREMENTED` message can claim an archive that did not happen

The default progress text says the old proposal was archived STALE whenever task revision increments, but Human Gate may occur before any proposal exists.

Recommended: emit/render only facts that actually occurred, e.g. separate `PROPOSAL_STALE` from generic task-revision change messaging.

---

## 4. Required RC2 Scope

V0.1-RC2 should be deliberately small.

Required:

- fix B101 session resolution;
- fix B102 review progress truth;
- fix B103 title presentation boundary;
- add regression tests for all three;
- preserve V0 PASS, Human Gate, Issue lifecycle, budgets, crash recovery, and read-only safety;
- run the full deterministic suite;
- rerun real Pi/Codex smoke where available;
- perform one real E2E that exercises progress output and session presentation.

Recommended while touching the same code:

- N101 interruption classification;
- N103 canonical phase naming;
- N105 truthful task-revision messaging.

N102 and N104 may be explicitly documented for V0.3 if changing them would widen V0.1-RC2 unnecessarily.

*(RC2 disposition: all Required items met; all three Recommended items fixed; N102/N104 documented as deferred — see the remediation record.)*

---

## 5. Exit Criteria

V0.1 may move from RC1 to complete only when:

1. default session commands resolve the intended latest session deterministically;
2. visible progress never overstates workflow success relative to mechanical PASS;
3. all agent/user-generated presentation titles cross a deterministic safety boundary;
4. deterministic regressions pass;
5. real-agent smoke remains healthy;
6. a real repository run confirms that the CLI is both perceptible during execution and understandable when inspecting/resuming sessions.

The final product validation should be performed on a real Shopify workflow rather than only a synthetic E2E.
