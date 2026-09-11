# Agent Review Orchestrator V0.2 Human Decision & Convergence Specification

**Status:** Implemented — deterministic suite green (229 passed), real Pi/Codex smoke green, real-agent E2E validated (custom decision, decision coverage, convergence gate, structured handoff). See `docs/V0_2_IMPLEMENTATION_AUDIT.md`.
**Target:** V0.2
**Baseline:** V0.1-RC3
**Primary evidence:** `docs/V0_1_CASE_AUDIT_20260911_PROD001_HANDOFF.md`

---

## 1. Background

V0.1 solved runtime perceptibility and session presentation, but the first post-V0.1 real Shopify case exposed a deeper workflow limitation.

In PROD-001, the workflow reached INITIAL_REVIEW after one Human Gate, with revision and ablation budgets still unused. Codex raised R001 as `BLOCKING + REQUIREMENT`; the Orchestrator converted it to `NEED_HUMAN` and immediately terminated the session with `HUMAN_HANDOFF` because V0 had no way to derive a new decision packet from a review issue.

The same case also exposed a more fundamental problem in the existing Human Gate interaction model: the terminal accepts arbitrary text, but only answers that map to one of the Agent-provided options become valid Decisions. If none of the options reflects the Human's intended requirement, the Human cannot authoritatively define a new decision inside the Gate.

This means the current system is closer to:

```text
Agent defines the decision space
        ↓
Human selects one offered option
```

than to the intended authority model:

```text
Agent proposes a decision space
        ↓
Human may select an option OR define a different decision
```

V0.2 closes that gap.

---

## 2. Goal

Upgrade Human Gate from **Human Confirmation** to **Human Authority**, and make downstream review-discovered Human decisions resumable instead of prematurely terminating the session.

V0.2 must answer two questions correctly:

1. **What if none of the Agent-proposed options is acceptable?**
2. **What if a real Human-owned decision is discovered only after DESIGN / REVIEW?**

The desired high-level flow is:

```text
Human Gate
  ├── choose offered option
  └── define custom decision
          ↓
     ACTIVE Decision
          ↓
     task_revision++
          ↓
  re-intake / re-investigate

Review NEED_HUMAN issue
          ↓
Decision coverage analysis
  ├── already covered by ACTIVE decision → treat as solution gap → REVISION
  ├── new Human decision required       → Convergence Gate
  └── cannot derive safe decision packet / budget exhausted → HUMAN_HANDOFF
```

---

## 3. Design Principles

### 3.1 Human owns the decision space, not only the final selection

Agent options are recommendations, not a closed enum owned by the Agent.

A Human must always be able to state a valid decision that was not proposed by the Agent.

### 3.2 Custom decisions must be explicit

Do **not** automatically treat every unmatched free-text answer as a valid custom decision.

An unmatched answer may be:

- a question;
- a request for clarification;
- accidental prose;
- an incomplete thought;
- an actual new decision.

Therefore the Human must explicitly enter a custom-decision mode before free text becomes authoritative.

### 3.3 Issue category does not by itself decide Human Authority

`REQUIREMENT` / `FACT` describes the reviewer's issue classification. It must not mechanically imply that a new Human decision is required.

A requirement issue may simply mean:

> the proposal failed to implement a requirement that the Human already decided.

Routing must distinguish **new decision required** from **existing decision not implemented**.

### 3.4 Probabilistic judgment stays with Agents; deterministic control stays with the Orchestrator

Determining whether an issue is semantically covered by an existing Human Decision may require Agent judgment.

The Orchestrator owns:

- validating referenced active decisions;
- deciding whether the returned classification is structurally valid;
- opening a Gate;
- budget accounting;
- task revision;
- Issue / Gate lifecycle;
- PASS / transition rules.

### 3.5 Human Gate remains bounded

V0.2 does not introduce unlimited interactive conversation.

The existing constraints remain:

- max 3 decisions per Gate;
- Human interruption budget remains a hard limit;
- unresolved / unsafe cases fail closed to `HUMAN_HANDOFF`.

---

## 4. Capability A — Explicit Custom Human Decision

### 4.1 CLI interaction

