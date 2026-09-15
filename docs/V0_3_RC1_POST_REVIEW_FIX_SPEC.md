# Agent Review Orchestrator V0.3-RC1 — Post-Review Focused Fix Spec

## 1. Status

Status: READY FOR IMPLEMENTATION

Target baseline:

```text
V0.3-RC1
commit: 4b01c751c5eb378894055e66eb1966e65a2054d8
```

Primary references:

```text
docs/V0_3_CONVERGENCE_QUALITY_DESIGN.md
docs/V0_3_RC1_FIX_SPEC.md
docs/V0_3_IMPLEMENTATION_AUDIT.md
```

This document is a focused post-review correction for V0.3-RC1.

It does NOT reopen V0.3 architecture and does NOT create a new workflow version.

---

# 2. Review Conclusion

The focused independent review of commit `4b01c751...` concludes:

```text
B401  PASS
B402  PASS with one minor protocol-consistency cleanup
B403  NEEDS SMALL FIX
B404  NEEDS SMALL FIX
B405  PASS
Validation strategy  PASS
```

Only the remaining issues below are in scope.

---

# 3. Scope

Required fixes:

```text
R403  Acceptance Baseline must use independently reviewable requirement granularity
R404  Actual proposal delta must treat list reordering as an actual change
```

Optional / non-blocking cleanup:

```text
N402  Fresh Agent packets should consistently provide candidate_id for every HumanCandidate
```

Explicitly out of scope:

```text
B401 / B405 redesign
Scope Guard redesign
Material Progress redesign
correction_action redesign
new correction actions
new workflow phases
new budgets / additional rounds
Human free-form conversation
annotation extraction
multi-session orchestration
full Living Requirement system
additional real-agent E2E validation
```

---

# 4. R403 — Acceptance Baseline Granularity

## Problem

RC1 correctly introduced:

```text
Contract-owned Acceptance Baseline
stable A### ids
authority_refs
Initial / Final exact-ID coverage
```

However the current request-backed baseline is synthesized as one coarse criterion:

```text
A001 = 原始请求的期望行为已交付：<entire raw request>
```

plus one criterion for each ACTIVE Human Decision.

For a request containing several independently verifiable behaviors or constraints, a single `A001` still permits the reviewer to mark the whole request PASS without separately accounting for each explicit requirement.

Example:

```text
- classify INTERNAL_SERVER_ERROR as transient
- reuse the existing retry channel
- mixed errors containing INTERNAL_SERVER_ERROR are transient
- failed sync must not advance the watermark
- historical failed stores are handled separately
```

These should not collapse into one indivisible acceptance item.

The goal is NOT to prove that the baseline is eternal business truth. The goal is:

> For the current task revision, every explicit independently reviewable Requirement already present in the current request / Human decisions is represented as a separately checkable acceptance item.

## Required Semantics

### 4.1 Request-backed requirements must be decomposed

Use the existing workflow calls; do NOT add another Agent round solely for acceptance extraction.

The preferred low-cost implementation is to let the existing DISCOVER result expose structured request-backed acceptance candidates (exact field names may follow repository conventions), conceptually:

```yaml
request_requirements:
  - criterion: "..."
    request_evidence: "exact fragment from the original request"
```

Rules:

- one independently PASS/FAIL-able explicit requested behavior / constraint per item;
- do not mechanically split by punctuation if clauses are semantically inseparable;
- do not invent new Requirement semantics;
- assumptions, implementation guesses and repository facts do not become request-backed acceptance;
- every request-backed item must carry evidence traceable to the original request;
- Orchestrator validates the evidence reference against the request text using a deterministic normalization / containment rule;
- request-backed acceptance criteria use `authority_refs=["REQUEST"]`;
- an atomic simple request may legitimately yield one request-backed acceptance criterion.

This is extraction of existing authority, not creation of new authority.

### 4.2 Intake builds the current baseline from request requirements + ACTIVE decisions

For the current task revision:

