# Agent Review Orchestrator V0.3 Implementation Audit

**Status:** V0.3 implemented — deterministic suite green (**360 passed, 2 skipped**, incl. 67 new V0.3 tests; 0 regressions against the V0.2-RC3 baseline of 293), real Pi/Codex smoke green (24 passed), bounded real validation completed within budget (§5)
**Audit type:** Implementation summary + verification record
**Implemented against:** `V0.3_CONVERGENCE_QUALITY_DESIGN.md` (sole source of truth)
**Baseline:** V0.2-RC3 (`c43e3ce`)
**Primary real-world evidence:** `docs/V0_2_CASE_AUDIT_20260914_RECONCILE_HANDOFF.md` (84fb) + `docs/V0_2_CASE_AUDIT_20260914_PROD005_HANDOFF.md` (c454)

---

## 1. Gap analysis (V0.3 design vs V0.2-RC3)

| Capability | V0.2-RC3 state | Gap | Resolution |
| --- | --- | --- | --- |
| C0 Scope Guard | none — every request entered the normal workflow | full | new `SCOPE_GUARD` phase between DISCOVER and INVESTIGATE/INTAKE; Pi `scope_guard` call; `ScopeAssessment` model; deterministic continuation control |
| C1 Terminal Result Contract | `handoff.md` only, decision-centric template (c454 P4 evidence); internal state == user-facing outcome | full | `ResultStatus` classification; deterministic `session-result.md` renderer + minimal fallback on **every** terminal (DONE / boundary / FAILED); `telemetry.json`; internal state ≠ user-facing result (§56) |
| C2 Generic Correction Action | fixed ladder REVISION → auto-ABLATION → handoff (the exact default fallback design §28 forbids) | rework | `correction_action` (+`focus_area`, `change_scope`) on issues/outcomes/final recommendations; deterministic `route_engineering_correction`; ABLATION explicit-only |
| C3 Focused Revision | none | full | new `FOCUSED_REVISION` phase + Pi `focused_revise`; focused contract with mechanical checks; separate budget (1) |
| C4 Review Convergence Contract | undifferentiated review depth (c454 P2/P3 evidence); no acceptance accounting; no late-issue provenance vocabulary beyond `why_not_detected_initially`; issue-id repetition irrelevant | extension | acceptance coverage at INITIAL (recorded) and FINAL (superset enforced — criteria may not silently disappear); `origin` provenance for late blockers (never suppressed when explained); `material_progress` on unresolved outcomes → No-Material-Progress STOP |
| C5 Human Gate Batching | hard cap 3/gate; overflow deferred unconditionally → chained same-second gates (84fb/c454 P1, both real cases) | rework | cap 3→6; deferral ONLY for `depends_on`-declared dependencies (transitive fixpoint); `GATE_CANDIDATE_DEFERRED` audit event |
| Telemetry §59 | none | new | `agent_review/telemetry.py` — deterministic aggregation written at every terminal |

## 2. Implementation summary