Every Human Gate question must expose a clear custom-decision path in addition to Agent-provided options.

Recommended interaction:

```text
[TRADE_OFF] TRAD-xxxx: 历史 DONE+PENDING 行如何处理？

  1. [compat_ignore] 保留历史行，查询精确匹配时忽略
  2. [rewrite]       批量重写历史行
  3. [hybrid]        新数据按新口径，历史逐步修复
  0. [custom]        以上都不合适，我自己定义

Your answer (number/key/label, 0=custom, '都按推荐', empty to skip):
```

If the Human selects `0`, `custom`, or equivalent explicit syntax:

```text
Enter your decision:
> 允许重新跑一轮进行修复，但只修复当前 PROD-001 受影响店铺，历史其他数据保持不变
```

That text becomes an authoritative Human Decision.

### 4.2 Data model

`GateAnswer` must distinguish offered-option answers from custom answers.

Recommended conceptual model:

```text
GateAnswer
- decision_key
- raw
- answer_type: OPTION | CUSTOM
- option_key: optional
- custom_text: optional
- matched / valid
```

A valid answer satisfies exactly one of:

```text
OPTION → option_key is present
CUSTOM → custom_text is non-empty
```

`Decision` should retain the origin:

```text
Decision
- selected_option_key: optional
- answer_text
- source: OPTION | CUSTOM
```

Exact field naming is implementation-defined; the semantics are normative.

### 4.3 Decision semantics

A valid custom decision behaves exactly like a valid offered option:

```text
persist Decision as ACTIVE
→ supersede prior ACTIVE decision with same decision_key when applicable
→ close Gate when all questions are answered
→ task_revision++
→ invalidate stale proposal/issues
→ rerun INTAKE or INVESTIGATE as appropriate
```

A custom answer inside an already-open Gate does **not** consume an additional Human interruption budget entry.

### 4.4 Unmatched free text is not automatically CUSTOM

Current behavior where an unmatched answer remains unresolved should remain unless the Human explicitly selected custom mode.

Example:

```text
Human types: "是否可以重跑一轮进行修复？"
```

This is a question, not a decision. It must not silently become an ACTIVE Decision.

The system may classify it as `QUESTION_ONLY` / unresolved and re-ask, but it must not grant it Requirement Authority automatically.

---

## 5. Capability B — NEED_HUMAN Convergence Gate

### 5.1 Current failure mode

Today:

```text
Codex issue
BLOCKING + REQUIREMENT/FACT
        ↓
OPEN → NEED_HUMAN
        ↓
try_gate_for_need_human_issues()
        ↓
HUMAN_HANDOFF
```

This discards remaining revision/ablation capacity and makes the Reviewer's category choice a single-point routing decision.

PROD-001 demonstrated this directly: R001 was categorized as `REQUIREMENT`, but an ACTIVE Human Decision D001 had already placed the disputed §5.4 display/statistics scope inside the requirement. The likely problem was proposal coverage, not missing Human semantics.

### 5.2 New routing stage: Human Authority Check

Before a blocking `REQUIREMENT` / `FACT` issue becomes `NEED_HUMAN`, V0.2 must evaluate whether a **new Human decision** is actually required.

Conceptual result:

```text
HumanAuthorityCheckResult
- issue_id
- outcome:
    COVERED_BY_ACTIVE_DECISION
    NEEDS_NEW_HUMAN_DECISION
    CANNOT_DETERMINE
- referenced_decision_ids[]
- rationale
- decision_candidate?   # required for NEEDS_NEW_HUMAN_DECISION
```

The semantic judgment may be performed by Pi or a dedicated read-only Agent call, but the Orchestrator must mechanically validate the result.

### 5.3 COVERED_BY_ACTIVE_DECISION

If the Agent claims an Issue is already covered by Human Decisions:

- every referenced `decision_id` must exist;
- every referenced Decision must be ACTIVE;
- the result must explain how the decision covers the disputed semantics.

Then the issue remains a blocker, but it is **not routed to Human**.

It should enter the normal solution correction path (typically REVISION).

Do not erase the original Reviewer category/provenance. Preserve auditability; routing metadata should record that the Human Authority check found the requirement already decided.

Conceptual event:

