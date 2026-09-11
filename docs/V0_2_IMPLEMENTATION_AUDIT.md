# Agent Review Orchestrator V0.2 Implementation Audit

**Status:** V0.2 — implemented; deterministic suite green; real Pi/Codex smoke green; real-agent E2E validated (custom decision, decision coverage, convergence gate, structured handoff)
**Audit type:** Implementation summary + verification record
**Implemented against:** `docs/V0_2_HUMAN_DECISION_CONVERGENCE_SPEC.md`
**Baseline:** V0.1-RC3 (`b93f2f0`)

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
12. Full deterministic suite passes without V0/V0.1 regression — met (229 passed; baseline 193 all green).
13. Real Pi/Codex smoke healthy — met (2/2 smoke within the 24 adapter tests).
14. Real-agent custom-decision and convergence-gate scenarios pass — met (E2E-A/C/D).