| Capability | Implementation | Key code |
| --- | --- | --- |
| C0 — Scope Guard | After DISCOVER the orchestrator enters `SCOPE_GUARD` (state machine: `DISCOVER → SCOPE_GUARD → {INTAKE, INVESTIGATE, HUMAN_HANDOFF}`; no bypass path exists). Pi produces a structured `ScopeAssessment` (verdict, primary outcome, independent outcomes, decision clusters, change surfaces, external unknowns, rationale, optional uncertainty, decomposition). The **orchestrator** controls continuation: BOUNDED → normal workflow (CHANGE→INTAKE, PROBLEM→INVESTIGATE); DECOMPOSITION_REQUIRED / OUT_OF_SCOPE → terminal before any Design/Review/Human budget is spent, with `SCOPE_GUARD_STOPPED` + classification. Model validation enforces ≥2 child sessions with title+goal for DECOMPOSITION_REQUIRED; malformed verdicts fail closed through protocol repair. §54 conservative classification: the prompt forbids inventing Requirement decisions and requires the `uncertainty` field to record ambiguities (no gate is ever opened from this phase). | `phases/scope_guard.py`, `models.py` (`ScopeVerdict`, `ScopeAssessment`, `DecompositionProposal`), `agents/pi.py` + `prompts/scope_guard.md`, `state_machine.py` |
| C1 — Terminal Result Contract | Every terminal session writes `session-result.md` via a **deterministic renderer over persisted artifacts** (no additional Agent call) + a mandatory minimal fallback when the rich renderer fails. Sections per design §22: Status / Summary / Scope Assessment / Current Recommended Design (with NOT-approved caveat) / Frozen Human Decisions / Resolved Issues / Remaining Blocking Issues (close conditions + reviewer-recommended correction as next-session hard inputs) / Remaining Non-Blocking Issues / Implementation Readiness (READY only for APPROVED) / Decomposition Proposal / Recommended Next Action (engineering-shaped for DESIGN_NOT_APPROVED — the c454-P4 fix). `handoff.md` remains for compatibility and now carries the result classification. `ResultStatus` on `SessionState` keeps internal state and user-facing classification separate (§56): HUMAN_HANDOFF may classify DESIGN_NOT_APPROVED / NEEDS_HUMAN_DECISION / DECOMPOSITION_REQUIRED / OUT_OF_SCOPE. Classification is explicit at every handoff call site; a mechanical derivation fallback uses pending decision work (pending questions, open gate, un-covered NEED_HUMAN issues) → NEEDS_HUMAN_DECISION, else DESIGN_NOT_APPROVED. FAILED results are written on protocol/tooling failure. `review show result` added. | `orchestrator.py` (`handoff(result_status=…)`, `fail()`, `_write_terminal_result`, `_derive_result_status`), `rendering.py` (`render_session_result`), `finalize.py`, `cli.py` |
| C2 — Generic Correction Action | WHAT is wrong (reviewer issues) is separated from HOW the workflow responds (orchestrator routing). `CorrectionAction` enum `FULL_REVISION / FOCUSED_REVISION / ABLATION / HUMAN_DECISION / STOP` + descriptive `focus_area` (BEHAVIOR…OTHER; never a workflow state). Reviewers recommend via `Issue.correction_action` (initial), `IssueOutcome.correction_action` (closure) and `CorrectionRecommendation` (final). `route_engineering_correction` executes deterministically: STOP recommendations and No-Material-Progress repeats stop as DESIGN_NOT_APPROVED; otherwise the highest-priority **explicitly recommended** action with remaining budget runs; no recommended action with budget → stop. **ABLATION never fires without an explicit remove/simplify recommendation** (the V0.2 auto-ablation ladder is deleted). Unknown enum values fail closed at schema validation (protocol repair → FAILED). A `HUMAN_DECISION` recommendation routes through the same V0.2 Human Authority Check as the REQUIREMENT/FACT category; covered semantics convert back to an engineering correction (default FULL). | `phases/review.py` (`route_engineering_correction`, `_need_human_ids`, `_default_recommendation`, `recommendations_for_unresolved_blockers`), `models.py` |
| C3 — Focused Revision | New `FOCUSED_REVISION` phase routed only on explicit FOCUSED_REVISION recommendations. Inputs: latest proposal, target issues, allowed change scope (union of `Issue.change_scope`), preserved invariants (**ACTIVE Human Decisions + contract must-preserve + explicitly-unchanged sections**, computed by the orchestrator and carried into the prompt). One `pi.focused_revise` call returns the complete updated proposal (serialization; the WORK stays focused — §36 permits this where delta persistence is impractical) + `target_issue_ids / allowed_change_scope / preserved_invariants / changed_sections / issue_responses / acceptance_changes`. Mechanical contract checks fail closed: targets must equal the routed blocker set; `changed_sections ⊆ allowed_change_scope` when the scope is explicit; issue-by-issue responses are model-enforced. No rediscovery (no DISCOVER re-run); decisions.json and `task_revision` are untouched; closure review verifies RESOLVED exactly as after full revision. Separate budget `focused_revision` (1), separate from full revision — not a sequential life. Artifacts: `focused-revision.md`. | `phases/focused_revision.py`, `models.py` (`FocusedRevisionResult`), `agents/pi.py` + `prompts/focused_revision.md`, config `budgets.focused_revision` |
| C4 — Review Convergence Contract | INITIAL_REVIEW: comprehensive contract in the prompt incl. **Evidence Discrimination** (would the evidence distinguish a Requirement-satisfying implementation from a violating one?) and mandatory `acceptance_coverage` (every derived criterion PASS, or FAIL linked to the exact BLOCKING issue title; duplicates rejected; fail-closed on violation). Coverage is persisted (`acceptance-coverage.json`) and **FINAL_REVIEW must re-account every recorded criterion** (string-superset enforced; a criterion that disappears is a protocol failure). CLOSURE_REVIEW stays differential (verify prior blockers + evaluate correction delta + global safety) but MUST still report serious late findings — now with recorded provenance: `origin ∈ {INTRODUCED_BY_CORRECTION, PREVIOUS_REVIEW_MISS, NEW_EVIDENCE, DIRECTLY_REQUIRED_FOR_CLOSURE}`; unexplained new BLOCKING issues are downgraded to NON_BLOCKING (REGRESSION auto-fills INTRODUCED_BY_CORRECTION — V0 compat); PREVIOUS_REVIEW_MISS additionally requires `why_not_detected_initially`. FINAL_REVIEW new blockers require origin (never suppressed when explained — user directive 7). Material progress: UNRESOLVED outcomes carry `material_progress ∈ {PROGRESSED, NO_PROGRESS}`; PROGRESSED requires a structured-evidence note ("looks better" is model-rejected); NO_PROGRESS + a recommendation to repeat the same mechanism → `NO_MATERIAL_PROGRESS_STOP` → DESIGN_NOT_APPROVED. | `phases/review.py`, `models.py` (`AcceptanceCoverageEntry`, `NewIssueOrigin`, `MaterialProgress`, `CorrectionRecommendation`), `storage.py` (coverage persistence), prompts |
| C5 — Human Gate Batching | `MAX_QUESTIONS_PER_GATE` 3→6; a candidate may be deferred **only** when it declares `depends_on` referencing another batched/deferred candidate (transitive fixpoint; dependencies satisfied by ACTIVE decisions batch immediately). `REQUIREMENT_TOO_AMBIGUOUS` remains the safety valve beyond 6. Every V0.2 constraint preserved: alias space, 2–4 options, custom decisions, latest-effective answers, one interruption per gate. This kills the 84fb/c454 chained same-second-gate pattern (4 independent candidates → 1 gate, 1 interruption). | `phases/human_gate.py` (`_gate_from_candidates`), `models.py` (`HumanCandidate.depends_on`) |
| Telemetry §59 | Deterministic aggregation from state + issues + events + scope assessment, written at every terminal as `telemetry.json`: scope_verdict, scope_guard_duration_seconds, decomposition_count, initial/closure/final blocker counts, previous_review_miss_count, full/focused/ablation counts, same_blocker_round_count, no_material_progress_stop_count, human_interruptions, terminal_result_status, session_result_generated, time_to_first_proposal_seconds, total_elapsed_seconds. Everything stays derivable from `events.jsonl`. | `telemetry.py`, orchestrator terminal hook |

