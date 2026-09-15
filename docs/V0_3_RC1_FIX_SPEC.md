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

This RC1 is a focused correctness repair after independent review of V0.3 and a re-check against the current engineering principles already established for this project.

It MUST NOT expand into a new workflow redesign.

---

# 2. RC1 Scope

RC1 fixes exactly these correctness gaps:

```text
B401  Late blocking issue provenance must fail closed
B402  Human Gate dependency protocol must be usable by real Agents
B403  Current effective Acceptance Baseline must be Contract-owned and authority-traceable
B404  Focused Revision containment must validate the actual proposal delta
B405  Existing Requirement Authority must be reused before asking Human again
```

All five are release blockers for V0.3-RC1.

The successful V0.3 architecture remains intact:

```text
Scope Guard
Terminal Result Contract
Generic Correction Action
Focused Revision
Review Convergence Contract
Human Gate Batching
```

RC1 tightens trust boundaries and authority propagation; it does not add a new product layer.

Explicitly deferred:

```text
N402  stronger mechanical Material Progress evidence
N403  making correction_action mandatory / removing default FULL_REVISION
full Living Requirement Baseline system
Human free-form clarification / annotations
advanced interruption accounting
multi-session orchestration
new budgets / extra correction rounds
```

---

# 3. Governing Principles

The following principles constrain every RC1 implementation choice.

## 3.1 Agent output is untrusted input

Agent output may recommend or describe state, but it becomes workflow truth only after:

```text
Schema Validation
→ Domain Validation
→ Orchestrator-controlled state transition
```

A missing Agent metadata field must never silently weaken an engineering risk.

## 3.2 Human Authority is a boundary, not a fallback

Human should only be interrupted for genuinely new Requirement / Fact / Trade-off authority.

If the current effective Requirement Baseline or an ACTIVE Human Decision already settles the semantics, the issue is an engineering gap and must return to correction without asking Human again.

## 3.3 Acceptance completeness is relative to the current effective baseline

RC1 does NOT claim that any static contract can prove the complete truth of the business forever.

The mechanical invariant is narrower and stronger:

> Every Reviewer must completely account for the current authoritative Acceptance Baseline for the current task revision.

When new evidence legitimately changes Requirement understanding, the existing task-revision / baseline-rebuild mechanism applies. Reviewers may not silently mutate that baseline.

## 3.4 Reuse valid facts and evidence

Closure / Final review should reuse still-valid Contract, decisions, previous findings and evidence. RC1 should not add another full review pass merely to obtain correctness.

## 3.5 Risk and task compositeness are different axes

A small coherent change may be high risk and still be BOUNDED.

Scope Guard should classify by independent decision / acceptance / deliverable boundaries, not simply by risk severity.

---

# 4. B401 — Late Blocker Provenance Must Fail Closed

## Problem

Current V0.3 behavior allows a new BLOCKING issue discovered in CLOSURE_REVIEW or FINAL_REVIEW to be mechanically downgraded to NON_BLOCKING when required provenance metadata is missing.

Examples:

```text
origin missing
PREVIOUS_REVIEW_MISS without why_not_detected_initially
```

This converts a Reviewer protocol defect into a lower engineering severity and may allow a false PASS.

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
- Missing `why_not_detected_initially` for PREVIOUS_REVIEW_MISS cannot lower severity.
- Valid late BLOCKING issues remain BLOCKING.
- NON_BLOCKING late issues do not require blocker provenance.
- Existing deterministic REGRESSION-origin compatibility remains tested.

---

# 5. B402 — Human Gate Dependency Protocol Must Be Agent-Usable

## Problem

V0.3 introduced:

```text
HumanCandidate.depends_on
```

but it currently expects references to orchestrator-generated `decision_key` values derived from an internal hash of category + question.

Unit tests can compute those keys directly, but a real Pi Agent has no stable public mechanism to know another candidate's generated decision key while producing one Discovery packet.

Therefore the dependency mechanism exists in code but is not a reliable Agent protocol.

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
- `depends_on` references candidate IDs, never internal decision hashes.
- Unknown dependency IDs are invalid and must not be silently treated as independent.
- Self-dependency is invalid.
- Cycles are invalid; detect them deterministically and fail closed with an auditable reason.
- After packet validation, the Orchestrator may map `candidate_id` to the existing internal stable `decision_key`.
- Persisted Human Decisions continue using existing decision-key identity / supersession semantics.
- Every Agent prompt/schema capable of producing `HumanCandidate` must expose the protocol clearly.

## Acceptance Criteria

- A real Agent can express `C2 depends on C1` without knowing an internal hash function.
- Independent candidates batch into one Gate.
- A dependent candidate is deferred until its dependency is ACTIVE.
- Satisfied dependencies become eligible normally on reevaluation.
- Unknown/self/cyclic dependencies never silently become independent questions.
- V0.2 Human Answer Alias Space and 2–4 option invariants remain unchanged.