```text
ISSUE_COVERED_BY_DECISION
issue_id=R001
decision_ids=[D001]
```

### 5.4 NEEDS_NEW_HUMAN_DECISION

If no existing ACTIVE Decision resolves the semantics, the Agent must produce a gate-ready Human Decision Candidate:

```text
category
question
why_human
2-4 options with impact
recommendation optional
source_issue_ids
```

The Orchestrator validates the packet using the same structural rules as normal Human Gate candidates.

If Human interruption budget remains, open a **Convergence Gate** instead of terminating the session.

```text
INITIAL_REVIEW / CLOSURE_REVIEW / FINAL_REVIEW
        ↓
new Human-owned decision found
        ↓
CONVERGENCE HUMAN GATE
        ↓
option or custom answer
        ↓
task_revision++
        ↓
rebuild task/design basis
```

The Gate consumes one Human interruption because it is a new interruption boundary.

### 5.5 CANNOT_DETERMINE

If the Agent cannot safely determine coverage or cannot produce a valid decision packet:

- do not invent options in the Orchestrator;
- do not automatically downgrade the Issue;
- generate a structured handoff package;
- enter `HUMAN_HANDOFF`.

This preserves the fail-closed boundary.

---

## 6. Capability C — Human Gate State Consistency

PROD-001 exposed persistence inconsistency between:

```text
human-gate.json.current
human-gate.json.gates[]
human-gate.md
```

The current Gate may be CLOSED with answers while the history entry for the same `gate_id` remains OPEN and empty.

V0.2 must establish one consistent persistence rule.

Acceptable implementation approaches include:

1. update the matching `gates[]` entry by `gate_id` whenever `current` changes; or
2. redesign Gate history so there is one authoritative stored object and references do not duplicate mutable state.

Normative requirements:

- there must not be two conflicting persisted states for the same Gate;
- closing / partially answering a Gate must persist consistently;
- `human-gate.md` must be re-rendered when the active Gate state changes materially;
- `review show gate` must show the current persisted truth.

---

## 7. Capability D — Answer Validation Semantics

PROD-001 also showed that historical unmatched answers can keep validation at `PARTIAL` even after every Gate question has a later valid answer.

Validation must operate on the **current effective answer per decision_key**, not all historical attempts indiscriminately.

Recommended rule:

```text
for each decision_key:
    use the latest effective answer

OPTION valid  → answered
CUSTOM valid  → answered
unmatched     → unresolved unless a later valid answer exists
```

Historical failed attempts may remain in the audit trail, but they must not make a fully answered Gate appear `PARTIAL` forever.

When all Gate questions have valid effective answers, validation must be `COMPLETE`.

---

## 8. Capability E — Structured HUMAN_HANDOFF Package

`HUMAN_HANDOFF` remains a legitimate terminal state when:

- Human interruption budget is exhausted;
- a safe decision packet cannot be derived;
- root cause / external fact remains unavailable;
- convergence budgets are exhausted;
- the task crosses another explicit V0/V0.2 boundary.

But the handoff must no longer be only a one-line reason.

Generate:

```text
.review/<session>/handoff.md
```

Minimum contents:

```text
# Human Handoff

## Why the workflow stopped

## What the Human needs to decide / provide

## Blocking Issues
- id / category / problem / acceptance / evidence

## Relevant Active Decisions

## Suggested Options
(if a trustworthy candidate exists; otherwise say none)

## Relevant Artifacts
- task.md
- proposal.md
- issues.json
- decisions.json
- human-gate.md

## Recommended next action
```

`review show handoff [session-id]` should display it.

The handoff package is an aid, not a mechanism for the Orchestrator to invent Human decisions.

V0.2 does not require making an already-terminal `HUMAN_HANDOFF` session resumable. The primary goal is to avoid unnecessary handoff by opening a Convergence Gate before terminal handoff when safe and within budget.

---

## 9. Audit Events

V0.2 must close the audit gap observed in PROD-001.

At minimum introduce stable events for Human-authority routing, such as:

```text
ISSUE_HUMAN_AUTHORITY_CHECK_STARTED
ISSUE_COVERED_BY_DECISION
ISSUE_NEED_HUMAN
CONVERGENCE_GATE_CREATED
CUSTOM_DECISION_CAPTURED
HANDOFF_WRITTEN
```