```text
request-backed explicit requirements
+
ACTIVE Human Decisions
→ Contract.acceptance_criteria
```

IDs remain stable for that task revision:

```text
A001, A002, ...
```

A Human Decision / Requirement change continues to use the existing `task_revision` rebuild mechanism.

### 4.3 Human Decision acceptance must preserve Human-visible meaning

Current implementation can prefer `selected_option_key` over the Human-visible answer.

That is insufficient because option keys may be opaque:

```text
key = a
label = Strong consistency
```

The authoritative acceptance text must preserve the semantic Human answer.

Required representation should be equivalent to:

```text
Human Decision D001: <question> -> Strong consistency [a]
```

Use Human-visible `answer_text` / option label as the semantic value; keep the option key only as audit metadata if useful.

### 4.4 Existing exact-ID coverage remains

Do NOT weaken RC1 exact-ID validation.

Initial and Final Review must still satisfy:

```text
Contract Acceptance IDs
== Review Coverage IDs
```

with no missing / duplicate / unknown ids.

### 4.5 Do not build a full Living Requirement system

This fix MUST NOT add:

```text
Goal / Invariant / Policy / Assumption state machines
new Requirement lifecycle statuses
new Human Gates
new task phases
new Agent calls
```

The current baseline is allowed to evolve later through existing Human Decision / task revision semantics.

## Acceptance Criteria

- A request with several explicit independently reviewable requirements produces several request-backed acceptance criteria.
- A simple atomic request may still produce one criterion.
- Every request-backed acceptance item has deterministic traceability to the raw request.
- A request-backed acceptance item cannot silently originate from an implementation assumption or repository fact.
- Human Decision acceptance text preserves Human-visible semantics, not only an opaque option key.
- Missing one of the resulting acceptance IDs in Initial / Final Review still fails closed.
- No extra Agent call or workflow phase is introduced.

---

# 5. R404 — Actual Delta Must Be Order-Sensitive

## Problem

RC1 correctly moved Focused Revision containment from Agent self-report to Orchestrator-owned structural diff.

However list fields are currently normalized with sorting before comparison.

Therefore:

```text
old:
1. READY -> RUNNING
2. RUNNING -> DONE

new:
1. RUNNING -> DONE
2. READY -> RUNNING
```

can be treated as unchanged.

For proposal fields such as:

```text
changes
state_lifecycle_changes
failure_handling
verification_plan
compatibility
change_map.*
```

order may carry semantic or explanatory meaning. More importantly, B404's invariant is about the ACTUAL serialized proposal delta; the Orchestrator should not silently reinterpret list fields as sets.

## Required Behavior

Structural diff must be conservative and order-sensitive.

For list fields:

```text
normalize item text
preserve sequence order
compare sequence to sequence
```

Do NOT sort before comparison.

Any reorder counts as an actual changed section.

This may conservatively report a section as changed even when a reorder is semantically harmless. That is acceptable for Focused Revision containment: a narrow correction should avoid unrelated serialization churn.

## Acceptance Criteria

- Reordering a DesignResult list field is detected as an actual change.
- Reordering a `change_map.*` list field is detected as an actual change.
- Whitespace-only normalization may remain non-semantic if already intentional.
- Adding/removing/changing list elements continues to be detected.
- Existing explicit-scope containment still uses Orchestrator-owned actual delta.
- Existing correction-delta evidence supplied to Closure Review remains unchanged in shape unless a minimal schema change is necessary.

---

# 6. N402 — candidate_id Protocol Consistency Cleanup

## Observation

The Agent-facing prompt says every HumanCandidate should carry a packet-local `candidate_id`, while the model currently allows an independent candidate with `depends_on=[]` to omit it for backward compatibility.

The core dependency protocol is already working and has been validated with a real Pi session.

This is NOT a release blocker.

## Preferred Cleanup

For newly produced RC1+ Agent packets:

```text
candidate_id is non-empty and unique for every HumanCandidate
```