### State machine / protocol changes

- Phases: `+SCOPE_GUARD` (pre-design), `+FOCUSED_REVISION` (execution). Edges: `DISCOVER→SCOPE_GUARD` only; `SCOPE_GUARD→{INTAKE, INVESTIGATE, HUMAN_HANDOFF}`; `INITIAL_REVIEW/CLOSURE_REVIEW/FINAL_REVIEW→FOCUSED_REVISION`; `FOCUSED_REVISION→{CLOSURE_REVIEW, WAITING_FOR_HUMAN, HUMAN_HANDOFF}`; `WAITING_FOR_HUMAN→FOCUSED_REVISION` (defensive convergence path).
- `SessionState`: `result_status`, `scope_verdict`, `last_correction_action` (the attempted-mechanism memory used by material-progress stops). Budgets: `max_focused_revision_rounds`/`focused_revision_used` (+ config key `focused_revision`).
- Events: `SCOPE_GUARD_STARTED/COMPLETED/STOPPED`, `GATE_CANDIDATE_DEFERRED`, `ACCEPTANCE_COVERAGE_RECORDED`, `CORRECTION_ROUTED`, `CORRECTION_STOPPED`, `NO_MATERIAL_PROGRESS_STOP`, `FOCUSED_REVISION_STARTED/COMPLETED`, `SESSION_RESULT_WRITTEN`, `TELEMETRY_WRITTEN`; `SESSION_DONE`/`SESSION_HUMAN_HANDOFF` now carry `result_status`.
- Exit codes unchanged (0/10/20/30/130); exit 10's meaning is now "terminal boundary — see session-result.md classification" and the CLI summary prints it (`HUMAN_HANDOFF [DESIGN_NOT_APPROVED]: …`).
- Adapters: `scope_guard(state, discovery)` and `focused_revise(state, contract, proposal, issues, allowed_scope, preserved_invariants)` on Pi (fake defaults: BOUNDED / a contract-respecting focused result — unscripted deterministic tests keep flowing); `final_review(..., acceptance_coverage)` on Codex; canonical phase names extended. `schemas/codex-review.schema.json` regenerated (correction/origin/coverage/recommendation definitions).
- Renderer: SCOPE_GUARD/FOCUSED_REVISION activity lines, scope-stop and correction-stop quiet-visible lines, result-status in DONE/HANDOFF terminal lines, session-result line.

### Preserved V0/V0.1/V0.2 invariants (verified by the unchanged suites)

Human Requirement Authority and all authority-check routing (COVERED / NEEDS_NEW / CANNOT_DETERMINE with fail-closed packet validation); mechanical PASS (Codex still never decides PASS); issue lifecycle ownership (ingest strips reviewer lifecycle + coverage fields); alias-space safety (B301) and 2–4 option cardinality (N301); gate state consistency; effective-answer semantics; interruption budget model (per-gate, default 2); protocol repair cap; phase-checkpoint recovery; fail-closed capability probes; read-only agent boundaries (scope guard and focused revision are read-only Pi calls); PROD-001 permanent replay.

### Intentional behavior changes (design-mandated; tests updated, not silently kept)

