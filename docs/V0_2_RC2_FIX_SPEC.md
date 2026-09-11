# Agent Review Orchestrator V0.2 RC2 Remediation Specification

**Status:** Required before V0.2 final real Shopify validation
**Baseline:** V0.2 implementation `f5038c1b37a2c8599f918a46f0335fa8db7a9b22`
**Review status:** V0.2-RC1 — three blocking protocol gaps found in independent review
**Scope:** Close only the Human Authority / Convergence protocol gaps identified after V0.2 implementation review. Do not expand into V0.3 telemetry, role routing, multi-reviewer, source implementation, or generic workflow changes.

---

## 1. Review conclusion

V0.2 successfully implemented the main Human Decision & Convergence direction:

- explicit Custom Human Decisions;
- unmatched free text does not silently acquire Requirement Authority;
- blocking REQUIREMENT/FACT issues in Initial/Closure Review can run a Human Authority Check;
- ACTIVE Decision coverage can route a semantic issue back to the solution-correction path;
- true new Human decisions can open a resumable Convergence Gate;
- Gate persistence/current/history/Markdown consistency was repaired;
- latest-effective-answer validation was introduced;
- structured `handoff.md` was added;
- PROD-001 was turned into a permanent deterministic replay.

However, independent review found three protocol gaps that still violate the V0.2 specification and Human Authority guarantees.

V0.2 should therefore remain **RC1** until B201-B203 below are resolved.

---

## 2. Blocking findings

## B201 — FINAL_REVIEW bypasses Human Authority Check / Convergence Gate

### Problem

V0.2 specification explicitly states that a true new Human-owned decision discovered in downstream review may open a Convergence Gate from:

```text
INITIAL_REVIEW / CLOSURE_REVIEW / FINAL_REVIEW
        ↓
Human Authority Check
        ↓
covered by ACTIVE decision → solution correction
new Human decision required → Convergence Gate
cannot determine / no budget → HUMAN_HANDOFF
```

The current implementation applies V0.2 routing after Initial Review and Closure Review, but `run_final()` still follows the old V0 path:

```text
FINAL_REVIEW
→ ingest reviewer issues
→ compute PASS
→ PASS ? FINALIZE : HUMAN_HANDOFF
```

It does not invoke `_need_human_ids()`, `route_after_failed_pass()`, or `resolve_need_human_issues()`.

The state machine also currently allows:

```text
FINAL_REVIEW → FINALIZE | HUMAN_HANDOFF
```

but not:

```text
FINAL_REVIEW → WAITING_FOR_HUMAN
```

Therefore a blocking REQUIREMENT/FACT issue discovered in Final Review can still terminate the session even when:

- the issue is already covered by an ACTIVE Human Decision; or
- a safe new Human Decision Candidate can be derived; and
- Human interruption budget remains.

### Impact

This breaks the primary V0.2 promise that downstream Human-owned decisions are resumable rather than prematurely terminal.

Current coverage is effectively:

```text
INITIAL_REVIEW  ✅
CLOSURE_REVIEW  ✅
FINAL_REVIEW    ❌
```

### Required correction

FINAL_REVIEW must use the same Human Authority routing semantics as other review phases when mechanical PASS fails because of blocking REQUIREMENT/FACT issues.

Requirements:

1. After Final Review issue ingestion and lifecycle processing, compute mechanical PASS as today.
2. If PASS succeeds, preserve existing `FINALIZE` behavior.
3. If PASS fails and blocking REQUIREMENT/FACT issues are present:
   - emit/retain the normal audited NEED_HUMAN transition;
   - run Human Authority Check;
   - `COVERED_BY_ACTIVE_DECISION` must not hand off merely because the reviewer category is REQUIREMENT/FACT;
   - `NEEDS_NEW_HUMAN_DECISION` must be able to open a Convergence Gate when budget remains;
   - `CANNOT_DETERMINE`, invalid packet, or exhausted Human budget must fail closed to structured HUMAN_HANDOFF.
4. Add `FINAL_REVIEW → WAITING_FOR_HUMAN` to the deterministic state-machine transition table.
5. Do not weaken the ablation budget rule. After a Human decision changes the design basis, the workflow rebuilds from the new task revision; it is not “continuing Final Review in place.”
6. Preserve the invariant that Codex never decides PASS.

### Acceptance tests

At minimum:

```text
B201-A
FINAL_REVIEW raises BLOCKING REQUIREMENT
ACTIVE decision already covers semantics
→ Human Authority Check = COVERED_BY_ACTIVE_DECISION
→ no immediate category-driven HUMAN_HANDOFF
→ workflow follows the valid correction/redesign path allowed by the new task/budget state
```