Exact event names may vary, but `OPEN → NEED_HUMAN` must never occur silently.

The event stream must make it possible to reconstruct:

- when the Issue changed routing state;
- why Human authority was required or not required;
- which ACTIVE Decisions were considered;
- which Gate / Decision resolved the issue;
- why a final Handoff occurred.

---

## 10. Human Interruption Budget

V0.2 keeps the existing Human interruption budget semantics unless changed by a later telemetry-driven version.

Rules:

- opening a new normal Gate consumes one interruption;
- opening a new Convergence Gate consumes one interruption;
- choosing `custom` inside an existing Gate does **not** consume another interruption;
- re-answering an unresolved question in the same persisted Gate does not create another interruption;
- when the budget is exhausted, no new Gate is opened; generate `handoff.md` and terminate with `HUMAN_HANDOFF`.

Do not increase the default budget merely to hide convergence defects. V0.3 Telemetry should later evaluate whether the default of 2 remains appropriate.

---

## 11. State / Lifecycle Requirements

### 11.1 Issue routing is separate from Issue provenance

Do not destroy the original Reviewer classification in order to route around it.

For example, an R001 originally emitted as `REQUIREMENT` should remain auditable as such even if V0.2 determines:

```text
Human semantics already decided by D001
→ route to REVISION as solution coverage gap
```

### 11.2 Custom decisions are first-class Decisions

Custom decisions must participate in:

- append-only Decision history;
- ACTIVE / SUPERSEDED semantics;
- confirmed_decisions in the Change Contract;
- re-investigation context for FACT decisions;
- task revision invalidation;
- future Decision Coverage checks.

### 11.3 Task revision

Any new Human Decision that changes the design basis, whether offered-option or custom, follows the same rule:

```text
task_revision++
old proposal → STALE
active unresolved issues → SUPERSEDED as appropriate
rebuild task/design from new basis
```

---

## 12. CLI Experience

The normal Human Gate interaction should make Human Authority obvious.

Recommended prompt:

```text
Your answer:
  number / key / label
  0 or custom = define your own decision
  都按推荐 = apply recommendations where available
  empty = leave unresolved
```

Custom mode:

```text
Enter your decision (this becomes an authoritative session decision):
> ...
```

The UI must clearly distinguish:

```text
Agent suggestion
Human-selected option
Human-defined custom decision
```

Do not present a custom Human Decision as if it were an Agent recommendation.

---

## 13. Required Deterministic Scenarios

At minimum, add regression / integration coverage for the following.

### A. Custom Decision

1. Human selects an offered option → existing behavior preserved.
2. Human selects `custom` and enters text → ACTIVE custom Decision is persisted.
3. Custom Decision closes the question and causes normal `task_revision++` behavior.
4. Custom Decision does not consume an extra Human interruption.
5. Unmatched free text without explicit custom mode does not silently become a Decision.
6. A question-like unmatched answer remains unresolved / QUESTION_ONLY.
7. Normal CJK custom text is preserved as authoritative Decision content.

### B. Existing Decision Coverage

8. Blocking REQUIREMENT issue semantically covered by an ACTIVE Decision → no Human Gate / no Handoff; route to REVISION.
9. Coverage result referencing a nonexistent or SUPERSEDED Decision is rejected / fails closed.
10. Original Issue category/provenance remains auditable after coverage routing.

### C. New Human Decision from Review

11. Review produces a true new Human-owned decision while interruption budget remains → Convergence Gate opens.
12. Human chooses an offered convergence option → new Decision → task revision → workflow continues.
13. Human uses custom convergence decision → same continuation behavior.
14. Invalid decision candidate (<2 options, invalid recommendation, etc.) does not open a malformed Gate.

### D. Budget / Handoff

15. Convergence Gate required but interruption budget exhausted → `HUMAN_HANDOFF` + `handoff.md`.
16. Human Authority check cannot determine coverage / cannot derive packet → `HUMAN_HANDOFF` + `handoff.md`.
17. `review show handoff` works for a healthy handoff session.

