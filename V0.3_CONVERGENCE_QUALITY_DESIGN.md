# Agent Review Orchestrator V0.3 — Convergence Quality

## 1. Status

Status: DESIGN READY

Target baseline:

```text
V0.2-RC3
commit: c43e3ce117f949aafdd997046d13f065022e6def
```

Primary real-world evidence:

```text
docs/V0_2_CASE_AUDIT_20260914_RECONCILE_HANDOFF.md
docs/V0_2_CASE_AUDIT_20260914_PROD005_HANDOFF.md
```

V0.3 is a focused convergence-quality release.

It is not a general Multi-Agent redesign and does not attempt to automate multi-session execution.

---

# 2. Product Position

Agent Review Orchestrator is designed for:

```text
existing repository
+
bounded engineering change
+
mid-development requirement change
+
missing functionality
+
small / medium capability addition
+
bounded problem investigation
+
root-cause-based fix design
```

It is not designed to solve arbitrary engineering problems of unlimited scope.

The product must therefore do two things well:

1. determine whether a request is suitable for one bounded review session;
2. if suitable, converge toward the strongest trustworthy engineering conclusion available within bounded Agent cost and Human attention.

---

# 3. Core Principle

V0.3 adopts the following product principle:

> The goal is not to keep Agents running until PASS.

The goal is:

> Use bounded Agent work and bounded Human attention to produce the strongest trustworthy engineering conclusion available.

Therefore:

```text
PASS is a good result.

A precise DESIGN_NOT_APPROVED is also a valid result.

A clear DECOMPOSITION_REQUIRED is also a valid result.

An expensive ambiguous HANDOFF is not.
```

---

# 4. Evidence From Real Sessions

## 4.1 Composite Task Case

Session:

```text
20260914-094512-84fb
```

The task mixed multiple independently decidable and independently deliverable concerns:

```text
business reconciliation semantics
StarRocks data semantics
Shopify API strategy
time model
Java engine
XXL-Job
credentials
kill switch
CSV
notification
operationalization
```

The workflow entered normal design convergence before establishing whether this was still one bounded engineering task.

Result:

```text
HUMAN_HANDOFF
```

The case suggests:

> Some tasks belong to the product domain but should not enter a single review session.

---

## 4.2 Bounded Task Case

Session:

```text
20260914-165600-c454
```

The task was a relatively bounded production defect design.

The Human decisions were largely settled, but the session consumed approximately:

```text
46 minutes total
39 minutes real Agent execution
```

and ended in:

```text
HUMAN_HANDOFF
```

even though no new Human Requirement decision was actually needed.

This suggests:

> Even bounded tasks need better convergence routing and better terminal results.

---

# 5. V0.3 Goals

V0.3 has two top-level goals.

## Goal A — Reject Unsuitable Single-Session Tasks Early

After repository discovery, detect when a task is:

```text
BOUNDED
DECOMPOSITION_REQUIRED
OUT_OF_SCOPE
```

If the task should not continue as one session:

```text
stop early
explain why
provide decomposition guidance
```

Do not spend Design / Review budget on a structurally unsuitable task.

---

## Goal B — Produce a Useful Result for Every Terminal Session

For a suitable bounded task, every terminal session must answer:

```text
What is decided?
What is the current recommended solution?
What remains unresolved?
Can implementation start?
Why did the workflow stop?
What should happen next?
```

A session does not need to PASS to be useful.

---

# 6. Non-Goals

V0.3 MUST NOT implement:

```text
automatic code implementation
PR generation
deployment
automatic execution of decomposed child sessions
multi-session dependency orchestration
0→1 product discovery
large-system architecture design
large-scale refactoring workflow
general Human Gate free-form conversation
general annotation / fact extraction from Human prose
complex interruption-window accounting
unbounded retry / revision budgets
```

---

# 7. Capability Overview

V0.3 introduces six capabilities:

```text
C0 Scope Guard
C1 Terminal Result Contract
C2 Generic Correction Action
C3 Focused Revision
C4 Review Convergence Contract
C5 Human Gate Batching
```

---

# 8. C0 — Scope Guard

## 8.1 Purpose

The workflow must determine:

> Should this request continue as one bounded review session?