```text
B201-B
FINAL_REVIEW raises BLOCKING REQUIREMENT
no ACTIVE decision covers it
Human budget remains
Pi returns valid NEEDS_NEW_HUMAN_DECISION candidate
→ Convergence Gate opens
→ Human answers option/custom
→ task_revision++
→ prior proposal/issues become stale/superseded
→ workflow rebuilds design basis
```

```text
B201-C
same scenario, but Human budget exhausted
→ no Gate
→ structured HUMAN_HANDOFF + handoff.md
```

---

## B202 — Problem Mode FACT Convergence Decision loses re-investigation semantics

### Problem

V0.2 requires first-class Human Decisions, including FACT decisions, to participate in Problem Mode re-investigation.

The normal V0 FACT Gate already has the intended behavior:

```text
Problem Mode + FACT Gate closed
→ task_revision++
→ INVESTIGATE
```

But V0.2 Convergence Gates are always stored as:

```text
gate.category = CONVERGENCE
```

regardless of whether the underlying Human Decision Candidate category is REQUIREMENT, FACT, TRADE_OFF, or SCOPE.

Gate close currently decides the next phase using:

```text
if task_kind == PROBLEM and gate.category == FACT:
    INVESTIGATE
else:
    INTAKE
```

Therefore a downstream FACT issue in Problem Mode produces:

```text
Review discovers new FACT decision
→ Convergence Gate(category=CONVERGENCE)
→ Human establishes new fact
→ task_revision++
→ INTAKE
```

instead of:

```text
→ INVESTIGATE
```

This can combine a newly established Human fact with a stale Evidence / Causal Chain / Root Cause from the previous investigation.

### Impact

This violates the design-basis invalidation principle:

> A material new fact must not be combined with an old root-cause model as if nothing changed.

The dangerous state is:

```text
new authoritative FACT
+
old InvestigationResult / old root cause
→ new Change Contract
```

### Required correction

Convergence provenance and decision semantics must be represented separately.

`CONVERGENCE` means **where the Gate came from**; it must not erase **what kind of Human fact/decision was established**.

Acceptable implementation shapes include:

```text
HumanGate
- category = CONVERGENCE
- resume_semantics = FACT | REQUIREMENT | TRADE_OFF | SCOPE
```

or deriving the resume semantic deterministically from the Gate questions, provided ambiguity is mechanically rejected.

Requirements:

1. A Problem Mode Convergence Gate whose effective Human decision establishes FACT semantics must transition to `INVESTIGATE` after decision application and task revision invalidation.
2. The new ACTIVE FACT Decision must be passed into the re-investigation context exactly like existing FACT decisions.
3. Requirement/Trade-off/Scope Convergence Decisions continue through INTAKE unless another existing rule says otherwise.
4. Mixed semantic Gate packets must have a deterministic rule. Prefer one of:
   - reject mixed FACT/non-FACT convergence packets and split them before opening the Gate; or
   - explicitly define a conservative resume phase (e.g. INVESTIGATE if any decision is FACT in Problem Mode).
   Do not silently depend on `gate.category=CONVERGENCE`.
5. Preserve task-revision invalidation and stale proposal/issue behavior.

### Acceptance tests

```text
B202-A
Problem Mode
→ review raises BLOCKING FACT
→ Authority Check = NEEDS_NEW_HUMAN_DECISION(category=FACT)
→ Convergence Gate
→ Human selects option
→ task_revision++
→ transition INVESTIGATE
→ new ACTIVE FACT Decision is included in Pi investigate context
```

Repeat with Custom Decision:

```text
B202-B
... → custom FACT decision
→ same INVESTIGATE behavior
```

Also add a guard:

```text
B202-C
Problem Mode + REQUIREMENT convergence decision
→ INTAKE (not INVESTIGATE solely because Gate source is convergence)
```

---

## B203 — Human Decision Candidate identity/provenance validation is incomplete

### Problem

V0.2 correctly treats Agent output as untrusted and mechanically validates many candidate fields, but the current Candidate packet boundary still accepts several structurally ambiguous forms that can corrupt Human Decision semantics.

Three concrete gaps were found.

### B203.1 `source_issue_ids` is not validated against the authority-check issue

Current validation only requires `candidate.source_issue_ids` to be non-empty.

It does not require:

```text
outcome.issue_id ∈ candidate.source_issue_ids
candidate.source_issue_ids ⊆ current authority-check issue_ids
```

