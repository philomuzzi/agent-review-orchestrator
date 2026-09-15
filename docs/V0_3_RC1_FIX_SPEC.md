# Agent Review Orchestrator V0.3-RC1 — Correctness Fix Spec

## 1. Status

Status: READY FOR IMPLEMENTATION

Target baseline:

```text
V0.3
commit: 841a4720f4c771bc574f36ec92d29cb19261b116
```

Primary Source of Truth:

```text
docs/V0_3_CONVERGENCE_QUALITY_DESIGN.md
```

This RC1 is a focused correctness repair after independent review of V0.3.

It MUST NOT expand into a new workflow redesign.

---

# 2. RC1 Scope

RC1 fixes exactly these items:

```text
B401  Late blocking issue provenance must fail closed
B402  Human Gate dependency protocol must be usable by real Agents
B403  Acceptance baseline must be Contract-owned and mechanically complete
N401  Focused Revision containment should validate actual proposal delta
```

The first three are release blockers.

N401 is included because it is directly adjacent to the new Focused Revision safety boundary and can be repaired without introducing a new product capability.

Explicitly deferred:

```text
N402  stronger mechanical Material Progress evidence
N403  removal of default FULL_REVISION when correction_action is absent
covered_by_original_request
Human free-form clarification / annotations
advanced interruption accounting
multi-session orchestration
new budgets / extra correction rounds
```

---

# 3. B401 — Late Blocker Provenance Must Fail Closed

## Problem

Current V0.3 behavior allows a new BLOCKING issue discovered in CLOSURE_REVIEW or FINAL_REVIEW to be mechanically downgraded to NON_BLOCKING when required provenance metadata is missing.

Examples:

```text
origin missing
PREVIOUS_REVIEW_MISS without why_not_detected_initially
```

This converts a Reviewer protocol defect into a lower engineering severity and may allow a false PASS.

The governing invariant is:

> A serious issue must never be suppressed or downgraded merely because it was discovered late.

`origin` explains why the issue appeared late. It does not determine whether the issue is actually blocking.

## Required Behavior

For a new BLOCKING issue in a late review phase:

```text
valid required provenance
→ ingest as BLOCKING

missing / invalid required provenance
→ protocol invalid
→ protocol repair
→ if repair still invalid: FAILED
```

Do NOT convert the issue to NON_BLOCKING.

A REGRESSION issue may still receive a deterministic default:

```text
origin = INTRODUCED_BY_CORRECTION
```

when this follows mechanically from existing semantics.

For:

```text
origin = PREVIOUS_REVIEW_MISS
```

`why_not_detected_initially` must be non-empty or the packet is invalid.

## Acceptance Criteria

- Missing `origin` on a late BLOCKING issue cannot lead to DONE / APPROVED.
- Missing `why_not_detected_initially` for PREVIOUS_REVIEW_MISS cannot lead to severity downgrade.
- Valid late BLOCKING issues remain BLOCKING.
- NON_BLOCKING late issues do not require blocker provenance.
- Existing REGRESSION compatibility behavior remains deterministic and tested.

---

# 4. B402 — Human Gate Dependency Protocol Must Be Agent-Usable

## Problem

V0.3 introduced:

```text
HumanCandidate.depends_on
```

but it currently expects references to orchestrator-generated `decision_key` values derived from internal hashing of category + question.

Unit tests can compute those keys directly, but a real Pi Agent has no stable, documented way to know another candidate's generated decision key while producing one Discovery packet.

Therefore the dependency mechanism is structurally implemented but not a reliable Agent protocol.

## Required Design

Give Human candidates an explicit packet-local identity that the Agent can author and reference.

Recommended shape:

```yaml
human_candidates:
  - candidate_id: C1
    category: REQUIREMENT
    question: ...
    depends_on: []

  - candidate_id: C2
    category: REQUIREMENT
    question: ...
    depends_on: [C1]
```

Requirements:

- `candidate_id` is local to one Agent packet.
- It must be non-empty and unique within that packet.
- `depends_on` references candidate IDs, not internal decision keys.
- Unknown dependency IDs fail closed / suppress the malformed packet according to the existing safe candidate-validation boundary; they must never be silently treated as independent.
- Self-dependency is invalid.
- Cycles must not produce an infinite or ambiguous gate plan; detect them deterministically and fail closed or terminate as REQUIREMENT_TOO_AMBIGUOUS with an auditable reason.
- After validation, the Orchestrator may map `candidate_id` to its internal stable `decision_key`.
- Persisted Human decisions continue using the existing decision-key semantics; this RC must not change V0.2 authority identity or supersession rules.

Update every Agent prompt/schema that can produce `HumanCandidate` so the dependency protocol is actually visible and usable.

## Acceptance Criteria