The check occurs after DISCOVER because repository facts are required for a meaningful judgment.

New high-level flow:

```text
REQUEST
↓
DISCOVER
↓
SCOPE GUARD
├─ BOUNDED
│    → existing workflow
│
├─ DECOMPOSITION_REQUIRED
│    → terminal result
│    → decomposition guidance
│
└─ OUT_OF_SCOPE
     → terminal result
     → unsupported reason
```

---

# 9. Scope Verdicts

## 9.1 BOUNDED

Use when the task can reasonably converge into one coherent engineering outcome.

Typical characteristics:

```text
one primary outcome
small number of tightly coupled decisions
one coherent change surface
shared acceptance criteria
one implementation-ready design can represent the result
```

---

## 9.2 DECOMPOSITION_REQUIRED

Use when the request belongs to the product domain but contains multiple independently converging engineering outcomes.

Examples:

```text
business semantics + engine design + deployment design

data contract + migration implementation + operational rollout

core feature behavior + unrelated admin UI + reporting pipeline
```

The product MUST NOT automatically execute the decomposed sessions in V0.3.

It only:

```text
stops
explains
proposes bounded child sessions
```

---

## 9.3 OUT_OF_SCOPE

Use when the request fundamentally does not fit the product.

Examples:

```text
0→1 full product exploration
whole-system architecture from scratch
large-scale rewrite
organization-wide platform strategy
open-ended research without bounded repository change
```

---

# 10. Scope Guard Input

The Scope Guard should consider at least:

```text
original request
repository discovery
identified change surfaces
candidate Human decisions
external unknowns
independently deliverable outcomes
```

Do NOT classify scope using only:

```text
file count
LOC
number of modules
estimated coding time
```

These may be weak signals but not decisive criteria.

---

# 11. Scope Assessment Model

The Agent should produce a structured assessment conceptually similar to:

```yaml
scope_assessment:
  verdict: BOUNDED | DECOMPOSITION_REQUIRED | OUT_OF_SCOPE

  primary_outcome:
    ...

  independent_outcomes:
    - ...

  decision_clusters:
    - ...

  change_surfaces:
    - ...

  external_unknowns:
    - ...

  rationale:
    ...

  decomposition:
    - title:
      goal:
      inputs:
      non_goals:
      dependencies:
```

Exact schema may follow repository conventions.

---

# 12. Scope Control Principle

The Agent may judge scope probabilistically.

The Orchestrator controls continuation deterministically.

```text
Agent:
"This appears DECOMPOSITION_REQUIRED."

Orchestrator:
"Do not enter DESIGN."
```

No Agent may silently override Scope Guard by continuing the workflow.

---

# 13. Decomposition Quality

For `DECOMPOSITION_REQUIRED`, the output should split by:

```text
independent decision boundary
independent acceptance boundary
independent implementation-ready outcome
```

Do not mechanically split by:

```text
folder
class
microservice
technology name
```

unless those align with genuine outcome boundaries.

---

# 14. C1 — Terminal Result Contract

Every terminal session MUST generate:

```text
session-result.md
```

This becomes the primary human-facing artifact.

`handoff.md` may remain for compatibility or specialized handoff data.

---

# 15. Result Classification

Minimum result statuses:

```text
APPROVED
DESIGN_NOT_APPROVED
NEEDS_HUMAN_DECISION
DECOMPOSITION_REQUIRED
OUT_OF_SCOPE
FAILED
```

---

# 16. APPROVED

Use when:

```text
review passes
no blocking issue remains
implementation readiness is satisfied
```

Default readiness:

```text
READY
```

---

# 17. DESIGN_NOT_APPROVED

Use when:

```text
Requirement authority is sufficiently settled

AND

no new Human Decision is necessary

AND

one or more blocking engineering issues remain

AND

the workflow stops because further Agent convergence is not justified
```

This is not a failure to produce a result.

It is an explicit engineering conclusion.

---

# 18. NEEDS_HUMAN_DECISION

Use only when:

```text
a new authoritative Human Requirement / Fact decision is genuinely required
```

Do not use this result merely because Agents failed to converge.

---

# 19. DECOMPOSITION_REQUIRED