Later, Gate construction silently filters unknown ids:

```text
for source id:
    keep it only if id in issue_ids
```

This can transform an invalid convergence packet into a normal Gate.

Example:

```text
outcome.issue_id = R001
candidate.source_issue_ids = [R999]
```

If the invalid id is filtered away, `source_issue_ids=[]`; `create_gate()` then computes `is_convergence=False`, losing Convergence category/provenance instead of failing closed.

#### Required correction

Mechanically require:

- `outcome.issue_id` must appear in `candidate.source_issue_ids`;
- every `candidate.source_issue_id` must belong to the current authority-check batch;
- no unknown source issue id is silently discarded;
- invalid provenance fails closed before Gate creation or issue mutation.

### B203.2 Option keys must be unique within each GateQuestion

Current model validates option count and recommendation membership, but not unique option keys.

A malformed packet can contain:

```text
1. [fix] option A
2. [fix] option B
```

Human can choose `2` by index. `match_option()` identifies the second option, but Decision persistence later looks up the label by `option_key` and takes the first matching option.

Result:

```text
Human selected option B
→ persisted Decision may contain option A label
```

This directly violates Human Authority.

#### Required correction

- GateQuestion option keys must be unique after the same normalization used for answer matching.
- Prefer enforcing this at the shared `GateQuestion` model boundary so both normal Intake gates and Convergence Gates inherit the invariant.
- Duplicate normalized keys must fail closed; do not auto-rename Agent keys.
- Recommendation validation occurs after uniqueness validation.

### B203.3 Multiple candidates must not collide on the same `decision_key`

`decision_key` is derived from normalized conceptual identity (`category + question`). Multiple Authority outcomes can currently generate identical category/question pairs with different option packets.

Because Gate answer tracking is keyed by `decision_key`, duplicate keys can cause:

- one answer to make multiple questions appear answered;
- historical/effective answer selection to collapse independent questions;
- Decision supersession semantics to treat distinct questions as one authority fact.

#### Required correction

Before opening a multi-question Convergence Gate:

- generated `decision_key`s must be unique;
- duplicate keys must either:
  1. be mechanically proven to represent an identical packet and deterministically merged; or
  2. fail closed.

For V0.2 RC2, **fail closed on duplicate decision_key is preferred** because it is simpler and safer.

### Additional candidate validation requirements

For RC2, also enforce:

- `DecisionCandidate.category` must be one of `REQUIREMENT | FACT | TRADE_OFF | SCOPE`; `CONVERGENCE` is a Gate routing category, not a Human decision semantic category;
- normalized option keys must not collide with reserved custom selectors;
- every option key and label remains non-empty;
- recommendation must reference exactly one valid unique option key;
- already-ACTIVE `decision_key` remains invalid for `NEEDS_NEW_HUMAN_DECISION` (existing behavior preserved).

### Acceptance tests

Add regressions for all malformed packets:

```text
candidate source_issue_ids excludes outcome.issue_id       → HANDOFF / fail closed
candidate source_issue_ids contains unknown batch issue     → HANDOFF / fail closed
candidate category = CONVERGENCE                            → HANDOFF / fail closed
duplicate option key                                        → rejected before Gate creation
duplicate normalized option key                             → rejected before Gate creation
two candidates produce same decision_key                    → rejected before Gate creation
```

And verify:

```text
no malformed Gate is persisted
no Human interruption is consumed when packet validation fails before Gate creation
no issue is downgraded/reclassified due to an invalid packet
handoff.md explains the invalid authority packet boundary
```

---

## 3. Non-blocking findings

## N201 — `handoff.md` is described as guaranteed but implementation is best-effort

### Observation

The implementation audit states that every HUMAN_HANDOFF writes `handoff.md`, but `Orchestrator.handoff()` currently wraps rendering/writing in a broad best-effort `try/except Exception: pass`.

This protects the authoritative terminal state from being masked by a presentation failure, which is correct. But it means the durable package is not actually guaranteed.

### Recommended correction

Do not make handoff rendering failure overwrite the already-persisted HUMAN_HANDOFF state.

Instead add a minimal deterministic fallback, for example:

```text
try full render_handoff(...)
except:
    write minimal handoff.md containing:
    - session id
    - raw sanitized handoff reason
    - blocking issue ids if readable
    - explicit terminal/non-resumable boundary
```

If even the minimal write fails, keep HUMAN_HANDOFF authoritative and emit/log a best-effort `HANDOFF_WRITE_FAILED` event when possible.

This is recommended but not required to unblock RC2 unless the implementation is local and low risk.