---

# 6. B403 — Current Effective Acceptance Baseline Must Be Contract-Owned

## Problem

Current V0.3 acceptance coverage only guarantees that criteria enumerated by INITIAL_REVIEW cannot silently disappear later.

It does not guarantee that INITIAL_REVIEW accounted for the current authoritative Requirement basis, and the current model permits an empty initial coverage set that can still lead to APPROVED.

At the same time, RC1 must not overclaim that a frozen list can represent all future business truth. Requirement understanding may legitimately change when new evidence appears.

## Required Semantics

The Change Contract owns the **current effective Acceptance Baseline for one task revision**.

Conceptually:

```yaml
acceptance_criteria:
  - id: A001
    criterion: ...
    authority_refs:
      - REQUEST

  - id: A002
    criterion: ...
    authority_refs:
      - D003
```

Exact field names may follow repository conventions, but these semantics are mandatory.

### 6.1 Stable IDs

- Acceptance IDs are stable within a task revision.
- INITIAL_REVIEW and FINAL_REVIEW report coverage by acceptance ID, not by free-form string identity.
- Missing, duplicate or unknown IDs fail closed.

### 6.2 Authority traceability

An Acceptance Criterion must not obtain Requirement Authority merely because an Agent wrote it into the Contract.

Each authoritative criterion must trace to valid Requirement authority, such as:

```text
original user request / explicit request fact
ACTIVE Human Decision
existing authoritative Contract element derived from those sources
```

The exact reference model may be chosen by implementation, but the Orchestrator must be able to validate that the reference exists.

Implementation assumptions and unresolved unknowns must remain assumptions / open questions; they must not silently enter the authoritative acceptance set.

### 6.3 Current baseline, not eternal truth

Mechanical completeness means:

```text
Contract Acceptance IDs
== Initial Review Coverage IDs
== Final Review Coverage IDs
```

for the current task revision.

It does NOT mean the baseline can never evolve.

When a new Human Decision or valid new evidence changes Requirement semantics:

```text
baseline changes
→ existing task_revision / contract rebuild semantics
→ new Acceptance Baseline for the new revision
```

A Reviewer may identify a possible Requirement gap, but may not silently append an authoritative acceptance criterion without going through the authority path.

## Backward Compatibility

Do not weaken the invariant merely to keep old fake/default adapters flowing.

Update fake/default fixtures so new RC1 sessions have a valid non-empty acceptance baseline.

For historical persisted sessions that predate the field, implement an explicit compatibility rule and document it. Compatibility MUST NOT create a false APPROVED path for newly created RC1 sessions.

## Acceptance Criteria

- A new RC1 session cannot APPROVE with an empty authoritative Acceptance Baseline.
- Every Contract acceptance criterion has a stable ID.
- Every authoritative criterion has mechanically valid authority provenance.
- Initial Review coverage IDs exactly match the current Contract Acceptance IDs.
- Final Review coverage IDs exactly match the same current baseline.
- Missing / unknown / duplicate IDs fail closed.
- FAIL coverage still links to a BLOCKING issue.
- Assumptions / unknowns cannot silently become authoritative acceptance.
- A legitimate task revision can replace the baseline without corrupting old audit history.

---

# 7. B404 — Focused Revision Must Validate the Actual Proposal Delta

## Problem

Current Focused Revision containment checks:

```text
Agent-reported changed_sections ⊆ allowed_change_scope
```

This validates what Pi says it changed, not what the serialized proposal actually changed.

Because Focused Revision's product guarantee is "correct only the bounded part", self-reported containment is not a sufficient workflow invariant.

## Required Behavior

Before replacing the current proposal, compute a deterministic structural delta between:

```text
old DesignResult
new DesignResult
```

At minimum compare all top-level fields that carry design semantics.

Produce an Orchestrator-owned set such as:

```text
actual_changed_sections
```

When an explicit `allowed_change_scope` exists:

```text
actual_changed_sections ⊆ allowed_change_scope
```

must hold, otherwise fail closed.

Agent-reported `changed_sections` may remain for explanation/audit but is not the source of truth for containment.

### Differential Review Evidence

Closure Review must receive reliable correction-delta context.

Prefer explicit persisted context such as:

```text
previous proposal reference / snapshot
current proposal
actual_changed_sections
focused target issues
preserved invariants
```

Do not ask Closure Reviewer to infer the delta from the corrected proposal alone.

## Acceptance Criteria

- An actual proposal change outside allowed scope is rejected even if Pi omitted it from `changed_sections`.
- Actual changes completely inside allowed scope are accepted.
- Agent self-report cannot bypass containment.
- Semantic/unbounded focused scope, if still supported, is explicitly distinguished from an empty explicit scope.
- Closure Review receives deterministic delta evidence and reuses prior issue/evidence context.

