# Agent Review Orchestrator V0.2 Implementation Audit

**Status:** V0.2-RC3 — implemented; B301/N301 closed (`docs/V0_2_RC3_FIX_SPEC.md`); deterministic suite green (293 + 2 skip, incl. 38 RC3 regressions); real Pi/Codex smoke green; RC3 real-agent supplemental evidence recorded in §7.6 within the mandatory validation budget
**Audit type:** Implementation summary + verification record
**Implemented against:** `docs/V0_2_HUMAN_DECISION_CONVERGENCE_SPEC.md` + `docs/V0_2_RC2_FIX_SPEC.md`
**Baseline:** V0.1-RC3 (`b93f2f0`); RC1 remediation baseline `f5038c1`

---

## 1. Implementation summary

| Spec capability | Implementation | Key code |
| --- | --- | --- |
| A — Explicit Custom Human Decision | Reserved custom-decision selectors (`0`, `custom`, `自定义`, …) in every gate question; `0. [custom]` line in the CLI listing; second prompt captures the authoritative text. `GateAnswer.answer_type` (`OPTION`/`CUSTOM`) + `custom_text`; `Decision.source` retains origin. Custom decisions are first-class: append-only history, SUPERSEDED semantics, contract `confirmed_decisions`, task-revision invalidation, future coverage checks. Unmatched free text never becomes CUSTOM — it stays an unresolved attempt (QUESTION_ONLY etc.). Empty input is a skip, not an attempt (it never degrades earlier attempts as the "latest effective answer"). | `phases/human_gate.py` (`CUSTOM_REQUEST_ANSWERS`, `_ask_pass`, `apply_gate_answers`), `models.py` |
| B — NEED_HUMAN Convergence Gate | New Human Authority Check stage before any terminal handoff: `route_after_failed_pass` flips blockers to NEED_HUMAN (audited) and calls `resolve_need_human_issues`, which runs a read-only Pi `human_authority_check` call, mechanically validates the returned `HumanAuthorityCheckResult`, and routes: **COVERED_BY_ACTIVE_DECISION** → issue reverts to OPEN as a solution gap (durable `covered_by_decisions` marker; provenance preserved) and the normal correction ladder continues; **NEEDS_NEW_HUMAN_DECISION** → validated decision candidate opens a Convergence Gate (`category=CONVERGENCE`, `source_issue_ids`, consumes one interruption); **CANNOT_DETERMINE** / any invalid packet → fail-closed `HUMAN_HANDOFF`. Gate close → decisions → `task_revision++` → proposal STALE → issues SUPERSEDED → INTAKE redesign. | `phases/human_gate.py` (`resolve_need_human_issues`, `_run_authority_check`, `_validate_candidate_packet`), `phases/review.py` (`_need_human_ids`, `continue_blocker_routing`), `agents/pi.py` + `prompts/human_authority_check.md`, `agents/fakes.py` |
| C — Gate state consistency | `StateStore.save_gate_log` mirrors `current` into its `gates[]` entry by `gate_id` on every save (or appends when new) and re-renders `human-gate.md` — one persisted truth; the V0.1 P3 load→mutate→save split is structurally impossible now. | `storage.py` |
| D — Effective answer validation | `HumanGate.effective_answers()` = latest answer per `decision_key`; `validate_answers`, `answered_keys`, `unresolved_questions` and `apply_gate_answers` all operate on it. Historical failed attempts remain in `gate.answers` (auditable, rendered under "unanswered attempts") but can no longer keep a fully answered gate at PARTIAL. | `models.py`, `phases/human_gate.py`, `rendering.py` |
| E — Structured handoff package | Every `HUMAN_HANDOFF` writes `handoff.md`: why stopped, what the Human must decide/provide, blocking issues (problem/impact/acceptance/evidence), relevant ACTIVE decisions, derivable suggested options (or "none"), artifact list, explicit resumability boundary. Gate-budget exhaustion passes the pending questions into the package. `review show handoff [session-id]` added. | `orchestrator.py` (`handoff`), `rendering.py` (`render_handoff`), `cli.py` |

### Protocol changes

