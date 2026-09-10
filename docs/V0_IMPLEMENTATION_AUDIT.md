# Agent Review Orchestrator V0 Implementation Audit

**Status:** V0-RC2 implementation; real-agent validation pending
**Audit Type:** Static implementation review against `V0_IMPLEMENTATION_SPEC.md`

## RC2 remediation record — 2026-09-10

The RC1 findings below are retained as the audit baseline. B001–B007 are
addressed in code with deterministic regression coverage in
`tests/unit/test_rc2_regressions.py`. The Pi Author / Codex Reviewer /
Orchestrator workflow owner / Human decision boundary model is unchanged.

| Finding / family | Confirmed root cause | RC2 correction | Remaining boundary |
| --- | --- | --- | --- |
| B001 / lifecycle | New Issue objects retained reviewer-supplied status and resolution metadata. | Ingestion assigns OPEN and clears agent lifecycle metadata in all three reviews; orchestrator closure restrictions still apply. | Reviewer evidence is not independently proven by the state machine. |
| B002 / authority | Routing checked NEED_HUMAN status but not blocking REQUIREMENT/FACT categories. | Such blockers are classified NEED_HUMAN and handed off before Revision/Ablation, including resumed author phases. | No decision options are invented from an Issue; a human must own the missing semantics/facts. |
| B003 / investigation | SUPPORTED had no evidence validator. | Require nonblank cause, located evidence and causal links; reject missing evidence or explicit unresolved contradictions through bounded protocol repair. Revalidate before persistence. | Mechanical validation cannot establish the truth of evidence; V0 conservatively rejects SUPPORTED with any missing evidence. |
| B004 / context | Stateless investigation calls omitted decisions. | Pass active decisions into investigation and include their questions and answer text in Pi's prompt. | Human facts remain authoritative session inputs. |
| B005 / artifact | Final rendering projected only a subset of the proposal. | Include every design/change-map field and contract constraints; sentinel tests verify no implementation fields disappear. | Actual design sufficiency still needs a real repository run. |
| B006 / recovery | Atomic individual writes did not protect multi-file phase boundaries; archiving deleted current artifacts. | Durable undo checkpoint before a phase, commit after outputs/state, recover before resume; preserve Human answers at an intermediate checkpoint. Archive by copy with unique names, hide retained stale designs, preserve retry accounting on resume. | Recovery may rerun an interrupted read-only agent call. Audit/history can retain entries from an uncommitted attempt. One workflow owner per session; no concurrent-writer or power-loss guarantee. |
| B007 / navigation | Pi had only read plus a bounded initial file map. | Enable exactly read, grep, find, ls; preserve disabled extensions/skills and absence of write/edit/shell tools. | Real Pi capability smoke requires configured authentication. |

Regression coverage includes forged lifecycle fields at every review phase,
Human-owned blockers, invalid SUPPORTED payloads, FACT re-investigation context,
all design/change-map fields in final.md, interrupted phase commits, individual
revision writes, interrupted Human decision application without duplicate
decisions, and persisted retry usage on resume.

Final verification: `python -m pytest --basetemp=.test-tmp/final-suite
-p no:cacheprovider --tb=short` passed **123 tests**, with the **2 opt-in real
smoke tests skipped** (79.84s). This includes 48 new RC2 regression cases and
the existing integration Cases A/B/C. `review --help`, fake-adapter CLI
run/status/show/resume checks, and `git diff --check` passed. No formatter,
linter, or type-check command is configured in `pyproject.toml`. The explicit
temporary directory avoids this sandbox's inaccessible default pytest temp
location; disabling pytest's cache avoids an inaccessible pre-existing cache.

Real smoke attempts in this environment failed closed before repository work:

- Pi: `No API key found for the selected model`.
- Codex: `Could not find home directory` / `Error finding codex home`.

RC2 is ready for the next real-repository validation gate once those execution
prerequisites are configured. This is not evidence that a real workflow passed.
N001–N003 remain deferred; N004 is covered by unique proposal history names.
No V0 non-goal was added.

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