### E. Gate Consistency

18. `current` and historical Gate representation agree after partial answer.
19. They agree after Gate close.
20. `human-gate.md` reflects the current persisted Gate truth.
21. Multiple Gates retain correct independent histories.

### F. Effective Answer Validation

22. First answer unmatched, second answer valid → Gate reaches COMPLETE.
23. Historical unmatched attempts remain auditable but no longer poison effective validation.
24. Latest custom answer is treated as valid effective answer.

### G. Auditability

25. `OPEN → NEED_HUMAN` emits an explicit event.
26. Existing-decision coverage emits referenced decision IDs.
27. Handoff reason and `handoff.md` can be reconstructed from persisted artifacts/events.

---

## 14. Real-Case Acceptance: PROD-001 Replay

V0.2 must include a deterministic replay/fixture modeled on:

`docs/V0_1_CASE_AUDIT_20260911_PROD001_HANDOFF.md`

The critical acceptance condition is:

```text
D001 already covers display/statistics unification
+
R001 is emitted as BLOCKING + REQUIREMENT claiming the proposal omitted that scope

V0.2 must NOT immediately HUMAN_HANDOFF merely because the Reviewer used category REQUIREMENT.
```

The authority check should be able to conclude that Human semantics are already established and route the solution gap into Revision, while preserving R001's original reviewer provenance.

This replay should be part of the deterministic suite so the real-case failure cannot regress silently.

---

## 15. Real-Agent Validation Gate

After deterministic coverage is green:

1. run real Pi/Codex smoke;
2. run at least one real workflow requiring a normal Human Gate with a **custom decision**;
3. run at least one real workflow where Review discovers a new Human-owned decision and opens a **Convergence Gate**;
4. verify Gate persistence and `review show gate` after answering;
5. verify `handoff.md` on one forced handoff path.

A successful V0.2 run should demonstrate that Human input remains authoritative without manual copy-paste into a new session.

---

## 16. Non-Goals

V0.2 does not implement:

- unlimited free-form chat inside Human Gate;
- automatic semantic interpretation of arbitrary unmatched text as a Decision;
- increasing Human interruption budget by default;
- V0.3 telemetry aggregation/dashboard;
- automatic model routing;
- Role-Based Agent Assignment;
- Multi Reviewer;
- automatic source implementation;
- deployment / production access;
- reopening arbitrary historical terminal handoff sessions;
- generic workflow DSL.

---

## 17. Exit Criteria

V0.2 is complete when all of the following are true:

1. Human can explicitly author a custom Decision when no offered option is acceptable.
2. Arbitrary unmatched text cannot silently acquire Requirement Authority.
3. `REQUIREMENT` / `FACT` blocker classification alone no longer forces terminal Handoff.
4. Existing ACTIVE Decisions are considered before requesting new Human authority.
5. Genuine downstream Human decisions can open a bounded Convergence Gate and resume the same session.
6. Custom and offered Decisions share the same task-revision and invalidation semantics.
7. Gate current/history/Markdown representations stay consistent.
8. Effective-answer validation reaches COMPLETE after later valid answers replace earlier failed attempts.
9. `OPEN → NEED_HUMAN` routing is explicitly auditable.
10. Terminal Handoff produces a durable `handoff.md` and is inspectable through CLI.
11. The PROD-001 deterministic replay no longer terminates solely because R001 is categorized REQUIREMENT when D001 already covers its semantics.
12. Full deterministic suite passes without V0/V0.1 regression.
13. Real Pi/Codex smoke remains healthy.
14. Real-agent custom-decision and convergence-gate scenarios pass.

---

## 18. Roadmap Position

The previously reserved V0.2 slot is now occupied by this capability because it emerged from real production workflow evidence.

```text
V0    Fixed Agent Workflow
V0.1  Runtime Progress Visibility / Session Presentation
V0.2  Human Decision & Convergence
V0.3  Workflow Telemetry
V0.5  Role-Based Agent Assignment
V0.7  Multi Reviewer
V1    Capability-Based Agent Routing
```

The rationale for reserving gaps remains valid: real usage should be allowed to interrupt the planned roadmap when it exposes a prerequisite capability.