while historical persisted sessions should not be broken merely to enforce this cosmetic consistency.

Implementation guidance:

- if this can be enforced at the fresh Agent-output boundary without introducing a protocol-version/migration subsystem, do so;
- otherwise keep the tolerant legacy model, document the compatibility exception, and do not add machinery merely to make the type non-optional.

Do NOT run another real-agent E2E for this cleanup; B402's public protocol viability has already been proven.

---

# 7. Validation Requirements

The validation objective is to prove the two remaining correctness fixes with minimum cost.

## 7.1 Targeted deterministic tests first

### R403

At minimum:

```text
multi-requirement request
→ multiple request-backed Acceptance Criteria

atomic request
→ one request-backed Acceptance Criterion is allowed

request-backed criterion evidence not traceable to request
→ invalid / fail closed

Human Decision option key = "a", label = "Strong consistency"
→ Acceptance Criterion preserves "Strong consistency"

Initial Review omits one granular A###
→ fail closed
```

### R404

At minimum:

```text
list reorder inside allowed section
→ section appears in actual_changed_sections

list reorder outside allowed focused scope
→ focused revision rejected

change_map list reorder
→ actual change detected

identical ordered lists
→ unchanged
```

### N402

Only add a small deterministic test if code is changed.

## 7.2 Regression

Run the full deterministic suite normally **once only**, after targeted tests are green.

If that run exposes a real regression:

```text
fix only the failure
→ rerun related targeted tests
→ at most one additional full suite if genuinely necessary
```

Do not rerun a green full suite for reassurance.

## 7.3 No new real-agent E2E

Do NOT run another real Pi / Codex E2E for this post-review fix.

Already reusable evidence:

```text
B402 real Pi dependency protocol: proven in RC1
Scope Guard real/synthetic evidence: still valid
Terminal Result behavior: unchanged
B401/B405 deterministic evidence: unchanged
```

Only run a real-agent session if the implementation unexpectedly changes an Agent protocol in a way deterministic tests cannot validate. That should be treated as an exception requiring justification in the audit.

---

# 8. Historical Replay Requirements

Do not rerun or expand historical case replays unless these changes directly invalidate their fixtures.

The existing facts remain authoritative:

```text
84fb abstraction
→ DECOMPOSITION_REQUIRED before DESIGN

c454 abstraction
→ bounded
→ focused correction
→ no automatic ABLATION
→ engineering non-convergence = DESIGN_NOT_APPROVED
```

If fixture schema updates are required by R403, update only the acceptance-baseline representation; do not add new domain behavior.

---

# 9. Implementation Audit

Append a short post-review-fix section to:

```text
docs/V0_3_IMPLEMENTATION_AUDIT.md
```

Record only:

- R403 implementation approach;
- R404 order-sensitive delta fix;
- whether N402 was tightened or deliberately left as a compatibility exception;
- targeted test result;
- full regression result + number of full-suite runs;
- confirmation that no new real-agent E2E was run (or justification if one was unavoidable);
- known limitations;
- final commit SHA.

Do not rewrite the V0.3 / RC1 audit history.

---

# 10. Definition of Done

This focused fix is complete only when:

1. request-backed Acceptance Baseline uses independently reviewable granularity rather than always one whole-request criterion;
2. request-backed acceptance remains traceable to original REQUEST authority;
3. Human Decision acceptance preserves Human-visible semantic meaning;
4. existing exact-ID Initial / Final coverage remains fail-closed;
5. list reordering is visible to Orchestrator-owned actual-delta detection;
6. out-of-scope list reorder cannot bypass Focused Revision containment;
7. targeted deterministic tests are green;
8. complete deterministic regression is green;
9. validation does not repeat unnecessary real-agent E2E;
10. no V0.4-style capability or new workflow phase is added.

Expected next independent-review result:

```text
V0.3-RC1 PASS
```

After PASS, stop modifying the workflow and use the next suitable real bounded engineering task as the natural validation sample.