Use when Scope Guard determines:

> The task is in-domain but unsuitable as one bounded session.

The result MUST include proposed child sessions.

---

# 20. OUT_OF_SCOPE

Use when the task fundamentally falls outside supported product scope.

---

# 21. FAILED

Use for:

```text
unrecoverable runtime failure
corrupted session
protocol failure that prevents a trustworthy result
infrastructure failure
```

Do not use FAILED for ordinary design non-convergence.

---

# 22. session-result.md Structure

Every terminal result should contain, where applicable:

```markdown
# Session Result

## Status

## Summary

## Scope Assessment

## Current Recommended Design

## Frozen Human Decisions

## Resolved Issues

## Remaining Blocking Issues

## Remaining Non-Blocking Issues

## Implementation Readiness

## Decomposition Proposal

## Recommended Next Action
```

Irrelevant sections may be omitted.

---

# 23. Result Rendering Requirements

Result generation should be deterministic from persisted artifacts wherever possible.

Preferred inputs:

```text
task
scope assessment
ACTIVE decisions
latest proposal
issues
review results
state
terminal reason
```

Do not require a large additional Agent call just to generate the final result.

A deterministic fallback renderer is mandatory.

---

# 24. C2 — Generic Correction Action

V0.3 must not create workflow branches for every possible engineering problem type.

The workflow should separate:

```text
WHAT is wrong
```

from:

```text
HOW the workflow should respond
```

---

# 25. Correction Action

Add a generic correction action concept.

Minimum actions:

```text
FULL_REVISION
FOCUSED_REVISION
ABLATION
HUMAN_DECISION
STOP
```

The exact enum naming may follow repository conventions.

---

# 26. FULL_REVISION

Use when the proposal requires broad redesign.

Typical examples:

```text
wrong architecture
wrong behavioral model
incorrect integration strategy
fundamental regression
large inconsistency across proposal sections
```

Routing:

```text
→ REVISION
```

---

# 27. FOCUSED_REVISION

Use when the overall design remains valid but a bounded part requires correction.

Examples:

```text
validation evidence
specific retry behavior
transaction boundary
SQL/index strategy
API compatibility detail
deployment rollback detail
operability control
```

Routing:

```text
→ FOCUSED_REVISION
```

This is a generic mechanism.

It is not validation-specific.

---

# 28. ABLATION

Use only when the corrective action is genuinely:

```text
remove
simplify
reduce change surface
eliminate unnecessary design elements
```

ABLATION MUST NOT be the default fallback after failed revision.

---

# 29. HUMAN_DECISION

Use when a new Requirement / Fact authority is needed.

Routing:

```text
→ existing Human Authority Check
```

Existing ACTIVE decisions may still convert the issue back into an engineering correction.

---

# 30. STOP

Use when continuing Agent correction is not justified.

Examples:

```text
required external evidence unavailable
applicable correction already failed without meaningful progress
remaining issue cannot safely converge within current session
```

Typical terminal classification:

```text
DESIGN_NOT_APPROVED
```

unless Human authority is genuinely required.

---

# 31. Focus Area

Optionally record a second dimension:

```text
focus_area
```

Examples:

```text
BEHAVIOR
DATA
INTEGRATION
VALIDATION
OPERABILITY
PERFORMANCE
SECURITY
COMPATIBILITY
OTHER
```

This is descriptive context.

It MUST NOT create additional workflow states.

Example:

```yaml
correction_action: FOCUSED_REVISION
focus_area: VALIDATION
```

or:

```yaml
correction_action: FOCUSED_REVISION
focus_area: DATA
```

Both use the same workflow path.

---

# 32. Correction Routing Principle

Agents recommend correction action.

The deterministic Orchestrator controls execution.

Conceptually:

```text
BLOCKING ISSUE
      │
      ├─ FULL_REVISION
      │    → full revision budget
      │
      ├─ FOCUSED_REVISION
      │    → focused revision budget
      │
      ├─ ABLATION
      │    → ablation budget
      │
      ├─ HUMAN_DECISION
      │    → authority check
      │
      └─ STOP
           → terminal result
```

Unknown or malformed actions must fail closed.

---

# 33. C3 — Focused Revision