---

## N202 — Human Authority Check prompt contains a contradictory instruction about options

### Observation

The prompt correctly requires Pi to produce 2-4 candidate options for `NEEDS_NEW_HUMAN_DECISION`, but later says:

```text
Do not invent options the Human never saw.
```

These instructions conflict: the entire purpose of the authority check is often to derive new candidate options the Human has not yet seen.

### Recommended correction

Replace with semantics such as:

```text
Do not invent Human decisions or claim that a proposed option is already Human-approved.
You MAY propose 2-4 decision options when a new Human decision is required.
They are suggestions only; the Human may reject all of them and use the explicit custom-decision path.
```

This better reflects V0.2 Human Authority.

---

## 4. Required RC2 regression suite

In addition to all existing V0/V0.1/V0.2 tests, add focused RC2 regressions covering:

### Final Review convergence

1. FINAL_REVIEW REQUIREMENT covered by ACTIVE decision does not category-handoff.
2. FINAL_REVIEW genuine new Human decision opens Convergence Gate when budget remains.
3. Custom answer from that Gate becomes ACTIVE, increments task revision, invalidates stale design, and rebuilds.
4. Exhausted Human budget produces structured handoff.

### Problem Mode FACT convergence

5. Downstream FACT Convergence Decision in Problem Mode re-enters INVESTIGATE.
6. Custom FACT decision does the same.
7. New fact is passed into re-investigation context.
8. REQUIREMENT convergence continues through INTAKE.

### Candidate packet integrity

9. Unknown/mismatched `source_issue_ids` rejected.
10. Outcome issue missing from candidate provenance rejected.
11. `category=CONVERGENCE` rejected as Decision semantic category.
12. Duplicate option keys rejected.
13. Duplicate normalized option keys rejected.
14. Duplicate generated `decision_key`s across candidates rejected.
15. Invalid packet creates no Gate and consumes no Human interruption.
16. Invalid packet leaves original Issue authority state auditable and fails closed with structured handoff.

### Preservation

17. Existing Custom Decision tests remain green.
18. PROD-001 permanent replay remains green.
19. Existing Initial/Closure authority routing remains green.
20. Gate current/history/Markdown consistency remains green.
21. V0.1 runtime/session presentation tests remain green.

---

## 5. Real-agent validation required for RC2

After deterministic tests pass, run real Pi/Codex smoke.

At least one focused real-agent E2E should cover a path not already proven by the original V0.2 E2E:

Preferred:

```text
Problem Mode
→ downstream FACT issue
→ Human Authority Check = NEEDS_NEW_HUMAN_DECISION
→ Convergence Gate
→ Human option/custom FACT decision
→ INVESTIGATE again with that decision
→ rebuild design basis
```

If reliably forcing that real path is impractical, run a real Final Review Convergence case instead and retain deterministic coverage for the Problem FACT path.

Do not declare RC2 complete using fake adapters only.

---

## 6. RC2 exit criteria

V0.2-RC2 is ready for real Shopify validation only when:

1. FINAL_REVIEW obeys the same Human Authority semantics as Initial/Closure Review.
2. FINAL_REVIEW can enter WAITING_FOR_HUMAN through a valid Convergence Gate.
3. Problem Mode FACT convergence causes re-investigation with new Human facts.
4. Convergence provenance and semantic category are represented separately enough to choose the correct resume phase.
5. Candidate provenance is exact and mechanically validated.
6. Option keys are unique and cannot mis-record a Human selection.
7. Duplicate decision identities cannot collapse multiple Human questions.
8. All malformed Agent packets fail closed before Gate creation / budget consumption.
9. Existing PROD-001 regression remains green.
10. Full deterministic suite passes with no V0/V0.1/V0.2 regression.
11. Real Pi/Codex smoke remains healthy.
12. A focused real-agent RC2 E2E validates at least one newly repaired path.
13. `docs/V0_2_IMPLEMENTATION_AUDIT.md` is updated with the RC2 remediation and evidence.
14. `docs/V0_LESSONS_LEARNED.md` records reusable findings from this review.

---

## 7. Non-goals

RC2 does not implement:

- V0.3 telemetry aggregation;
- heartbeat/renderer telemetry decoupling;
- phase-attempt commit/rollback telemetry semantics;
- increased Human interruption budget;
- resumable terminal HUMAN_HANDOFF sessions;
- role-based Agent assignment;
- multi-reviewer;
- source-code implementation/deployment;
- generic workflow DSL.

The goal is to complete the V0.2 Human Authority protocol, not broaden the product surface.