1. **Auto-ablation removed** (design §28): closure-unresolved without an explicit ABLATION recommendation now stops as DESIGN_NOT_APPROVED. Affected V0/V0.1-era tests were updated to script the explicit recommendation (m2 scenarios 3–5, m5/v01_rc2/v02_rc2 fixtures) — each update is annotated in the test file.
2. **Gate cap 3→6 + dependency-based deferral** (design §51): four independent candidates now produce ONE gate (E21, scenario 13 updated; new C5 suite covers deferral).
3. **Budget-exhaustion handoffs are classified** (design §17/§56): "convergence budget exhausted" reasons became "correction stopped: …" with `result_status=DESIGN_NOT_APPROVED`; authority-path handoffs classify NEEDS_HUMAN_DECISION.

## 3. Tests

- **Full deterministic suite: 360 passed, 2 skipped (~45s)** — V0.2-RC3 baseline 293 → **+67 V0.3 tests, 0 regressions**.
- New files:
  - `test_v03_scope_guard.py` (11) — BOUNDED continuation (incl. problem-mode), DECOMPOSITION_REQUIRED early termination (no budget, no gates, no design artifacts), OUT_OF_SCOPE, actionable split rendering, ≥2-children validation, unknown-verdict fail-closed, conservative-uncertainty recording, state-machine edges, guard-before-gate ordering.
  - `test_v03_correction_routing.py` (15) — FULL/FOCUSED/ABLATION/HUMAN_DECISION/STOP routing, priority rule, default FULL, ABLATION-never-auto, no-material-progress stop, progress continuation, PROGRESSED-note enforcement, budget-exhaustion stop, malformed action fail-closed, engine unit checks.
  - `test_v03_focused_revision.py` (7) — preserves decisions/task_revision (windowed assertions), no rediscovery, allowed-scope fail-closed, exact-targets fail-closed, issue-by-issue model validation, artifacts/budget/last_correction, separate-mechanism budget after full revision.
  - `test_v03_review_convergence.py` (15) — coverage recorded/persisted, FAIL-linkage + duplicate fail-closed, final superset enforcement (disappearance rejected), complete-coverage pass, late-blocker origin variants (allowed with provenance / auto-filled REGRESSION / downgraded unexplained / PREVIOUS_REVIEW_MISS-without-explanation downgraded), late-blocker focused-fix convergence, prompt-contract pins (evidence discrimination, differential+provenance, readiness+completeness).
  - `test_v03_gate_batching.py` (6) — six-in-one-gate, overflow deferral, dependency-based deferral with audit event, satisfied-dependency batching, mixed batching, V0.2 constraints preserved under batching.
  - `test_v03_session_result.py` (10) — APPROVED sections+readiness, frozen decisions, DESIGN_NOT_APPROVED sections + internal/user-facing separation, NEEDS_HUMAN_DECISION, FAILED minimal fallback (renderer crash never masks terminal state), agent-error FAILED, telemetry fields (both shapes), `show result` CLI, status output.
  - `test_v03_case_replay.py` (3) — the two case replays below.
- Design §60 checklist mapping: every listed item is covered by at least one test above or by an existing V0.2 suite ("all V0.2 regression tests" = the 293-test baseline remains green with only the three annotated, design-mandated behavior updates).

## 4. Case replay (deterministic fixtures)

Both replays are **structural abstractions** of the real audits — the failure pattern is kept, all domain-specific business terms are removed (no platform/product names; generic data-pipeline vocabulary). They live in the permanent suite so the real-case regressions cannot recur silently.

### Composite Case (source 84fb)

`test_composite_case_stops_before_design_with_decomposition` — a request mixing several independently decidable/deliverable concerns (comparison semantics + engine + operationalization + output + credentials/kill-switch), with a discovery that under V0.2 would have opened chained gates. Verified:

```text
scope guard → DECOMPOSITION_REQUIRED
→ stops BEFORE DESIGN (no DESIGN/INITIAL_REVIEW events, no proposal artifacts)
→ 0 interruptions, 0 correction budgets, round 0
→ session-result.md: 3 child sessions (title/goal/inputs/non_goals/dependencies)
→ split follows outcome boundaries; child dependencies recorded
→ "NOT executed automatically" boundary stated
```

### Bounded Convergence Case (source c454)

`test_bounded_case_design_not_approved_not_needs_human` — a bounded defect-fix design with four independent intake questions and one persistent evidence-quality blocker whose semantics are already decided. Verified:

```text
4 independent intake candidates → ONE gate (1 interruption; no same-second HG002)
R001 (BLOCKING REQUIREMENT, evidence quality) → authority check
→ COVERED_BY_ACTIVE_DECISION [D003] → engineering gap (no convergence gate)
→ CORRECTION_ROUTED action=FOCUSED_REVISION → focused revision (1/1)
→ closure: UNRESOLVED + NO_PROGRESS + recommends FOCUSED again
→ NO_MATERIAL_PROGRESS_STOP → DESIGN_NOT_APPROVED
   (ABLATION never auto-triggered, ablation 0/1, full revision 0/1)
→ session-result.md: Frozen Human Decisions + Remaining Blocking Issues
   with close conditions as hard inputs + engineering next action
→ NOT NEEDS_HUMAN_DECISION (agent convergence failure ≠ Human decision need)
```