---

# 8. B405 — Existing Requirement Authority Must Be Reused

## Problem

V0.2/V0.3 Human Authority Check primarily searches ACTIVE Human Decisions.

A Requirement may already be explicitly established by the original request or by the current effective Change Contract / Acceptance Baseline without having a separate `decisions.json` entry.

If Reviewer later raises the same semantics as a REQUIREMENT issue, the workflow can incorrectly ask Human to decide something already decided.

That increases Human Attention Cost and violates the intended authority boundary.

## Required Semantics

Human Authority Check must evaluate the current effective Requirement Authority, not only ACTIVE decisions.

Conceptually support:

```text
COVERED_BY_EXISTING_AUTHORITY
NEEDS_NEW_HUMAN_DECISION
CANNOT_DETERMINE
```

or preserve the existing enum while expanding the meaning of the COVERED path.

Coverage may reference, for example:

```yaml
authority_refs:
  - D003
  - A005
  - REQUEST:<stable-ref>
```

Exact representation may follow repository architecture.

Mechanical rules:

- every authority reference must resolve to persisted current-authority data;
- stale/superseded decisions or acceptance criteria from an old task revision cannot provide current coverage;
- covered Requirement issues revert to an engineering gap and continue through correction;
- only genuinely undecided semantics may open a Human Gate;
- the Agent cannot forge authority references that the Orchestrator cannot resolve.

## Relationship to B403

B403 establishes the current effective Acceptance Baseline and its authority provenance.

B405 ensures downstream review issues actually reuse that baseline.

Together they enforce:

```text
Requirement already settled
→ do not ask Human again
→ fix Solution / Validation / Integration instead
```

## Acceptance Criteria

- A Reviewer REQUIREMENT issue already covered by current Acceptance Baseline does not open a Human Gate.
- Coverage by an ACTIVE Decision still works exactly as in V0.2.
- Coverage can combine multiple current authority refs when needed.
- Unknown/stale/invalid authority refs fail closed.
- A genuinely new Requirement ambiguity still opens the existing bounded Human Authority path.
- Covered issues retain auditable authority references in persisted issue/routing metadata.

---

# 9. Scope Guard Regression — Risk Is Not Compositeness

No Scope Guard redesign is required in RC1.

Add a regression protecting this distinction:

```text
small coherent outcome
+
high correctness / data / security / operability risk
→ BOUNDED
```

High risk may justify deeper relevant Review / evidence requirements, but it must not by itself produce:

```text
DECOMPOSITION_REQUIRED
```

The existing composite replay remains:

```text
multiple independent decision / acceptance / deliverable outcomes
→ DECOMPOSITION_REQUIRED
```

---

# 10. Non-Goals / Do Not Change

RC1 MUST NOT:

- add new correction actions;
- increase revision/focused/ablation budgets;
- reintroduce automatic ABLATION fallback;
- change `DESIGN_NOT_APPROVED` vs `NEEDS_HUMAN_DECISION` semantics;
- redesign Scope Guard;
- implement automatic decomposition execution;
- implement the full four-layer Living Requirement model;
- add mandatory new Material Progress subfields;
- make every review run another comprehensive pass;
- redesign Human interaction into a conversation protocol.

The objective is to make the existing V0.3 abstractions trustworthy, not heavier.

---

# 11. Deterministic Validation Requirements

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

Remove/update existing tests that intentionally assert downgrade-to-NON_BLOCKING behavior.

## B402 Tests

At minimum:

```text
candidate_id unique
unknown dependency rejected
self dependency rejected
cycle rejected
independent candidates batch
C2 depends on C1 → C2 deferred
C1 becomes ACTIVE → C2 becomes eligible
internal decision_key identity remains stable
V0.2 alias/cardinality regressions green
```

Tests must exercise the public Agent packet shape, not call internal hash helpers to manufacture dependency references.

## B403 Tests

At minimum:

```text
new Contract has a non-empty Acceptance Baseline
acceptance IDs unique and stable inside one task revision
authority refs resolve mechanically
assumption/open-question cannot masquerade as authoritative acceptance
Initial Review exact-ID coverage equality
missing ID rejected
unknown ID rejected
duplicate ID rejected
FAIL must link BLOCKING issue
Final Review exact-ID coverage equality
task_revision rebuild creates the new current baseline while preserving history
no empty-baseline false APPROVED path
```

## B404 Tests

At minimum:

```text
reported changed_sections valid
but actual proposal modifies disallowed field
→ rejected

actual delta only inside allowed scope
→ accepted

Agent omission from changed_sections cannot bypass containment
Closure Review receives deterministic old/new delta context
```

## B405 Tests