## 33.1 Purpose

Focused Revision corrects a narrow part of an otherwise valid design.

It avoids:

```text
rediscovery
full proposal regeneration
unnecessary reinterpretation of Requirements
unrelated redesign
```

---

# 34. Focused Revision Input

Minimum inputs:

```text
latest proposal
target issue ids
latest reviewer notes
close conditions
ACTIVE Human Decisions
allowed change scope
preserved invariants
relevant acceptance criteria
```

---

# 35. Focused Revision Contract

The Author must:

```text
preserve ACTIVE Human Decisions

preserve explicitly listed invariants

modify only the allowed scope

respond issue by issue

explain how each close condition is satisfied
```

The Author must not:

```text
restart DISCOVER
reinterpret frozen Requirement
redesign unrelated sections
expand task scope
```

---

# 36. Focused Revision Output

Conceptually:

```yaml
target_issue_ids:
allowed_change_scope:
preserved_invariants:
changed_sections:
issue_responses:
acceptance_changes:
proposal_delta:
```

A full-proposal rewrite is not required unless existing architecture makes delta persistence impractical.

---

# 37. Budget

Initial V0.3 recommendation:

```yaml
full_revision: 1
focused_revision: 1
ablation: 1
```

Do not increase budgets merely because V0.2 exhausted them.

Different mechanisms are not sequential lives in one generic ladder.

They are semantically different corrective actions.

---

# 38. C4 — Review Convergence Contract

V0.3 differentiates Review phases without suppressing legitimate new findings.

Review phases:

```text
INITIAL_REVIEW
CLOSURE_REVIEW
FINAL_REVIEW
```

must have different primary responsibilities.

---

# 39. INITIAL_REVIEW — Comprehensive Review

INITIAL_REVIEW is the deepest broad review.

It should cover:

```text
original request
task contract
ACTIVE Human Decisions
repository facts
proposal
acceptance criteria
change surface
regression risk
operability
validation evidence
implementation feasibility
```

The objective is:

> Discover as many material blockers as reasonably possible before correction begins.

---

# 40. Acceptance Coverage

Every acceptance criterion should be explicitly accounted for.

Conceptually:

```yaml
acceptance_coverage:
  A01:
    status: PASS
  A02:
    status: FAIL
    issue_id: R001
  A03:
    status: PASS
```

The exact schema may vary.

The invariant is:

> Acceptance criteria may not silently disappear from review.

---

# 41. Evidence Quality

Review must assess not only whether validation exists, but whether evidence is capable of distinguishing correct from incorrect behavior.

General question:

> Would the proposed evidence meaningfully distinguish a Requirement-satisfying implementation from an implementation that violates the Requirement?

Examples:

```text
retry behavior
→ test must prove retry actually occurred

performance requirement
→ functional success alone is insufficient

idempotency
→ one successful request is insufficient

migration safety
→ success-path verification alone may be insufficient

rollback behavior
→ deployment success alone may be insufficient
```

This concept is:

```text
Evidence Discrimination
```

It is intentionally generic.

---

# 42. CLOSURE_REVIEW — Differential Review

Primary responsibility:

```text
verify prior blockers
evaluate the correction delta
```

Secondary responsibility:

```text
global safety check
```

CLOSURE_REVIEW should not behave as another unrestricted INITIAL_REVIEW.

However it MUST still report a serious newly discovered problem.

---

# 43. Closure New Issue Provenance

Any newly created issue in CLOSURE_REVIEW should record why it appeared now.

Suggested values:

```text
INTRODUCED_BY_CORRECTION
PREVIOUS_REVIEW_MISS
NEW_EVIDENCE
DIRECTLY_REQUIRED_FOR_CLOSURE
```

---

# 44. FINAL_REVIEW — Readiness Review

Primary responsibility:

```text
implementation readiness
global invariant consistency
acceptance completeness
Human Decision preservation
blocking issue closure
```

It is not another unrestricted design review.

However:

> A serious blocker must never be suppressed merely because it was discovered late.

---

# 45. Final New Issue Provenance

New FINAL_REVIEW blockers must record origin:

```text
INTRODUCED_BY_CORRECTION
PREVIOUS_REVIEW_MISS
NEW_EVIDENCE
```