- `GateAnswer`: `answer_type` (OPTION/CUSTOM), `custom_text`; shape-validated.
- `Decision`: `source` (OPTION/CUSTOM).
- `HumanGate`: `source_issue_ids` (convergence provenance); effective-answer helpers.
- `Issue`: `covered_by_decisions: list[str]` — orchestrator-owned routing metadata, **reset on ingest** (the reviewer can never forge coverage), written only by the authority-check routing, read by `_need_human_ids` so a covered blocker is never re-flipped on later phase entries (including across crash/resume).
- New models: `AnswerType`, `DecisionSource`, `AuthorityOutcome`, `DecisionCandidate`, `IssueAuthorityOutcome`, `HumanAuthorityCheckResult`.
- New Pi adapter method `human_authority_check(state, issues, decisions, contract)` (read-only; real RPC prompt + fake default CANNOT_DETERMINE so unscripted paths fail closed exactly like the V0 boundary).
- State machine: `REVISION → {WAITING_FOR_HUMAN, HUMAN_HANDOFF}` and `ABLATION → {WAITING_FOR_HUMAN, HUMAN_HANDOFF}` (defensive convergence-gate paths).
- Audit events: `ISSUE_NEED_HUMAN`, `ISSUE_HUMAN_AUTHORITY_CHECK_STARTED`, `ISSUE_COVERED_BY_DECISION`, `CONVERGENCE_GATE_CREATED`, `CUSTOM_DECISION_CAPTURED`, `HANDOFF_WRITTEN`.
- Renderer: convergence-gate line (quiet-visible), NEED_HUMAN routing line, covered-by-decision line, authority-check activity line; verbose fallbacks for the new audit events.
- `schemas/codex-review.schema.json` regenerated for the new Issue field.

### Preserved V0/V0.1 guarantees (verified by the unchanged tests)

Deterministic orchestrator control; mechanical PASS (Codex still never decides PASS); Human Requirement Authority; issue lifecycle ownership (ingest still strips reviewer-supplied lifecycle + coverage fields); all four budgets (opening any gate — normal or convergence — consumes one interruption; custom answers and same-gate re-answers consume none; default remains 2); phase-checkpoint recovery (gate-answer crash test still passes); fail-closed behavior (capability probes, protocol repair, invalid packets, unknown/duplicate/superseded coverage references); Pi/Codex read-only boundaries (unchanged allowlists; authority check is a read-only Pi call); V0.1 progress/session presentation (no V0.1 regression in the suite); Windows console hardening (re-verified on the real E2E runs: CJK, pipes, redirects).

---

## 2. Tests

- **Deterministic suite: 229 passed, 2 skipped** (smoke opt-in), ~30s. Baseline before V0.2 was 193 → **+36 V0.2 tests, 0 regressions**.
- New files:
  - `tests/unit/test_v02_custom_decision.py` — spec §13 A1-A7, F22-F24, custom-supersession, prompt surfaces, final.md labeling.
  - `tests/unit/test_v02_authority_convergence.py` — §13 B8-B10, C11-C14, D15-D17, G25-G27; mixed covered+new; authority check never called for DESIGN blockers; default fail-closed.
  - `tests/unit/test_v02_gate_consistency.py` — §13 E18-E21 + the exact P3 load→mutate→save repro from the V0.1 case audit (appendix B).
  - `tests/unit/test_v02_prod001_replay.py` — §14 permanent replay (below).
- PROD-001 replay coverage: D001 (full_doc5, incl. §5.4 display/statistics unification) + R001 BLOCKING REQUIREMENT + R002/R003 → must NOT handoff; asserts DONE, `ISSUE_COVERED_BY_DECISION [D001]`, preserved REQUIREMENT/INITIAL_REVIEW provenance, revision budget used, no gate burned. A second replay drives the genuine new-decision variant through a Convergence Gate with a custom answer (task_revision 1→3, R001-R003 SUPERSEDED, proposal rebuilt on revision 3). A third replay pins the budget-exhausted structured handoff with explicit resumability boundary.
- Schema robustness: coverage referencing nonexistent **and** SUPERSEDED decisions fails closed; candidates with <2 options, unknown recommendation, reserved-selector collisions, empty questions, or already-decided keys are rejected without opening a malformed gate; unknown/duplicate outcome issue-ids fail closed.

---

## 3. Real-agent validation