Companion `test_bounded_case_focused_revision_closes_blocker_when_progress_holds` — the same local blocker closes after the focused revision → APPROVED without touching revision/ablation budgets.

## 5. Bounded real validation

Environment: pi (RPC, read-only allowlist) + codex (`exec -s read-only`), Windows host, driver `scripts/v03_e2e_driver.py` (real adapters + real renderer; only gate keystrokes scripted). Scratch repos under `C:\frank\aro-v03-e2e\` (sessions preserved).

**Budget consumed:** fresh real E2E sessions **2/2** · forcing request variants **0/2** (both natural samples — no manufactured complexity) · wall-clock **18.9 min / 60 min** (878s + 254s; the real-adapter smoke, 24 passed in 4:20, counted separately as adapter plumbing per prior audit practice).

| Run | Session | Scenario (natural) | Result |
| --- | --- | --- | --- |
| E2E-A | `20260915-100633-20ef` (`aro-v03-e2e/bounded`, retry-kit; request 「给重试工具增加退避上限和抖动，尽量最小改动，不要重构整个工具」) | Clearly bounded task | **DONE / APPROVED** in 14.6 min: Scope Guard BOUNDED (29.6s, uncertainty honestly recorded on the bounded verdict per §54); discovery emitted **4 independent candidates → ONE gate HG001 (4 questions, 1 interruption, all answered "1")**; initial review raised 3 BLOCKING DESIGN issues (evidence-quality shaped) **each recommended FOCUSED_REVISION** → `CORRECTION_ROUTED action=FOCUSED_REVISION` → real Pi focused revision **stayed inside the declared change scope** (changed_sections ⊆ allowed_scope on live output) → closure verified all three RESOLVED; a late REGRESSION finding arrived NON_BLOCKING with auto-origin `INTRODUCED_BY_CORRECTION`; one protocol retry recovered a real formatting drift; budgets: full 0/1, focused 1/1, ablation 0/1, interruptions 1/2; `final.md` + `session-result.md` (APPROVED, READY, frozen decisions, resolved issues with close-condition detail) + `telemetry.json` |
| E2E-B | `20260915-102219-5f42` (`aro-v03-e2e/composite`, sync-pipeline; request 「为同步链路建设对账能力：确定对账口径与时间语义、实现对账引擎、设计定时调度与告警通知、明确凭证管理与紧急开关」) | Naturally composite task | **DECOMPOSITION_REQUIRED in 4.2 min, stopped BEFORE DESIGN**: scope verdict grounded in repository facts (README wording + stub-only sources), decision-boundary analysis (independent outcomes, independent acceptance boundaries), **zero** gates/issues/proposals and all budgets untouched; session-result.md carries a genuinely actionable 3-session decomposition — the agent even merged semantics+engine into one child (correctly reasoning they are strongly coupled) and split scheduling/alerting and credentials/kill-switch as independent children, each with inputs/non-goals/dependencies |

Design §62 goals verified: Bounded — scope guard allowed continuation, usable result produced, convergence did not walk unrelated correction mechanisms (only FOCUSED_REVISION fired; FULL/ABLATION untouched). Composite — scope guard stopped before DESIGN and the decomposition guidance is useful. Low-probability branches (no-material-progress stop, NEEDS_HUMAN paths, FAILED fallback) were NOT forced on real agents — they are deterministic-fixture coverage by design (§61).

## 6. Known limitations

1. **Scope Guard judgment quality is Pi's** — the orchestrator validates structure and enforces continuation deterministically. A wrong-but-well-formed BOUNDED on a truly composite task would proceed (bounded by the downstream budgets as before); a wrong DECOMPOSITION_REQUIRED costs one discover+scope round. The conservative-classification + uncertainty field (§54) is the mitigation; real E2E-B shows repository-fact-grounded reasoning.
2. **Acceptance-coverage completeness depends on reviewer diligence** — mechanical enforcement is FAIL-linkage, duplicates and the final superset; a criterion the reviewer never enumerated in the initial review is invisible to the superset check. (c454-style misses of contract criteria remain possible if the initial review under-enumerates.)
3. **The final-coverage superset check is string-exact** — the final prompt embeds the initial criteria verbatim and protocol repair handles drift, but a real reviewer re-wording a criterion fails the session (FAILED, resumable at the FINAL_REVIEW boundary). Accepted fail-closed friction.
4. **Focused-revision scope containment is admission-based** — `changed_sections ⊆ change_scope` is checked mechanically only when the reviewer declared explicit scopes; semantic drift inside undeclared scope relies on closure review (differential delta evaluation).
5. **Material-progress assessment is reviewer-provided** — the orchestrator enforces the PROGRESSED-evidence rule and the repeat-stop rule, but a reviewer claiming PROGRESSED with plausible prose cannot be mechanically falsified (§49 accepts this boundary).
6. **Handoff sessions remain non-resumable** (unchanged V0 boundary); `session-result.md` + `handoff.md` are the structured inputs for the follow-up session.
7. **Gate cap 6 is a judgment call** — design §51 fixes the deferral rule but not the cap number; 6 covers the observed real-candidate counts (4–5) with REQUIREMENT_TOO_AMBIGUOUS beyond it.
8. Deferred (design §64, not implemented): automatic multi-session execution, parent-child orchestration, dependency propagation, free-form clarification conversation, annotation extraction, `covered_by_original_request` enhancement, complex interruption accounting, code implementation, PR/deployment automation.

## 7. Definition of Done (design §65) — status

1. Scope Guard exists after DISCOVER — met.
2. Unsuitable single-session tasks stop before DESIGN — met (deterministic + E2E-B).
3. DECOMPOSITION_REQUIRED provides actionable split guidance — met (goal/inputs/non_goals/dependencies; E2E-B quality).
4. Every terminal session creates `session-result.md` — met (DONE/boundary/FAILED + minimal fallback; deterministic tests incl. renderer-crash path).
5. Agent convergence failure is distinct from Human decision need — met (explicit classification at every handoff site; c454 replay).
6. Correction routing uses generic actions, not case-specific types — met (enum + deterministic engine; `focus_area` descriptive only).
7. Focused Revision exists — met (phase, budget, contract, real-agent E2E-A).
8. ABLATION is explicit only — met (auto-ladder deleted; tests pin it).
9. Review phases have differentiated contracts while preserving global safety — met (prompts + origin/coverage enforcement; late serious blockers stay reportable with provenance).
10. Evidence Quality is reviewed generically — met (Evidence Discrimination in the initial-review contract + validation-shaped c454 replay).
11. Convergence considers Material Progress rather than issue-id repetition — met (PROGRESSED/NO_PROGRESS + repeat-stop; same-blocker rounds only counted in telemetry).
12. Independent Human Gate candidates batch together — met (cap 6 + dependency-only deferral; E2E-A live).
13. All existing V0.2 safety and alias tests pass — met (293 baseline green with only the three design-mandated, annotated updates; +67 new).
14. Real validation stays within the mandatory budget — met (2/2 sessions, 0/2 forcing variants, 18.9/60 min).

---

# V0.3-RC1 — Correctness Fix Implementation Audit

**Status:** RC1 implemented — deterministic suite green (**404 passed, 2 skipped**; +42 tests over the V0.3 baseline of 360, 0 regressions), real Pi dependency-protocol validation green (1 session, 3.2 min), both structural case replays green
**Implemented against:** `docs/V0_3_RC1_FIX_SPEC.md` (B401–B405 only; no V0.4-style capability added)
**Baseline:** V0.3 (`841a472`)

## RC1.1 How B401–B405 were closed

| Blocker | Closure | Key code |
| --- | --- | --- |
| **B401** late blocker provenance fail-closed | Enforcement moved from an ingest-time severity downgrade to **schema validation at the review-result boundary**: `ClosureReviewResult`/`FinalReviewResult` model validators reject a new BLOCKING issue without `origin` (and `PREVIOUS_REVIEW_MISS` without `why_not_detected_initially`) — real agents get protocol repair, then FAILED. The deterministic REGRESSION → `INTRODUCED_BY_CORRECTION` default is preserved. `ingest_new_issues` keeps the same rule as orchestrator defense-in-depth (never downgrades). A missing-provenance defect can no longer produce DONE/APPROVED. | `models.py` (`enforce_late_blocker_provenance`), `phases/review.py`, prompts `closure_review.md`/`final_review.md` |
| **B402** Agent-usable HumanCandidate dependency protocol | `HumanCandidate` gains a packet-local **`candidate_id`** the Agent authors itself; `depends_on` now references those ids — never the internal decision-key hash. Packet validation (`validate_candidate_dependency_packet` on `DiscoveryResult` and `InvestigationResult`): ids unique; unknown/self/cyclic references invalid (fail closed with auditable reasons; protocol repair applies). After validation the orchestrator resolves ids to the existing internal stable `decision_key` (`depends_on_keys`, resolved per source packet at collection); persisted Human Decisions keep decision-key identity/supersession unchanged. Prompts (`discover.md`, `investigate.md`) expose the protocol. | `models.py`, `phases/intake.py`, `phases/human_gate.py`, prompts |
| **B403** Contract-owned current effective Acceptance Baseline | `ChangeContract` owns `acceptance_criteria: AcceptanceCriterion[]` (`id` A###, `criterion`, `authority_refs`). INTAKE synthesizes the baseline deterministically: **A001 ← REQUEST**, one criterion per ACTIVE Human Decision (← `D###`); assumptions/open questions never enter it. `AcceptanceCoverageEntry` gains `acceptance_id`; INITIAL and FINAL review coverage must equal the current baseline **by exact stable ID set** (missing/unknown/duplicate → fail closed); FAIL-linkage to a BLOCKING issue title retained. `effective_acceptance_baseline(o)` implements the documented **legacy compatibility rule** for pre-RC1 persisted sessions (baseline synthesized from persisted initial coverage, ids assigned in recorded order, REQUEST provenance attributed by the rule) — reachable only by resumed historical sessions, never a false-APPROVED path for new RC1 sessions. Task-revision rebuild archives the previous coverage to `history/acceptance-coverage-*.json`. | `models.py`, `phases/intake.py`, `phases/review.py`, `storage.py`, `rendering.py` (task.md section), prompts `initial_review.md`/`final_review.md`, `agents/codex.py` |
| **B404** actual-delta containment | The orchestrator computes **`actual_changed_sections`** (`design_actual_changed_sections`: deterministic structural diff over every top-level DesignResult semantic field + `change_map.*` subfields) between old and new serialized proposals. With an explicit `allowed_change_scope`, `actual_changed_sections ⊆ scope` (canonical section-name normalization: case/whitespace/hyphen) must hold — **Pi's self-reported `changed_sections` is explanation/audit only**; omission cannot bypass containment. Empty scope stays an explicitly distinguished *semantic* scope (`FOCUSED_REVISION_SEMANTIC_SCOPE` event). Every correction persists `correction-delta.json` (mechanism, previous proposal snapshot, actual/reported sections, targets, invariants); Closure Review receives it as deterministic delta context (`{{CORRECTION_DELTA}}` prompt section) instead of inferring the delta. Reviewers are instructed to use the canonical section vocabulary in `change_scope`. | `models.py` (delta helpers), `phases/focused_revision.py`/`revision.py`/`ablation.py`, `phases/review.py` (`save_correction_delta`), `agents/codex.py`, prompts |
| **B405** existing Requirement Authority reuse | The Human Authority Check evaluates the **current effective Requirement Authority**, not only ACTIVE decisions: `IssueAuthorityOutcome.authority_refs` may reference `D###` (ACTIVE decision), `A###` (current-baseline acceptance criterion) and `REQUEST`; coverage may combine refs. Every reference resolves mechanically (`_resolve_authority_refs`) — stale/superseded decisions and old-revision criteria fail closed to a NEEDS_HUMAN_DECISION-classified handoff. Covered issues revert to OPEN engineering blockers carrying auditable `covered_by_authority` (full ref list) + `covered_by_decisions`; they never re-enter the gate path (phase-entry re-checks and `_derive_result_status` updated). Prompt updated (`human_authority_check.md`). | `models.py`, `phases/human_gate.py`, `phases/review.py`, `orchestrator.py`, prompt |
| **§9 regression** risk ≠ compositeness | No Scope Guard redesign: prompt guidance states the axes are different (high risk means deeper review, never DECOMPOSITION_REQUIRED by itself) and a deterministic regression pins high-risk-but-coherent → BOUNDED continues to DESIGN. | prompt `scope_guard.md`, `test_v03_rc1_fixes.py` |