At minimum:

```text
Requirement issue covered by ACTIVE Decision
→ no Human Gate

Requirement issue covered by current Acceptance Baseline
→ no Human Gate
→ engineering correction

coverage combining valid authority refs
→ accepted

stale/unknown authority ref
→ fail closed

genuinely new Requirement ambiguity
→ existing Human Authority / Gate path
```

## Scope Guard Regression

```text
small + high-risk + one coherent outcome
→ BOUNDED

multiple independent outcomes
→ DECOMPOSITION_REQUIRED
```

## Full Regression

Run the complete deterministic suite.

All V0/V0.1/V0.2/V0.3 safety invariants must remain green, especially:

```text
Human Requirement Authority
custom decisions
latest-effective-answer semantics
alias-space safety
2–4 option rule
Human Authority Check
ACTIVE-decision coverage
Problem Mode FACT resume semantics
fail-closed convergence packet validation
Terminal Result classifications
no automatic ABLATION
Scope Guard early stop
Focused Revision budget separation
```

---

# 12. Historical Case Replay Requirements

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

Add focused replay coverage for the authority/baseline failures:

## Acceptance / Authority Replay

```text
original request establishes requirement X
→ current Contract Acceptance A001 traces to existing authority
→ Reviewer raises "X is not satisfied"
→ authority check resolves COVERED_BY_EXISTING_AUTHORITY
→ no Human interruption
→ issue routes as engineering correction
```

Also prove:

```text
late blocker with malformed provenance
→ cannot create false APPROVED

missing Contract acceptance coverage
→ cannot create false APPROVED
```

---

# 13. Real-Agent Validation Requirements

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

This validates Agent-protocol viability, not business quality.

## Optional Second Real-Agent Session

Only run a second real-agent session if a changed Agent protocol cannot be credibly validated through deterministic coverage.

Do not manufacture increasingly complex tasks merely to hit states.

---

# 14. Natural Real-Business Validation

Synthetic scratch repositories with real Pi/Codex are useful runtime evidence but do not replace natural production-style usage.

A natural real-business case is **not a merge blocker for RC1** because the relevant environment/task may not exist on demand.

After RC1 is implemented, use the next suitable real bounded engineering task as the natural sample.

Record:

```text
Scope Guard verdict
time to first proposal
total elapsed time
Human interruption count
full/focused/ablation counts
Contract Acceptance Baseline size and authority sources
Initial acceptance coverage completeness
late blocker count + provenance
existing-authority coverage count
terminal result status
session-result usability
```

Do NOT invent a fake business task solely to claim this evidence.

One natural real-business sample is enough before deciding whether another RC is needed.

---

# 15. Validation Cost / Evidence Reuse Rules

RC1 validation itself must follow the workflow principles it is enforcing.

- Reuse still-valid V0.3 deterministic and real-agent evidence.
- Re-run the complete deterministic suite because protocol/model contracts changed.
- Add targeted tests for changed semantics rather than recreating all historical E2Es.
- One mandatory real-agent B402 protocol run is sufficient unless it fails or exposes a new protocol gap.
- Do not rerun a full real-agent scenario merely because a deterministic-only branch was not naturally hit.
- Stop validation when the RC1 acceptance criteria are proven and no new material uncertainty has appeared.

---

# 16. RC1 Definition of Done

RC1 is complete only when:

1. late BLOCKING provenance defects fail closed rather than lowering severity;
2. HumanCandidate dependency references are a usable public Agent protocol;
3. the Change Contract owns a stable, non-empty **current effective** Acceptance Baseline for new sessions;
4. authoritative acceptance criteria carry mechanically valid Requirement authority provenance;
5. Initial and Final Review cover the exact Contract Acceptance IDs;
6. Focused Revision containment checks actual proposal changes, not Agent self-report;
7. downstream Human Authority Check reuses current Requirement Baseline as well as ACTIVE Human Decisions;
8. high-risk but coherent bounded work is not misclassified as composite merely because of risk;
9. complete deterministic suite is green;
10. both historical structural case replays remain green;
11. Acceptance/Authority replay proves already-decided requirements do not re-interrupt Human;
12. one real Pi dependency-protocol validation succeeds within budget;
13. implementation audit records changes, test counts, validation budget usage, known limitations and remaining non-blockers;
14. no deferred V0.4-style capability is implemented as part of RC1.

---

# 17. Expected Review Outcome After RC1

Independent review should focus only on whether B401–B405 are closed and whether the RC1 changes preserve the successful V0.3 architecture.

Do not reopen V0.3 architecture unless these fixes uncover a new correctness contradiction.

Expected successful conclusion:

```text
V0.3-RC1 focused independent review PASS
```

Then return to natural validation on the next real bounded engineering task rather than manufacturing another RC solely for process experimentation.