Environment: pi 0.85.1 (RPC, read-only allowlist), codex-cli 0.154.0 (`exec -s read-only`), Windows host, driver `scripts/v02_e2e_driver.py` (real adapters + real renderer + CLI stdio hardening; only gate keystrokes scripted). Scratch target repos under `C:\frank\aro-v02-e2e\` (sessions preserved).

| Run | Session | Scenario | Result |
| --- | --- | --- | --- |
| Smoke | — | `AGENT_REVIEW_SMOKE=1` real pi/codex adapter smoke | 24 passed (~153s) |
| E2E-A | `20260911-125830-8d2d` (e2e_a, job queue pause/resume) | Normal gate, 3 questions; Q1 answered `0` + custom CJK text, Q2 offered option; Q3 left unresolved → exit 20 → **resumed in a second process** with another custom answer | **DONE**; D001+D003 CUSTOM / D002 OPTION, all ACTIVE; `CUSTOM_DECISION_CAPTURED` ×2; task_revision 2; interruptions stayed 1/2 (custom consumed no extra budget); `current` == `gates[0]` CLOSED with 3 answers; `review show gate` renders the closed truth incl. "Human-defined decision" lines |
| E2E-B | `20260911-130500-44e7` (e2e_b, sync retry) | REQUIREMENT_TOO_AMBIGUOUS: 5 candidates → 2 gates; custom answer on resume for HG002 | **DONE**; D004 CUSTOM via resume; multi-gate histories independent; real codex raised only a NON_BLOCKING suggestion |
| E2E-C | `20260911-131119-fb65` (e2e_c, retry + report invariant) | Real review raised R002 **BLOCKING REQUIREMENT** (failed-item representation) — the PROD-001 pattern on a live run | **DONE, not HUMAN_HANDOFF**: real Pi authority check → `COVERED_BY_ACTIVE_DECISION [D002]` → R002 reverted OPEN → REVISION → closure RESOLVED; R002 kept REQUIREMENT/INITIAL_REVIEW provenance with `covered_by_decisions=["D002"]` |
| E2E-D | `20260911-132019-4133` (e2e_d, retry + frozen report contract) | **Downstream NEED_HUMAN → Convergence Gate → resume** | Real codex R001 BLOCKING REQUIREMENT (alert-log failure semantics) → real Pi authority check returned NEEDS_NEW + candidate → `CONVERGENCE_GATE_CREATED HG002 source_issue_ids=[R001]` (interruption 2/2) → **answered via custom decision in a separate resume process** → D004 CUSTOM, task_revision 3, proposal archived STALE, R001-R003 SUPERSEDED → redesign on revision 3 → second review raised R004/R005; R005 (REQUIREMENT) again routed via coverage `[D002, D004]` — no termination. Session later hit the known agent-side truncated-JSON failure in `revise` (V0.1 lessons §7.3.1), recovered by resume, and finally converged budgets legitimately exhausted → **HUMAN_HANDOFF with a rich `handoff.md`** (per-issue acceptance/evidence with in-memory reproduction traces quoting D004 verbatim); `review show handoff` verified |

Combined, the real runs cover all three required E2E shapes: custom decision; downstream NEED_HUMAN → Convergence Gate → resume; successful continuation into revision/redesign (E2E-C DONE; E2E-D redesign + second review) — plus the forced-handoff `handoff.md` verification (spec §15.5). Human input remained authoritative without manual copy-paste into a new session.

---

## 4. Remaining limitations

1. **Terminal handoff sessions are not resumable** (unchanged V0 boundary): `handoff.md` is an aid for starting the next session with the conclusions stated in the request; V0.2 deliberately did not reopen arbitrary historical handoffs (spec §16).
2. **The authority check is one Pi call per NEED_HUMAN routing batch** with protocol repair; a Pi failure mid-check fails the session (FAILED, exit 30) — resume from the phase boundary recovers (verified on E2E-D).
3. **Semantic coverage quality depends on Pi's judgment**; the orchestrator only validates structure and ACTIVE references. A wrong-but-well-formed COVERED claim would route to revision (and the reviewer can re-raise it next round, where the same coverage marker prevents re-flipping — a bounded risk accepted by the spec's probabilistic-judgment/deterministic-control split).
4. **Intake still gates most discoverable ambiguities upstream** (observed in E2E-B/D): genuine downstream vacuums are the minority path; convergence gates will be correspondingly rare unless requests under-specify.
5. **Agent-side long-output truncation** (revise phase) recurred on real runs; behavior is the documented V0.1 stance (fail closed + resume), now with two recorded live recoveries.
6. Deferred to later versions (unchanged): V0.3 telemetry aggregation (N102/N104 remain), role-based routing, multi-reviewer, source implementation, deployment, workflow DSL. Telemetry note: V0.3 can now also aggregate authority-check outcomes (COVERED / NEEDS_NEW / CANNOT_DETERMINE) and convergence-gate counts from `events.jsonl`.

---

## 5. Readiness verdict

**V0.2 is ready for another real Shopify workflow.** Exit criteria (spec §17) status:

1. Human can explicitly author a custom Decision — met (deterministic + E2E-A).
2. Arbitrary unmatched text cannot silently acquire Requirement Authority — met (A5/A6 + QUESTION_ONLY).
3. REQUIREMENT/FACT blocker classification alone no longer forces terminal handoff — met (B8 + E2E-C/D).
4. Existing ACTIVE Decisions are considered before requesting new Human authority — met (authority check with ACTIVE-decision context).
5. Genuine downstream Human decisions open a bounded Convergence Gate and resume the same session — met (C11-C13 + E2E-D).
6. Custom and offered Decisions share task-revision/invalidation semantics — met (A3, C13, E2E-D).
7. Gate current/history/Markdown representations stay consistent — met (E18-E21 + P3 repro + real-session checks).
8. Effective-answer validation reaches COMPLETE after later valid answers — met (F22-F24).
9. OPEN → NEED_HUMAN routing is explicitly auditable — met (G25 + renderer line).
10. Terminal handoff produces durable `handoff.md`, inspectable via CLI — met (D15-D17 + E2E-D).
11. PROD-001 replay no longer terminates solely on REQUIREMENT category — met (permanent regression).
12. Full deterministic suite passes without V0/V0.1 regression — met (229 passed at RC1; 255 at RC2).
13. Real Pi/Codex smoke healthy — met (2/2 smoke within the 24 adapter tests).
14. Real-agent custom-decision and convergence-gate scenarios pass — met (E2E-A/C/D).

---

## 6. V0.2-RC2 remediation record (B201/B202/B203 + N201/N202)

**Remediation spec:** `docs/V0_2_RC2_FIX_SPEC.md` · **RC1 baseline:** `f5038c1`
Independent review found three blocking protocol gaps in RC1; all three plus both
non-blocking findings are closed here. No V0.3+ scope was touched.

### 6.1 B201 — FINAL_REVIEW obeys Human Authority / Convergence Gate semantics

| Aspect | Change |
| --- | --- |
| Routing | `run_final()` no longer terminates on failed PASS by category alone: after the audited `ISSUE_NEED_HUMAN` flip it calls the same `try_gate_for_need_human_issues` used by Initial/Closure — **COVERED** → revert-to-OPEN + `continue_blocker_routing` (REVISION/ABLATION only while budget remains, else budget-driven handoff); **NEEDS_NEW** → bounded Convergence Gate (`FINAL_REVIEW → WAITING_FOR_HUMAN`); **CANNOT_DETERMINE / invalid packet / exhausted Human budget** → structured `HUMAN_HANDOFF`. Non-REQUIREMENT/FACT failures keep the legacy "ablation budget exhausted" handoff. |
| State machine | `FINAL_REVIEW → {WAITING_FOR_HUMAN, REVISION, ABLATION, FINALIZE, HUMAN_HANDOFF}`. A Human decision always rebuilds from the new task revision (gate close → invalidate → INTAKE/INVESTIGATE); Final Review is never "continued in place". |
| Invariants | Mechanical PASS unchanged (`passed = verdict AND pass_result.passed` — Codex still never decides PASS); ablation budget rule untouched (routing only consumes *remaining* budgets); interruption budget consumed only on gate creation. |

### 6.2 B202 — Problem Mode FACT convergence re-investigation

- `HumanGate.resume_semantics` (new field, validated against `RESUME_SEMANTICS`): the KIND of Human decision a convergence gate establishes, recorded separately from the `CONVERGENCE` provenance category so provenance can no longer erase decision semantics.
- `compute_resume_semantics()` — deterministic conservative rule: any FACT question forces `FACT` (a Problem-Mode session always re-investigates with the new Human fact instead of pairing it with a stale root-cause model); single common category preserved verbatim; mixed non-FACT packets are `MIXED` and resume via INTAKE. Never depends on `gate.category=CONVERGENCE`.
- Gate close: `establishes_fact = category == FACT or resume_semantics == FACT`; Problem Mode + establishes_fact → `INVESTIGATE` (the new ACTIVE FACT decision is loaded into the re-investigation context exactly like existing FACT decisions), otherwise `INTAKE`. Normal FACT gates keep their V0 behavior.
- Audit/render surfaces: `resume_semantics` in `HUMAN_GATE_CREATED`/`CONVERGENCE_GATE_CREATED` payloads, rendered on the convergence-gate progress line and in `human-gate.md`.

### 6.3 B203 — decision-candidate identity/provenance hardening

All validation happens in `resolve_need_human_issues` BEFORE gate creation, budget consumption, or any issue mutation (covered issues are only reverted after every packet validated):

1. **Exact provenance (B203.1):** `outcome.issue_id ∈ candidate.source_issue_ids`, every source id ∈ the current authority-check batch. Unknown ids are **never silently filtered** — the old `if i in issue_ids` gate-construction filter that could launder an invalid packet into a normal gate is gone (validated union taken verbatim).
2. **Semantic category:** candidate category must be REQUIREMENT/FACT/TRADE_OFF/SCOPE — `CONVERGENCE` rejected with an explicit message (it is a gate routing category). Intake candidate filtering now enforces the same decision-semantic set.
3. **Option-key uniqueness (B203.2):** enforced with the SAME normalization used for answer matching (`normalize_answer_text`, moved to `models.py`) at two boundaries — `_validate_candidate_packet` (convergence) and the shared `GateQuestion` model validator (normal intake gates inherit it; `eligible_candidates` also suppresses duplicates so intake fails closed without crashing). Recommendation validation runs after uniqueness.
4. **Decision identity (B203.3):** duplicate `decision_key` across candidates in one batch → fail closed (RC2's chosen option; no merging).
5. Reserved custom-selector option keys, non-empty keys/labels, 2–4 options, valid recommendation, and the already-ACTIVE `decision_key` rule are all retained/enforced.

### 6.4 N201/N202

- **N201:** `handoff()` now writes a minimal deterministic `handoff.md` fallback (session id, sanitized reason, blocking issue ids, explicit terminal/non-resumable boundary, pointer to the authoritative artifacts) whenever the full render fails; if even that fails, `HANDOFF_WRITE_FAILED` is emitted best-effort. The authoritative `HUMAN_HANDOFF` state can never be masked by a presentation failure (both paths tested).
- **N202:** the authority-check prompt's contradictory "Do not invent options the Human never saw" is replaced with the correct Human-Authority semantics (options are suggestions; never claim Human approval; the Human may reject all and use the custom-decision path), plus the RC2 packet rules (never `CONVERGENCE`, unique option keys, exact `source_issue_ids`).

### 6.5 RC2 regression suite (new)

`tests/unit/test_v02_rc2_regressions.py` — 26 tests mapping to fix-spec §4 items 1–16:

| Item | Tests |
| --- | --- |
| 1 Final Review covered → correction (budget remaining AND exhausted variants) | `test_b201a_*` |
| 2–3 Final Review new decision → gate → custom/option → rebuild | `test_b201b_*` |
| 4 Final Review budget exhaustion → structured handoff | `test_b201c_*` (+ `test_b201_final_review_cannot_determine_fails_closed`, `test_final_review_convergence_handoff_written_from_final_review`) |
| 5–7 Problem FACT convergence → INVESTIGATE with the new ACTIVE fact (option + custom + mixed conservative rule + semantics unit) | `test_b202a/b/mixed`, `test_compute_resume_semantics_deterministic_rules` |
| 8 Problem REQUIREMENT convergence → INTAKE | `test_b202c_*` |
| 9–14 packet integrity: unknown source id / outcome-missing provenance / `category=CONVERGENCE` / duplicate keys / duplicate normalized keys / duplicate `decision_key` (+ reserved selector, empty key, shared `GateQuestion` boundary, intake suppression) | `test_b203_*`, `test_gate_question_rejects_duplicate_option_keys`, `test_intake_candidate_with_duplicate_keys_is_suppressed` |
| 15–16 no gate, no interruption consumed, issue stays auditable, handoff.md explains the boundary | embedded in every `assert_fail_closed_before_gate` case |
| N201 | `test_n201_*` (fallback written; total-write failure keeps state authoritative) |
| N202 | `test_n202_authority_check_prompt_options_are_suggestions` |

### 6.6 RC2 verification evidence

- **Deterministic:** 255 passed, 2 skipped (~37s) — RC1 baseline 229 + 26 RC2 regressions, **0 regressions** (V0/V0.1/V0.2 suites, PROD-001 permanent replay, gate consistency, session presentation all unchanged).
- **Real smoke:** `AGENT_REVIEW_SMOKE=1` full suite 257 passed (~3 min; pi 0.85.1 RPC read-only + codex-cli 0.154.0 `exec -s read-only` probes green).
- **Real-agent RC2 validation:** §6.7.

### 6.7 Real-agent RC2 E2E

Environment: pi 0.85.1 (RPC, read-only allowlist), codex-cli 0.154.0 (`exec -s read-only`), Windows host, driver `scripts/v02_e2e_driver.py` (only gate keystrokes scripted), scratch repos under `C:\frank\aro-rc2-e2e\` (sessions preserved).

| Run | Session | Scenario | Result |
| --- | --- | --- | --- |
| RC2-E2E-A | `20260911-170545-c349` (finalconv, interruptions=3) | e2e_d replay: intake gate → initial-review convergence gate (real NEEDS_NEW + real authority check + custom answer) → rebuild → REVISION → CLOSURE → ABLATION → FINAL_REVIEW with 2 remaining blockers | The full chain reached FINAL_REVIEW under RC2 code; this run's remaining blockers were both DESIGN-classified, so the correct legacy budget handoff fired — RC2 routing did **not** flip a DESIGN blocker (false convergence routing must never happen). Real evidence: `CONVERGENCE_GATE_CREATED resume_semantics=REQUIREMENT` rendered "establishes REQUIREMENT decision(s)"; task_revision 1→3 with two full rebuilds; one agent-side `ablate` truncation recovered via resume. |
| RC2-E2E-B | `20260911-174619-04b0` (finalconv, interruptions=3) | Hard-requirement request variant: 3 REQUIREMENT blockers at initial review → real authority check: R001/R002 → `ISSUE_COVERED_BY_DECISION [D003, D004]` (real coverage routing), R003 → NEEDS_NEW → **real convergence gate through the B203-hardened packet boundary** (exact provenance + unique keys + semantic category validated on a real Pi packet) → rebuild → budget-exhausted structured handoff | Live-validated the hardened candidate boundary accepting a good real packet, the coverage marker path, `resume_semantics` in the real event stream/rendering, and the budget-exhausted handoff with pending packet (B201-C semantics, reached at initial review this run). |
| RC2-E2E-C | `20260911-161230-a345` (factvac, Problem Mode, interruptions=3) | Preferred Problem→FACT path attempt: real investigation SUPPORTED → intake gates (incl. a real FACT gate → live re-INVESTIGATION with the new fact) → design → review blockers → REVISION ×2 (agent-side truncation twice, both recovered via resume) → closure → DONE | Real Problem-Mode integrity end-to-end incl. the FACT-gate → re-INVESTIGATE hop and two fail-closed→resume recoveries; the *downstream* FACT convergence hop was absorbed upstream by intake candidates in every attempt (§6.8 limitation 3) and remains deterministic-only. |

**Real-E2E verdict (honest):** the RC2 stack ran every hop it encountered correctly on real agents — real authority checks, real coverage routing, a real convergence gate through the *new* hardened packet boundary with `resume_semantics` audited end-to-end, real rebuilds, real truncation recoveries, and correct non-routing on DESIGN-classified final blockers. The two *newly repaired routing hops* (a gate opening FROM Final Review, and a Problem-Mode FACT convergence re-entering INVESTIGATE) were not live-triggered within the timebox: reaching Final Review with a REQUIREMENT blocker AND remaining interruption budget, and keeping a fact vacuum downstream of intake, are both low-probability real paths (six documented forcing attempts; reviewer category choice and discovery candidate emission are the probabilistic layers). Deterministic coverage of both hops is complete and permanent (§6.5). Per fix-spec §6.12 this leaves exit criterion 12 (focused real E2E on a newly repaired path) **partially met** — the hardened-boundary + resume-semantics surfaces were live-exercised, the repaired routing hops await the next real workflow.

### 6.9 RC2 exit criteria status (fix-spec §6)

1. FINAL_REVIEW obeys the same Human Authority semantics — met (deterministic B201-A/B/C + state-machine edge).
2. FINAL_REVIEW can enter WAITING_FOR_HUMAN through a valid Convergence Gate — met (deterministic B201-B/C).
3. Problem Mode FACT convergence causes re-investigation with new Human facts — met (deterministic B202-A/B + investigate-context assertion).
4. Convergence provenance and semantic category represented separately — met (`resume_semantics` + conservative mixed rule, deterministic).
5. Candidate provenance exact and mechanically validated — met (B203.1 deterministic; live-validated accepting a good real packet).
6. Option keys unique, cannot mis-record a Human selection — met (shared model boundary + same normalization; deterministic).
7. Duplicate decision identities cannot collapse questions — met (fail-closed; deterministic).
8. All malformed packets fail closed before Gate/budget — met (deterministic, items 9–16).
9. PROD-001 regression green — met.
10. Full deterministic suite, no regression — met (255 passed, 0 regressions).
11. Real Pi/Codex smoke healthy — met (257 passed incl. 2 real smokes).
12. Focused real-agent E2E on a newly repaired path — **partially met** (§6.7 verdict): hardened packet boundary + `resume_semantics` live-exercised; the FINAL_REVIEW-gate and Problem-FACT routing hops remain deterministic-only pending the next real workflow.
13/14. Audit + lessons docs updated — met (this record; `V0_LESSONS_LEARNED.md` §11).

**Readiness:** V0.2-RC2 protocol is complete and deterministic-proven; because criterion 12 is only partially met, the V0.2 spec status is **not** flipped to "validated ready" — the recommendation is to treat the next real Shopify workflow as the confirming run (it exercises the protocol exactly as repaired; any terminal outcome is protocol-correct).

### 6.8 Remaining limitations (RC2)

1. Terminal handoff sessions remain non-resumable (V0 boundary, unchanged).
2. Authority-check judgment quality remains Pi's; the orchestrator validates structure and ACTIVE references only (unchanged RC1 stance, bounded by the durable coverage marker).
3. Forcing the *downstream* Problem-Mode FACT vacuum on real agents proved impractical within RC2's timebox: intake gates legitimately absorb fact-shaped candidates whenever the request reveals the vacuum, and request wording that hides it tends to produce clean-passing designs (six documented attempts). Deterministic coverage (B202-A/B/C + mixed rule) is complete; the next real Shopify problem-mode workflow is expected to exercise this path naturally, and V0.3 telemetry should count convergence-gate resume semantics.
4. Reviewer category choice (REQUIREMENT vs DESIGN) remains the probabilistic layer the spec assigns to Codex; RC2 guarantees the *routing* is correct for whichever category the reviewer uses — never more, never less.
5. Agent-side long-output truncation (`revise`/`ablate`) recurred on RC2 real runs (3 occurrences, 3 recoveries via the documented FAILED→resume path). Agent-side, not orchestrator-side; stance unchanged.

---

## 7. V0.2-RC3 remediation record (B301 + N301)

**Remediation spec:** `docs/V0_2_RC3_FIX_SPEC.md` · **RC2 baseline:** `11bf2ef` (spec baseline `92c7dfd`)
Independent post-RC2 review found one remaining Human Authority blocker (B301 —
Human Answer Alias Space ambiguity) and one protocol-hardening item (N301 —
Intake option cardinality). Both are closed here. No V0.3+ scope was touched.

### 7.1 B301 — Human Answer Alias Space is mechanically unambiguous

**Root cause.** RC2 proved uniqueness only for normalized *option keys*, but the
CLI answering protocol accepts six forms per option — key, label, `key + label`,
numeric index, `选项N`, `option N` — plus reserved protocol-control commands
(custom selectors, global-recommend selectors) in the same Human input
namespace. A packet with duplicate labels, a key colliding with another
option's numeric selector, or a label colliding with `custom`/`按推荐` was
structurally valid, and `match_option()` resolved it **first-match-wins** —
silently recording one of two possible Human meanings as an ACTIVE Decision.

**Fix — one shared source of truth (fix-spec §2.5–§2.7).** `models.py` now owns
the complete alias space:

| Helper | Role |
| --- | --- |
| `CUSTOM_REQUEST_ANSWERS` / `GLOBAL_RECOMMEND_ANSWERS` | the reserved protocol-control commands, moved from `phases/human_gate.py` into models (single definition; re-exported for compatibility) |
| `normalized_option_aliases(option, index)` | the six normalized answer forms each option owns (fixed order ⇒ deterministic violations) |
| `normalized_protocol_control_aliases()` | CUSTOM ∪ GLOBAL_RECOMMEND through the same `normalize_answer_text` |
| `option_alias_violation(options)` | the invariant: aliases of different options must never intersect, and no option-owned alias may intersect the protocol-control namespace; returns a deterministic reason string |

One rule, three enforcement points, all fed by the same helpers:

1. **Shared model boundary** — `GateQuestion` validates the alias space after
   key uniqueness and before recommendation membership, so normal Intake gates,
   Problem Mode FACT gates, Convergence gates and any future producer inherit
   the invariant. No auto-rename, no silent discard, no reordering.
2. **Intake candidate suppression** — `eligible_candidates` rejects ambiguous
   candidates with the shared deterministic reason via `HUMAN_CANDIDATE_SUPPRESSED`
   (no Gate, no interruption consumed).
3. **Convergence packet validation** — `_validate_candidate_packet` runs the
   same check before gate creation/budget consumption; invalid packets fail
   closed to structured `HUMAN_HANDOFF` with provenance intact.

**Runtime matching.** `match_option()` now resolves input against the same
`normalized_option_aliases` sets and **fails closed on ambiguity**: 0 matches →
unresolved; exactly 1 → the option; **>1 → protocol ambiguity → None** — never
first-match-wins, so even a corrupt historical artifact or a future validator
regression cannot silently persist one of multiple Human meanings. `is_custom_request`
/ `is_global_recommend` consume the normalized control sets from the same
source. Persisted corrupt artifacts are additionally rejected at the
`GateLog` load boundary (pydantic revalidates nested questions).

### 7.2 N301 — Intake option cardinality is strictly 2–4

- `eligible_candidates` now enforces `2 <= len(options) <= 4` exactly like
  convergence packets; `>4` is **suppressed**, never truncated, with the
  deterministic reason `requires 2-4 meaningful options, got N` (auditable in
  `events.jsonl`; also the new message for <2, which was previously
  `fewer than 2 meaningful options`).
- Both `[:4]` slices removed: `_to_question()` (intake) and the convergence
  `GateQuestion` construction consume the already-validated list, so invalid
  cardinality can no longer be hidden by slicing and an Agent recommendation
  can never point at a truncated-away option.
- Malformed candidates create no Gate and consume no Human interruption
  (asserted by tests).

### 7.3 Prompt boundary documentation (supporting, not protocol)

`discover.md`, `investigate.md` and `human_authority_check.md` now state the
tightened mechanical boundary (mutually distinct keys/labels after
normalization, no answer-shortcut/reserved-command look-alikes, 2–4 options
rejected-not-truncated) so real agents are not surprised by fail-closed
rejection. Mechanical validation remains authoritative; prompts are advisory.

### 7.4 RC3 regression suite (new)

`tests/unit/test_v02_rc3_regressions.py` — 38 tests mapping to fix-spec §4
items 1–23 (preservation items 24–30 are the unchanged existing suites):

| Fix-spec item | Tests |
| --- | --- |
| 1–6 cross-option ambiguity (duplicate/normalized labels, key↔label, composite, numeric, `选项N`/`option N`) | `test_b301_item1..6`, `test_b301_intake_duplicate_label…`, `test_b301_intake_numeric_collision…`, `test_b301_convergence_duplicate_label…` |
| 7–8 protocol-control collisions (custom + recommend selectors, incl. normalization variants like `Custom.` / `All Recommended.`) | `test_b301_item7` (5 params), `test_b301_item8` (5 params), `test_b301_control_collision_only_after_normalization…`, `test_b301_convergence_control_collision…` |
| 9 same normalization as runtime | `test_b301_item9…`, `test_b301_shared_alias_helpers…`, `test_b301_match_option_uses_the_shared_alias_forms` |
| 10–16 valid behavior preserved (distinct packet valid; numeric/key/label/key+label answers; custom selectors; global recommend) | `test_b301_item10`, `test_b301_items_11_to_14…`, `test_b301_item15…`, `test_b301_item16…` |
| 17 defense in depth (no first-match-wins; ambiguity never becomes ACTIVE Decision; corrupt artifact rejected at load) | `test_b301_item17_match_option_fails_closed…`, `test_b301_item17_ambiguous_answer_never_becomes…`, `test_b301_item17_persisted_ambiguous_gate…` |
| 18–23 N301 cardinality (1 option, 5 options no-truncation, 2 works, 4 works incl. numeric alias 4, no gate/no interruption, deterministic auditable reason) | `test_n301_item18..23`, `test_n301_gate_question_rejects_five_options`, `test_n301_convergence_candidate_with_five_options…` |

**Falsification** (the `V0_LESSONS_LEARNED.md` §8.6.2 “回归必须先证伪” practice): before the fix was applied, a probe
script against the RC2 source confirmed all five headline defects —
duplicate-label packet accepted; key `1` colliding with the numeric selector
accepted; label `custom` accepted; `match_option("保持现状")` silently selected
the first option; 5 options silently truncated to 4. All are now rejected by
the RC3 suite.

### 7.5 Verification evidence

- **Focused RC3 suite:** 38 passed.
- **Full deterministic suite:** 293 passed, 2 skipped (~40s) — RC2 baseline 255
  + 38 RC3 regressions, **0 regressions** (V0/V0.1/V0.2/RC2 suites, PROD-001
  permanent replay, gate consistency, session presentation all unchanged).
- **Real adapter smoke:** `AGENT_REVIEW_SMOKE=1` full suite **295 passed**
  (~2:43; pi 0.85.1 RPC read-only + codex-cli 0.154.0 `exec -s read-only`
  probes green).

### 7.6 Real-agent supplemental evidence (within the mandatory budget)

Per fix-spec §5, malformed alias/cardinality packets are **deterministic
fixtures**; no probabilistic branch forcing was attempted.

**Budget usage:** 1/2 fresh real-agent sessions · 0/2 branch-forcing request
variants (the single run was natural) · ~14/60 minutes wall clock. Whichever
limit hit first did not apply; validation stopped voluntarily after the natural
run provided the relevant evidence.

| Run | Session | Scenario | Result |
| --- | --- | --- | --- |
| RC3-E2E-A | `20260911-191400-873a` (scratch repo `C:\frank\aro-rc3-e2e\target-repo`, request 「给订单同步任务增加暂停能力」, driver `scripts/v02_e2e_driver.py`) | Real Pi discovery emitted 3 candidates (REQUIREMENT/TRADE_OFF/FACT) → **all accepted by the new alias-space validation (0 suppression events)** → HG001 (3 questions); answered in two passes: Q1 numeric `1` → `cooperative_flag`; Q2 **full CJK label** (punctuation intact) → `new_task_class`; Q3 key `library_call` → `library_call` | **DONE exit 0** (~13.5 min); task_revision 2; interruptions 1/2; real Codex review raised R001 REGRESSION + R002 DESIGN blockers → REVISION → closure verified → DONE; 3 ACTIVE decisions each persisted with the **correct option key and label**; gate `current == gates[0]` CLOSED; `human-gate.md` renders the closed truth |

Interpretation: the changed boundary accepts well-formed real agent packets
(the over-rejection risk RC3 introduced did not materialize) and all three
advertised answer forms resolve through the shared alias space on real packets
with unmis-recordable Human authority. The **reject** direction (ambiguous
aliases, >4 options) remains deterministic-fixture coverage by design, exactly
as the fix-spec prescribes.

### 7.7 RC3 exit criteria status (fix-spec §7)

1. Every accepted Human answer string has exactly one authoritative
   interpretation — met (shared alias-space invariant at three boundaries).
2. Cross-option alias collisions fail before Human interaction — met.
3. Option aliases cannot collide with custom/global-recommend commands — met.
4. Runtime matching never uses silent first-match-wins on ambiguity — met
   (fail-closed `None`; corrupt artifacts also rejected at load).
5. Validation and runtime matching share one alias source of truth — met
   (`models.py` helpers drive both).
6. Intake no longer truncates >4 options — met (both `[:4]` slices removed;
   suppression with deterministic reason).
7. Malformed alias/cardinality packets create no Gate and consume no
   interruption — met.
8. Existing Custom Decision behavior unchanged — met (item-15 regressions +
   suite).
9. RC2 B201/B202/B203 regression suites green — met (26/26).
10. Full deterministic suite, no regression — met (293 passed).
11. Real Pi/Codex smoke healthy — met (295 passed incl. 2 real).
12. Validation Budget obeyed, no unbounded probabilistic forcing — met
    (§7.6: 1 session / 0 forcing variants / ~14 min).

**Readiness:** all twelve RC3 exit criteria are met. V0.2-RC3 is ready for the
focused independent code review of B301/N301 prescribed by the fix-spec; after
that review finds no new blocker, the product returns to normal real Shopify
usage for validation rather than another synthetic RC.