## RC1.2 Schema / state / prompt changes (minimal)

- **Schema:** `AcceptanceCriterion` (new), `ChangeContract.acceptance_criteria`, `AcceptanceCoverageEntry.acceptance_id`, `HumanCandidate.candidate_id` + `depends_on_keys` (`depends_on` semantics now candidate-id based), `IssueAuthorityOutcome.authority_refs`, `Issue.covered_by_authority`, late-provenance validators on closure/final results. `schemas/codex-review.schema.json` regenerated.
- **State machine:** unchanged (no new phases/edges; correction-delta is a persisted artifact, not a state).
- **Prompts:** discover/investigate (candidate_id protocol), initial/final review (ID-based coverage), closure (correction-delta section + fail-closed provenance wording), focused revision (canonical section names + actual-delta truth), human authority check (authority_refs), scope guard (risk vs compositeness).
- **Fixtures:** c454/84fb replays and focused/coverage fixtures updated to the RC1 protocols (baseline-ID coverage; canonical scopes; proposals echo the current design). Fake adapters model "a well-behaved reviewer accounts for the baseline" (auto-fill only when a scripted/default reply predates the id protocol) and the default focused revision mutates only in-scope fields.

## RC1.3 Targeted tests (all green)

`test_v03_rc1_fixes.py` (**38 new**): B402 duplicate/unknown/self/cycle rejection with auditable reasons + public-protocol ordering (C1 → HG001, C2 deferred until D001 ACTIVE, internal key stability) + batching + persisted ids; B403 non-empty baseline, decision-extended rebuild with history preservation, authority-ref validation, unknown/duplicate/missing-ID fail-closed, legacy compatibility rule + legacy empty-coverage cannot approve, reviewer-invented criterion rejected; B404 reported-ok-but-actual-outside rejected, omission bypass rejected, in-scope accepted + normalization, semantic-scope distinction, closure delta context (storage + real-adapter prompt render); B405 baseline/REQUEST/combined coverage (no gate, engineering correction), unknown/stale refs fail closed, genuinely-new still gates; Scope Guard high-risk BOUNDED regression; Acceptance/Authority + late-blocker + missing-coverage replays. Updated: `test_v03_review_convergence.py` (B401 fail-closed + ID coverage, 6 new), `test_v03_gate_batching.py` (public protocol), `test_v03_focused_revision.py` (actual-delta fixtures), `test_m2_issues_budgets.py` (downgrade test → fail-closed), 2 wording-only assertions in `test_v02_authority_convergence.py`, `test_m5_codex_adapter.py` prompt-render kwargs.