- A real Agent can express `C2 depends on C1` without knowing any internal hash function.
- Two independent candidates batch into one gate.
- A dependent candidate is deferred until its dependency is ACTIVE.
- Satisfied dependencies batch normally on the next evaluation.
- Unknown/self/cyclic dependency declarations do not silently become independent questions.
- All V0.2 Human Answer Alias Space and 2–4 option invariants remain unchanged.

---

# 5. B403 — Acceptance Baseline Must Be Contract-Owned

## Problem

Current V0.3 acceptance coverage guarantees only that criteria enumerated by INITIAL_REVIEW cannot disappear later.

It does not prove that INITIAL_REVIEW enumerated the complete Requirement acceptance set.

The current model also permits:

```text
InitialReviewResult.acceptance_coverage = []
```

which can allow a no-issue review to reach APPROVED without any mechanically known acceptance baseline.

This does not fully solve the real failure mode V0.3 was intended to address: a requirement can exist from the beginning but only be discovered by a later review.

## Required Design

The acceptance baseline must belong to the Change Contract, not to the Reviewer.

Extend the contract with stable acceptance criteria, conceptually:

```yaml
acceptance_criteria:
  - id: A001
    criterion: ...
  - id: A002
    criterion: ...
```

The exact field names may follow repository conventions, but the semantics are mandatory:

- Acceptance criteria are produced/frozen as part of the Requirement basis before DESIGN.
- IDs are stable within the task revision.
- A Human Decision that changes the design basis may regenerate/supersede the contract through the existing `task_revision` mechanism.
- Reviewer phases do not invent the authoritative acceptance baseline.

INITIAL_REVIEW must account for every contract acceptance ID:

```text
Contract IDs == Initial Review coverage IDs
```

FINAL_REVIEW must re-account the same baseline:

```text
Contract IDs == Final Review coverage IDs
```

No missing IDs, no duplicates, no unknown IDs.

A failed acceptance item must still link to a BLOCKING issue.

## Backward / Test Compatibility

Do not weaken the requirement merely to keep old fake adapters flowing.

Update fake/default fixtures so new sessions have a valid minimal acceptance baseline.

For genuinely old persisted sessions lacking the field, choose an explicit compatibility rule and document it. Compatibility must not create a false APPROVED path for newly created V0.3-RC1 sessions.

## Acceptance Criteria

- A newly created session cannot APPROVE with an empty authoritative acceptance baseline.
- INITIAL_REVIEW cannot omit a contract acceptance ID.
- INITIAL_REVIEW cannot add unknown acceptance IDs as if they were authoritative requirements.
- FINAL_REVIEW cannot omit or rename acceptance IDs.
- FAIL coverage still points to a BLOCKING issue.
- Human Decision / `task_revision` semantics remain unchanged.

---

# 6. N401 — Validate Actual Focused-Revision Delta

## Problem

Current Focused Revision containment checks:

```text
reported changed_sections ⊆ allowed_change_scope
```

This validates what Pi says it changed, not what the serialized proposal actually changed.

A Pi response could unintentionally modify unrelated proposal fields while reporting only allowed sections.

## Required Behavior

Before replacing the current proposal, compute a deterministic structural delta between:

```text
old DesignResult
new DesignResult
```

At minimum compare all top-level DesignResult fields relevant to design semantics.

Produce an orchestrator-owned set such as:

```text
actual_changed_sections
```

When an explicit focused `allowed_change_scope` exists:

```text
actual_changed_sections ⊆ allowed_change_scope
```

must hold, otherwise fail closed.

Agent-reported `changed_sections` may remain for explanation/audit but must not be the source of truth for containment.

Also provide Closure Review enough delta context to perform its differential review reliably. Prefer explicit old/new or computed-delta context rather than asking the Reviewer to infer history from the final proposal alone.

## Acceptance Criteria

- An undeclared actual proposal change outside allowed scope is rejected.
- Agent omission from `changed_sections` cannot bypass containment.
- Allowed focused changes continue normally.
- Empty explicit scope vs semantic/unbounded scope remains intentionally distinguished and documented.
- Closure Review receives reliable correction-delta context.

---

# 7. Non-Goals / Do Not Change

RC1 MUST NOT:

- add new correction actions;
- increase revision/focused/ablation budgets;
- reintroduce automatic ABLATION fallback;
- change `DESIGN_NOT_APPROVED` vs `NEEDS_HUMAN_DECISION` semantics;
- redesign Scope Guard;
- implement automatic decomposition execution;
- redesign Material Progress beyond what is necessary for these fixes;
- redesign Human interaction into a conversation protocol.

The successful V0.3 architecture remains intact:

```text
Scope Guard
Terminal Result Contract
Generic Correction Action
Focused Revision
Review Convergence
Human Gate Batching
```

RC1 is a correctness tightening release.

---

# 8. Deterministic Validation Requirements

Deterministic tests carry the primary proof burden.

## B401 Tests

At minimum:

