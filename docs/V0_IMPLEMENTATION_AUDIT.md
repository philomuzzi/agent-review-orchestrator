# Agent Review Orchestrator V0 Implementation Audit

**Status:** V0-RC1
**Audit Type:** Static implementation review against `V0_IMPLEMENTATION_SPEC.md`

## Conclusion

The V0 implementation has the correct overall architecture:

- Python CLI orchestrator;
- deterministic state machine;
- Pi Author + Codex Reviewer adapters;
- Human Gate protocol;
- Issue lifecycle;
- revision / ablation budgets;
- session persistence.

However, V0 Definition of Done is not yet reached. Several deterministic boundaries are still enforced by prompts or conventions rather than by the Orchestrator itself.

## Blocking Issues

## B001 — Reviewer can influence Issue lifecycle

**Problem**

Codex output currently includes Issue status fields. The Orchestrator does not normalize newly created Issues to `OPEN`.

Potential impact:

- Reviewer could accidentally or intentionally return `RESOLVED`.
- PASS calculation may ignore a blocker that was never actually verified.

**Expected behavior**

- Initial Review creates only `OPEN` issues.
- Pi can only move `OPEN -> ADDRESSED`.
- Codex Closure Review moves `ADDRESSED -> RESOLVED`.
- Orchestrator owns lifecycle transitions.

---

## B002 — Requirement / Fact blockers can bypass Human Authority

**Problem**

A Codex blocker with category `REQUIREMENT` or `FACT` can currently enter Revision flow.

**Expected behavior**

Blocking issues that require Human authority must route to Human Gate or HUMAN_HANDOFF.

Pi may change solutions, but cannot decide requirement semantics or missing business facts.

---

## B003 — Problem Mode Root Cause validation is insufficient

**Problem**

`SUPPORTED` root cause status is accepted without mechanical validation.

A valid investigation should require:

- non-empty root cause;
- evidence;
- causal chain;
- no unresolved contradiction affecting the fix direction.

**Expected behavior**

Invalid `SUPPORTED` output should fail validation or downgrade to `UNRESOLVED`.

---

## B004 — Human FACT decisions are not passed into re-investigation

**Problem**

Problem Mode supports:

`INVESTIGATE -> FACT Human Gate -> INVESTIGATE`

but the second investigation does not receive the confirmed Human facts as context.

**Expected behavior**

Re-investigation input must include active decisions from `decisions.json`.

---

## B005 — final.md may lose implementation details

**Problem**

The Proposal contains implementation-relevant sections:

- Data Model Changes;
- Interface Changes;
- State/Lifecycle Changes;
- Compatibility;
- Config/API/Behavior changes.

The final document currently summarizes only part of these fields.

**Expected behavior**

`final.md` must be standalone and implementation-ready.

A coding agent should not need to read proposal history.

---

## B006 — Phase recovery is not transactionally safe

**Problem**

Single-file writes are atomic, but multi-file phase changes are not.

Example:

1. archive old proposal;
2. delete current proposal files;
3. process crashes;
4. new proposal is not written.

The session may lose the last valid design boundary.

**Expected behavior**

Never delete the last valid artifact before a new durable artifact exists.

Recommended approach:

- write new proposal generation;
- persist completion;
- update state pointer;
- archive old generation afterward.

---

## B007 — Pi discovery capability is too restricted

**Problem**

Pi currently receives only `read` capability.

This is safe, but large repositories may become effectively undiscoverable because Pi cannot use basic read-only navigation.

**Expected behavior**

Allow read-only navigation capabilities:

- read;
- grep;
- find;
- ls.

Do not enable:

- write;
- edit;
- shell execution.

---

# Non-blocking Improvements

## N001 — Human Gate semantic matching

Current answer normalization is mostly exact matching.

Future improvement:

Allow semantic matching for natural language answers while keeping deterministic validation.

---

## N002 — Decision key stability

Current decision keys are derived from category/question text.

Equivalent questions with different wording may generate different keys.

---

## N003 — Resume config persistence

A resumed session should remember the configuration used when it was created.

---

## N004 — History artifact naming

History filenames should avoid possible collisions from second-level timestamps.

---

# Next Validation Gate

After fixing B001-B007:

1. Run deterministic test suite.
2. Run optional real Pi/Codex smoke tests.
3. Execute one real repository workflow:

```bash
review "<real change request>"
```

Validate that:

- Human interruptions are minimal;
- final.md contains sufficient implementation detail;
- no manual Pi/Codex copy-paste is required.