## RC1.4 Full regression + case replay

- **Full deterministic suite: 404 passed, 2 skipped (~71 s) — 1 post-change run.** (V0.3 baseline 360+2; +42, 0 regressions. All V0/V0.1/V0.2 safety invariants green: alias space, 2–4 options, custom decisions, latest-effective answers, authority check, PROD-001 replay, checkpoint recovery, no automatic ABLATION, focused-budget separation, terminal classifications.) A cosmetic enum-literal fix in one RC1 test helper afterwards was covered by rerunning that file (38/38); no further full run was needed.
- **Case replays green:** 84fb composite → DECOMPOSITION_REQUIRED before DESIGN (fixture untouched); c454 bounded → one gate for 4 decisions → COVERED via D003 → FOCUSED_REVISION → NO_MATERIAL_PROGRESS_STOP → DESIGN_NOT_APPROVED (fixture updated to the 5-criterion baseline A001←REQUEST + A002..A005←D001..D004 and canonical `verification_plan` scope; behavior identical). No automatic ABLATION; engineering non-convergence = DESIGN_NOT_APPROVED.

## RC1.5 Real-agent validation — B402 (mandatory, within budget)

**Budget consumed: fresh real sessions 1/2 · forcing variants 0/1 · wall-clock 3.2 min / 30 min.** Validation stopped once the protocol invariant was proven (fix spec §13/§15).