This becomes an important Reviewer quality signal.

---

# 46. Material Progress

V0.3 must not use a simplistic rule such as:

```text
same issue id exists for two rounds
→ stop
```

The correct question is:

> Is the blocker materially converging?

---

# 47. Material Progress Indicators

A blocker may be considered materially progressed when one or more of the following occur:

```text
close condition becomes materially narrower

substantial part of blocker is proven closed

new evidence eliminates an uncertainty

scope of required correction shrinks

remaining failure becomes more specific and actionable
```

---

# 48. No-Material-Progress Stop

Consider stopping when:

```text
same blocker persists

AND

applicable corrective action was attempted

AND

close condition did not materially narrow

AND

no meaningful new evidence appeared

AND

the next proposed action would repeat substantially the same work
```

Then:

```text
correction_action = STOP
```

and typically:

```text
DESIGN_NOT_APPROVED
```

---

# 49. Progress Must Not Be Fabricated

Agents may propose progress assessment.

The Orchestrator should rely on structured evidence where possible:

```text
previous close condition
current close condition
previous issue note
current issue note
changed proposal sections
new evidence references
```

Do not accept:

```text
"looks better"
"mostly fixed"
"should now work"
```

as sufficient material progress.

---

# 50. C5 — Human Gate Batching

Two real sessions independently produced immediate chained gates:

```text
HG001 completes
→ HG002 opens immediately
```

for independently decidable questions.

This is unnecessary Human fragmentation.

---

# 51. Batching Rule

A candidate may be deferred only when:

> Its final question or valid options materially depend on answers from the current Human Gate.

Independent candidates should be included in the same Gate subject to existing safety constraints.

---

# 52. Human Gate Constraints Preserved

V0.3 does not change:

```text
option alias safety
2–4 option rule
custom decision semantics
latest-effective-answer semantics
Human interruption budget model
```

Complex interruption-window accounting remains deferred.

---

# 53. Existing Human Authority Semantics

All V0.2 authority invariants remain.

Especially:

```text
Human provides Requirement Authority.

Repository provides Current State Facts.

Agent may modify Solution.

Agent may not silently modify Requirement.
```

Existing:

```text
covered_by_active_decision
```

behavior remains valid.

---

# 54. Scope Guard and Human Authority

Scope Guard must not invent Requirement decisions.

Its task is only:

```text
Can this task converge as one session?
```

If classification depends on an actual Requirement ambiguity:

```text
do not guess
```

The workflow may either:

```text
ask the minimum necessary Human question
```

or:

```text
classify conservatively and explain the uncertainty
```

depending on existing budget and implementation constraints.

---

# 55. State Machine Strategy

Prefer minimal state-machine expansion.

Potential new execution state:

```text
FOCUSED_REVISION
```

Potential pre-design state:

```text
SCOPE_GUARD
```

If either can safely be represented as a typed subtype while preserving audit clarity, that is acceptable.

Persisted events must make these distinguishable.

---

# 56. Product-Facing Result vs Internal State

Internal workflow state and user-facing result classification are separate concepts.

Example:

```text
internal:
HUMAN_HANDOFF

reason:
convergence stopped
no new Human decision needed

user-facing result:
DESIGN_NOT_APPROVED
```

Another:

```text
internal:
HUMAN_HANDOFF

reason:
new Requirement decision required

user-facing result:
NEEDS_HUMAN_DECISION
```

This distinction is mandatory.

---

# 57. Scope Result Examples

## Example A

```text
Task:
fix one retry classification defect
```

Likely:

```text
BOUNDED
```

---

## Example B

```text
design business reconciliation semantics
+
build Java engine
+
design scheduling/deployment/notifications
```

Likely:

```text
DECOMPOSITION_REQUIRED
```

Possible decomposition:

```text
Session A — Reconciliation Contract
Session B — Reconciliation Engine
Session C — Operationalization
```

---

## Example C

```text
design an entire ERP product from scratch
```

Likely:

```text
OUT_OF_SCOPE
```

---

# 58. Generic Correction Examples

## Example 1 — Validation

```yaml
correction_action: FOCUSED_REVISION
focus_area: VALIDATION
```

