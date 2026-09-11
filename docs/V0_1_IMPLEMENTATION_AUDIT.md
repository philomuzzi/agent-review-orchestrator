# Agent Review Orchestrator V0.1 Implementation Audit

**Status:** V0.1-RC1 — blocking fixes required before the next real Shopify validation
**Audit type:** Static implementation review
**Implementation commit:** `24eb2b52fd2d18088edb0bbd258f331376ba45f1`
**Reviewed against:** `docs/V0_1_RUNTIME_PROGRESS_VISIBILITY_SPEC.md`

## 1. Summary

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