Session `20260915-125428-21a0` (scratch repo `C:\frank\aro-rc1-b402\export-tool`, natural request: a structured-export capability whose configuration items depend on the format choice; driver `scripts/v03_e2e_driver.py`; only gate keystrokes scripted). Verified **from persisted artifacts/events, no injected keys**:

```text
Pi's raw discover reply itself authors candidate_id C1..C4
(raw/pi-discover.jsonl contains candidate_id; discovery.json persists them)
C1 (FACT, independent) + C4 (TRADE_OFF, independent)  -> batched into HG001
C2 (depends_on [C1]) and C3 (depends_on [C2])         -> GATE_CANDIDATE_DEFERRED
                                                        (candidate_ids [C2, C3])
HG001 closed -> D001/D002 ACTIVE -> task_revision 2 -> HG002 asks C2 only
C3 stays deferred at the second round (transitive chain works)
gate questions use the internal hash decision keys (FACT-48467d60 ...) -
candidate ids never leak into persisted decision identity
```

## RC1.6 Known limitations

1. **Legacy sessions that persisted V0.3 decision-key `depends_on` references cannot resume** under RC1 packet validation (unknown candidate ids) — explicit, documented compatibility break; no known real session used `depends_on` (both V0.3 E2E sessions predate any dependency use).
2. **Fake-adapter coverage auto-fill** models a well-behaved reviewer for pre-RC1 fixtures; scripted non-empty coverage is never modified, and the empty-coverage fail-closed rule is additionally unit-tested at the validator boundary.
3. **Actual-delta containment is structural** — it proves which serialized sections changed, not the semantic size of a change inside an allowed section; semantic drift within an in-scope section remains closure review's responsibility (unchanged V0.3 boundary).
4. **Canonical section vocabulary is a convention** — prompts instruct reviewers to use canonical names and matching normalizes case/whitespace/hyphens, but a reviewer using a non-canonical label on a real session fails closed (protocol repair recovers; accepted friction, same class as the V0.3 string-exact final coverage check).
5. Deferred items from the fix spec (N402 stronger material-progress evidence, N403 mandatory correction_action, full Living Requirement system, free-form Human conversation, annotation extraction, interruption accounting, multi-session orchestration, new budgets/rounds) remain **not implemented** by RC1.

## RC1.7 Natural real-business validation

```text
RC1 correctness mechanically validated
real Pi dependency protocol validated
natural real-business validation pending next suitable task
```

Per fix spec §14: the next suitable real bounded engineering task is the natural sample (record scope verdict, time to first proposal, elapsed, interruptions, correction counts, baseline size/authority sources, initial coverage completeness, late blockers + provenance, existing-authority coverage count, terminal result, session-result usability). No fake business task was manufactured.

## RC1.8 Commit

Recorded in the repository history immediately after this audit (RC1 commit; see the final report for the SHA).