---

## Example 2 — Database design detail

```yaml
correction_action: FOCUSED_REVISION
focus_area: DATA
```

---

## Example 3 — Fundamental architecture problem

```yaml
correction_action: FULL_REVISION
focus_area: INTEGRATION
```

---

## Example 4 — Over-design

```yaml
correction_action: ABLATION
focus_area: OTHER
```

---

## Example 5 — Requirement ambiguity

```yaml
correction_action: HUMAN_DECISION
focus_area: BEHAVIOR
```

---

# 59. Telemetry

Persist or make derivable:

```text
scope_verdict
scope_guard_duration
decomposition_count

initial_blocker_count
closure_new_blocker_count
final_new_blocker_count
previous_review_miss_count

full_revision_count
focused_revision_count
ablation_count

same_blocker_round_count
no_material_progress_stop_count

human_interruptions
terminal_result_status
session_result_generated

time_to_first_proposal
total_elapsed_time
```

No dashboard required in V0.3.

---

# 60. Deterministic Test Plan

Add tests covering at least:

```text
BOUNDED scope continuation

DECOMPOSITION_REQUIRED early termination

OUT_OF_SCOPE early termination

decomposition result rendering

APPROVED result

DESIGN_NOT_APPROVED result

NEEDS_HUMAN_DECISION result

FAILED fallback result

FULL_REVISION routing

FOCUSED_REVISION routing

explicit ABLATION routing

HUMAN_DECISION routing

STOP routing

Focused Revision preserves Human Decisions

Focused Revision does not rediscover

Focused Revision respects allowed change scope

Acceptance coverage completeness

Evidence discrimination review contract

Closure differential review

Closure new issue provenance

Final readiness review

Final new issue provenance

material progress continuation

no-material-progress stop

independent Human Gate batching

dependent Human Gate deferral

all V0.2 regression tests
```

---

# 61. Real Validation Budget

Retain bounded validation discipline:

```text
fresh real E2E sessions <= 2
forcing request variants <= 2
wall-clock <= 60 min
```

Do not brute-force low-probability states.

Use deterministic tests for routing coverage.

---

# 62. Real Validation Strategy

Prefer two natural samples only if available within budget:

```text
one clearly bounded task

optionally one naturally composite task
```

Goals:

### Bounded

Verify:

```text
Scope Guard allows continuation
usable result produced
convergence does not automatically walk unrelated correction mechanisms
```

### Composite

Verify:

```text
Scope Guard stops before DESIGN
decomposition guidance is useful
```

Do not manufacture complexity solely to hit the branch.

---

# 63. Success Criteria

Hard invariants:

```text
100% terminal sessions generate session-result.md

DECOMPOSITION_REQUIRED stops before expensive design convergence

Agent convergence failure is not mislabeled as Human decision need

ABLATION is never generic fallback

Focused Revision cannot silently change frozen Requirement

all V0.2 safety regressions remain green
```

Directional product goals:

```text
Human attention < 5 min

typical bounded task:
ideal < 25 min
acceptable < 35 min

Final new blocker target:
0

usable terminal result:
100%
```

---

# 64. Deferred Work

Explicitly deferred:

```text
automatic multi-session execution
parent-child session orchestration
automatic dependency propagation
Human free-form clarification conversation
Human annotation extraction
covered_by_original_request enhancement
complex interruption accounting
automatic implementation
PR / deployment automation
```

---

# 65. Definition of Done

V0.3 is complete only when:

1. `Scope Guard` exists after DISCOVER;
2. unsuitable single-session tasks stop before DESIGN;
3. `DECOMPOSITION_REQUIRED` provides actionable split guidance;
4. every terminal session creates `session-result.md`;
5. Agent convergence failure is distinct from Human decision need;
6. correction routing uses generic actions rather than case-specific workflow types;
7. Focused Revision exists;
8. ABLATION is explicit only;
9. Review phases have differentiated contracts while preserving global safety;
10. Evidence Quality is reviewed generically;
11. convergence considers Material Progress rather than issue-id repetition;
12. independent Human Gate candidates batch together;
13. all existing V0.2 safety and alias tests pass;
14. real validation stays within the mandatory validation budget.