```text
late BLOCKING + missing origin
→ protocol repair / FAILED
→ never NON_BLOCKING
→ never APPROVED

PREVIOUS_REVIEW_MISS + missing why_not_detected_initially
→ invalid packet

valid NEW_EVIDENCE blocker
→ stays BLOCKING

valid REGRESSION deterministic origin
→ stays BLOCKING
```

Remove/update the existing tests that intentionally assert downgrade-to-NON_BLOCKING behavior.

## B402 Tests

At minimum:

```text
candidate IDs unique
unknown dependency rejected
self dependency rejected
cycle rejected
independent candidates batch
C2 depends on C1 → C2 deferred
C1 becomes ACTIVE → C2 becomes eligible
internal decision_key identity still stable
V0.2 alias/cardinality regressions green
```

Tests must exercise the public Agent packet shape, not call internal hash helpers to manufacture `depends_on` values.

## B403 Tests

At minimum:

```text
new contract has non-empty acceptance baseline
initial coverage exact-ID equality
missing ID rejected
unknown ID rejected
duplicate ID rejected
FAIL must link BLOCKING issue
final coverage exact-ID equality
Human decision task_revision rebuild preserves acceptance authority semantics
no empty-coverage false APPROVED path
```

## N401 Tests

At minimum:

```text
reported changed_sections valid but actual proposal modifies disallowed field
→ rejected

actual delta only inside allowed scope
→ accepted

Closure Review receives deterministic delta context
```

## Regression

Run the complete deterministic suite.

All V0/V0.1/V0.2 safety invariants must remain green, especially:

```text
Human Requirement Authority
custom decisions
latest-effective-answer semantics
alias-space safety
2–4 option rule
Human Authority Check
covered_by_active_decision
Problem Mode FACT resume semantics
fail-closed convergence packet validation
Terminal Result classifications
no automatic ABLATION
```

---

# 9. Historical Case Replay Requirements

Keep both V0.3 structural replay fixtures green:

```text
84fb abstraction:
composite task
→ DECOMPOSITION_REQUIRED before DESIGN

c454 abstraction:
bounded task
→ focused correction
→ no automatic ABLATION
→ engineering non-convergence = DESIGN_NOT_APPROVED
```

Do not add domain-specific Shopify/StarRocks/retry logic to satisfy the replays.

Add only the minimum replay coverage needed to prove that B401/B403 cannot create false APPROVED outcomes.

---

# 10. Real-Agent Validation Requirements

Do not repeat RC2-style brute-force validation.

Validation budget:

```text
fresh real-agent E2E sessions <= 2
forcing request variants <= 1
wall-clock <= 45 min
```

## Mandatory Protocol Validation — B402

Run one small real Pi session/fixture whose Discovery naturally emits at least:

```text
C1 independent Human decision
C2 whose valid options depend on C1
```

Verify from persisted artifacts/events:

```text
Pi emitted candidate_id references through the public schema
C1 asked first
C2 not asked prematurely
C2 asked after C1 becomes ACTIVE
no manually injected internal decision_key/hash
```

This validation is specifically for Agent-protocol viability, not for business quality.

## Optional Second Real-Agent Session

Only run a second real-agent session if required to validate a code path not credibly covered by deterministic tests.

Do not manufacture increasingly complex tasks merely to hit a state.

---

# 11. Natural Real-Business Validation

The synthetic/scratch real-agent E2Es are useful runtime evidence but do not replace natural production-style usage.

After RC1 is implemented, the next suitable real bounded engineering task should be used as the natural validation sample.

For that sample record:

```text
Scope Guard verdict
time to first proposal
total elapsed time
Human interruption count
full/focused/ablation counts
Initial acceptance coverage completeness
late blocker count + provenance
terminal result status
session-result usability
```

Do NOT delay RC1 implementation waiting for such a task, and do NOT invent a fake business task solely to claim this evidence.

One natural real-business sample is enough before deciding whether another RC is needed.

---

# 12. RC1 Definition of Done

RC1 is complete only when:

1. late BLOCKING provenance defects fail closed rather than lowering severity;
2. HumanCandidate dependency references are a usable public Agent protocol;
3. the Change Contract owns a stable, non-empty acceptance baseline for new sessions;
4. Initial and Final review mechanically cover the exact Contract acceptance IDs;
5. Focused Revision containment checks actual proposal changes, not only Agent self-report;
6. complete deterministic suite is green;
7. both historical structural case replays remain green;
8. one real Pi dependency-protocol validation succeeds within budget;
9. implementation audit records what was changed, test counts, validation budget usage, known limitations and any remaining non-blockers;
10. no deferred V0.4-style capability is implemented as part of RC1.

---

# 13. Expected Review Outcome After RC1

Independent review should focus only on whether B401/B402/B403 are closed and whether N401 is materially tightened.

Do not reopen V0.3 architecture unless the fixes uncover a new correctness contradiction.

Expected successful conclusion:

```text
V0.3-RC1 focused independent review PASS
```

followed by natural validation on the next real bounded engineering task.
