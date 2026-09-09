# Agent Review Orchestrator V0 Implementation Spec

**Status:** Execution Baseline  
**Date:** 2026-09-09  
**Implementation:** Python CLI  
**Author Agent:** Pi  
**Reviewer Agent:** Codex

> This document is the implementation source of truth for V0. Implement exactly this scope. Do not expand the product while implementing it. Execution behavior is defined in `V0_AUTONOMOUS.md`.

---

## 1. V0 Definition of Done

V0 is complete when a user can enter an existing repository and run:

```bash
review "给同步任务增加暂停能力，尽量最小改动，不要重构整个任务框架"
```

and the tool can autonomously perform:

```text
Natural-language request
→ Discover repository
→ Build Change Contract
→ Human Gate only when required
→ Pi design
→ Codex initial review
→ Pi targeted revision when blocked
→ Codex closure review
→ Ablation when convergence fails
→ Final review
→ final.md or HUMAN_HANDOFF
```

The user must not manually copy proposals or reviews between Pi and Codex.

A successful session must create:

```text
.review/<session-id>/final.md
```

`final.md` must be implementation-ready for a separate coding agent that has access to the repository.

---

## 2. Scope

### 2.1 Supported

V0 supports existing repositories and bounded engineering changes:

- mid-development requirement changes;
- missing functionality;
- small/medium capability additions;
- bounded problem investigation;
- root-cause-based fix design;
- design review convergence.

### 2.2 Explicit non-goals

Do not implement any of the following in V0:

- automatic source-code implementation;
- Git commit / PR automation;
- deployment;
- production access;
- Alibaba Cloud / DB / Kafka / MCP verification;
- web or desktop UI;
- HTTP server;
- database persistence;
- multiple reviewers;
- reviewer voting;
- model router;
- generic workflow DSL;
- generic multi-agent framework;
- plugin architecture.

If an implementation decision makes one of these attractive, record it as future work and continue without it.

---

## 3. Core Invariants

These are hard requirements.

1. **Human owns requirement semantics.** Agents may transform wording but may not silently change business meaning.
2. **Repository owns current-state facts.** Pi should discover existing behavior from code, tests, configuration and project documents.
3. **Orchestrator owns process state.** Pi/Codex session memory is never authoritative.
4. **Only Orchestrator writes `.review/`.** Pi and Codex return structured outputs; they do not mutate workflow files.
5. **Review is issue-oriented.** Round is history; Issue is state.
6. **Codex does not decide PASS.** Orchestrator computes PASS mechanically.
7. **Pi cannot resolve an Issue.** Pi may mark it ADDRESSED; Codex verifies RESOLVED.
8. **Requirement basis changed → redesign.** V0 does not attempt smart incremental reuse of a stale proposal.
9. **Agents are read-only against project source during this workflow.** If safe read-only execution cannot be enforced, fail closed.
10. **Budgets are hard limits.** Do not silently add extra review, ablation, protocol-repair or Human Gate rounds.

---

## 4. Technology and Package Layout

Use:

- Python 3.11+
- Typer for CLI
- Pydantic v2 for protocol models
- stdlib subprocess / asyncio as appropriate
- JSON + Markdown files for persistent state
- pytest for tests

Target layout:

```text
agent-review-orchestrator/
├── pyproject.toml
├── README.md
├── docs/
│   ├── V0_IMPLEMENTATION_SPEC.md
│   └── V0_AUTONOMOUS.md
├── schemas/
│   └── codex-review.schema.json
├── src/
│   └── agent_review/
│       ├── __init__.py
│       ├── cli.py
│       ├── orchestrator.py
│       ├── state_machine.py
│       ├── models.py
│       ├── storage.py
│       ├── rendering.py
│       ├── config.py
│       ├── agents/
│       │   ├── base.py
│       │   ├── pi.py
│       │   └── codex.py
│       ├── phases/
│       │   ├── discover.py
│       │   ├── investigate.py
│       │   ├── intake.py
│       │   ├── design.py
│       │   ├── review.py
│       │   ├── revision.py
│       │   ├── ablation.py
│       │   ├── human_gate.py
│       │   └── finalize.py
│       └── prompts/
│           ├── discover.md
│           ├── investigate.md
│           ├── design.md
│           ├── revision.md
│           ├── ablation.md
│           ├── initial_review.md
│           └── closure_review.md
└── tests/
    ├── unit/
    ├── integration/
    └── fixtures/
```

Do not collapse V0 into one large script.

---

## 5. CLI Contract

Required commands:

```bash
review "<request>"
review resume [session-id]
review status [session-id]
review show [final|gate|task|proposal|issues]
```

Optional arguments for new sessions:

```bash
review --repo /path/to/repo "<request>"
review --kind change "<request>"
review --kind problem "<request>"
```

Defaults:

- repository = current working directory;
- task kind = discovered automatically unless explicitly supplied;
- session = latest unfinished session for `resume/status/show` when unambiguous.

Required exit codes:

```text
0   DONE
10  HUMAN_HANDOFF
20  WAITING_FOR_HUMAN
30  FAILED
130 INTERRUPTED
```

When stdin is not a TTY, Human Gate must persist its packet and exit with 20 rather than trying to interact.

---

## 6. Session Persistence Contract

Each run creates:

```text
<target-repo>/.review/<session-id>/
├── input.md
├── discovery.md
├── investigation.md
├── task.md
├── proposal.md
├── change-map.json
├── issues.json
├── decisions.json
├── human-gate.json
├── human-gate.md
├── state.json
├── ablation.md
├── final.md
├── events.jsonl
├── raw/
│   ├── pi-*.jsonl
│   └── codex-*.jsonl
└── history/
```

Not every file must exist from session start; create it when its phase first produces content.

Authoritative state is structured data in `.review/`, especially:

- `state.json`
- `issues.json`
- `decisions.json`

Markdown is the human-readable projection.

`events.jsonl` and `raw/` are audit/debug artifacts and must never be the sole source for recovery.

---

## 7. State Model

Required phases:

```text
INIT
DISCOVER
INVESTIGATE
INTAKE
WAITING_FOR_HUMAN
DESIGN
INITIAL_REVIEW
REVISION
CLOSURE_REVIEW
ABLATION
FINAL_REVIEW
FINALIZE
DONE
HUMAN_HANDOFF
INTERRUPTED
FAILED
```

Minimal `state.json`:

```json
{
  "session_id": "20260909-pause-sync",
  "repository": "/abs/path/to/repo",
  "task_kind": "CHANGE",
  "phase": "CLOSURE_REVIEW",
  "status": "RUNNING",
  "task_revision": 1,
  "active_gate": null,
  "round": 2,
  "budgets": {
    "revision_used": 1,
    "ablation_used": 0,
    "human_interruptions_used": 0,
    "protocol_retries_used": 0
  }
}
```

Persist phase outputs before persisting the transition to the next phase.

---

## 8. Task Kinds and Flow

### 8.1 Change Mode

```text
INIT
→ DISCOVER
→ INTAKE
→ optional HUMAN GATE
→ DESIGN
→ INITIAL_REVIEW
→ REVISION if blocked
→ CLOSURE_REVIEW
→ ABLATION if unresolved
→ FINAL_REVIEW
→ FINALIZE
→ DONE or HUMAN_HANDOFF
```

### 8.2 Problem Mode

```text
INIT
→ DISCOVER
→ INVESTIGATE
→ INTAKE only when root cause is SUPPORTED
→ remaining Change flow
```

If root cause remains UNRESOLVED and missing facts materially affect the fix direction, create a FACT Human Gate or HANDOFF according to budget/rules. Do not fabricate a fix design.

---

## 9. Agent Adapters

Define stable adapter interfaces so process integration can change later without changing orchestration logic.

```python
class PiAdapter(Protocol):
    def discover(...) -> DiscoveryResult: ...
    def investigate(...) -> InvestigationResult: ...
    def design(...) -> DesignResult: ...
    def revise(...) -> RevisionResult: ...
    def ablate(...) -> AblationResult: ...

class CodexAdapter(Protocol):
    def initial_review(...) -> ReviewResult: ...
    def closure_review(...) -> ReviewResult: ...
    def final_review(...) -> ReviewResult: ...
```

### 9.1 Pi

Preferred integration: `pi --mode rpc` over stdin/stdout JSONL.

At startup capability-detect:

- `pi` binary exists;
- RPC mode works;
- read-only tool allowlist is supported.

For V0 design phases, allow only repository-reading capabilities, e.g.:

```text
read, grep, find, ls
```

Do not enable edit/write/shell tools merely because they are convenient.

### 9.2 Codex

Preferred integration: non-interactive `codex exec` with structured/JSON output when available.

Capability-detect:

- `codex` binary exists;
- non-interactive execution works;
- output can be parsed deterministically;
- source repository can be enforced read-only / safely sandboxed.

If safe read-only reviewer execution cannot be established, stop with FAILED instead of running unrestricted.

### 9.3 Process lifetime

V0 should be stateless across agent calls:

```text
spawn → provide complete phase context → collect output → validate → exit
```

Do not rely on long-lived Pi/Codex conversational memory for correctness.

---

## 10. Structured Output and Protocol Repair

Every Agent phase returns one JSON object matching a Pydantic model.

Agents do not directly write `task.md`, `proposal.md`, `issues.json` or `final.md`.

Pipeline:

```text
agent output
→ parse JSON
→ Pydantic validate
→ one protocol-repair retry on failure
→ persist structured state
→ render Markdown
```

Protocol-repair prompt may only say, in effect:

> Re-emit the same conclusion using the required schema. Do not re-analyze or change the answer.

Default:

```json
{"max_protocol_retries": 1}
```

Second protocol failure → FAILED.

---

## 11. DISCOVER Contract

Purpose: establish facts before proposing solutions.

Pi must identify:

- current behavior;
- relevant components/files/classes/config/tests;
- existing constraints;
- likely change surface;
- unknowns;
- human-decision candidates.

Example model:

```json
{
  "task_kind": "CHANGE",
  "current_state": "...",
  "relevant_components": [],
  "existing_constraints": [],
  "change_surface": [],
  "unknowns": [],
  "human_candidates": []
}
```

DISCOVER must not:

- mutate code;
- create tests;
- choose final architecture;
- widen the request.

Rule:

```text
Facts → Problem Definition → Design
```

not:

```text
Early Idea → Search for supporting facts
```

---

## 12. INVESTIGATE Contract

Only for Problem Mode.

Required output:

```json
{
  "evidence": [],
  "hypotheses": [],
  "root_cause": "...",
  "root_cause_status": "SUPPORTED",
  "causal_chain": [],
  "missing_evidence": [],
  "human_candidates": []
}
```

`root_cause_status` only:

```text
SUPPORTED
UNRESOLVED
```

SUPPORTED requires:

- concrete evidence;
- coherent causal chain;
- no unresolved contradictory evidence that would change the fix.

Do not use fake numerical confidence percentages.

---

## 13. INTAKE / Change Contract

`task.md` must contain:

```text
User Intent
Current Behavior
Desired Behavior
Must Preserve
Scope
Known Constraints
Assumptions
Confirmed Decisions
Open Questions
Out of Scope
```

Requirement semantics come from the user; current-state facts come from repository investigation.

### Assumptions

An unresolved detail may become an assumption only when being wrong would not change the main design direction.

Each assumption must record:

```text
value
reason
impact_if_wrong
```

If `impact_if_wrong` changes requirement, scope, critical fact or architecture direction → Human Gate instead.

---

## 14. Human Gate Contract

Agents emit Human Gate candidates; only Orchestrator may pause the workflow.

Allowed categories:

```text
REQUIREMENT
FACT
TRADE_OFF
SCOPE
CONVERGENCE
```

Do not gate on:

- naming;
- local code organization;
- non-blocking suggestions;
- reviewer taste;
- future extensibility preferences;
- facts derivable from repository/project conventions.

### Decision Packet

One gate contains at most 3 blocking decisions.

Each question requires:

- stable `decision_key`;
- question;
- why Human authority is required;
- 2–4 meaningful options;
- impact per option;
- recommendation when justified (nullable).

User may answer structured or natural language, including “都按推荐”. This shortcut is valid only for questions that actually have a recommended option.

Answer validation result:

```text
COMPLETE
PARTIAL
AMBIGUOUS
QUESTION_ONLY
```

Partial/ambiguous responses keep the same gate open and ask only for unresolved decisions.

### Decision history

`decisions.json` is append-only.

Changing a prior decision creates a new ACTIVE decision and marks the previous one SUPERSEDED.

A Human answer becomes session fact and must not be asked again unless the Human later supersedes it.

### Task revision

If a Human decision changes design basis:

```text
task_revision += 1
old proposal → history / STALE
old review basis → STALE
→ DESIGN again
```

Do not perform clever partial reuse in V0.

---

## 15. Pi DESIGN Contract

Goal:

> Produce the minimum implementable design that satisfies the current Change Contract.

Not the most general architecture.

`proposal.md` must contain:

```text
Summary
Current Flow
Proposed Flow
Changes
Data Model Changes
Interface Changes
State / Lifecycle Changes
Failure Handling
Compatibility
Risks
Alternatives Considered
Verification Plan
Explicitly Unchanged
```

`Explicitly Unchanged` is mandatory.

Pi also returns `change-map.json`:

```json
{
  "affected_components": [],
  "data_changes": [],
  "api_changes": [],
  "config_changes": [],
  "behavior_changes": [],
  "unchanged_behaviors": []
}
```

Every proposal records `based_on_task_revision`.

---

## 16. Issue Model

Required issue fields:

```json
{
  "id": "R001",
  "category": "DESIGN",
  "severity": "BLOCKING",
  "status": "OPEN",
  "title": "...",
  "problem": "...",
  "evidence": [],
  "impact": "...",
  "acceptance": [],
  "introduced_round": 1,
  "provenance": "INITIAL_REVIEW",
  "based_on_task_revision": 1,
  "addressed_by": null,
  "resolution": null
}
```

Categories:

```text
DESIGN
REQUIREMENT
FACT
REGRESSION
SUGGESTION
```

Severity:

```text
BLOCKING
NON_BLOCKING
```

Lifecycle:

```text
OPEN
→ ADDRESSED
→ RESOLVED
```

Additional terminal/special states:

```text
NEED_HUMAN
ACCEPTED_RISK
SUPERSEDED
```

Every BLOCKING Issue must include explicit acceptance criteria.

---

## 17. Codex INITIAL REVIEW Contract

Codex reviews:

- Requirement Coverage;
- Correctness;
- Compatibility;
- Complexity;
- Failure Modes;
- Maintainability.

BLOCKING is allowed only when not fixing the issue can cause:

- unmet requirement;
- clear bug;
- data correctness issue;
- serious compatibility break;
- unacceptable engineering risk.

Architecture taste, abstraction preference and optional future extensibility are NON_BLOCKING.

Codex creates Issues; it does not rewrite the proposal.

---

## 18. Pi REVISION Contract

Input:

- current proposal;
- OPEN BLOCKING Issues;
- each Issue acceptance criteria;
- current Change Contract.

Rules:

- solve only listed blockers;
- preserve accepted design;
- do not expand scope;
- do not implement NON_BLOCKING suggestions merely because they exist.

Pi may mark an Issue ADDRESSED and explain what changed. It cannot mark RESOLVED.

---

## 19. Codex CLOSURE REVIEW Contract

Do not run a fresh full review.

Only verify:

1. whether existing blocker acceptance criteria are satisfied;
2. whether the revision introduced a blocking REGRESSION;
3. whether proposal still satisfies current `task_revision`.

After Initial Review, a new blocking Issue is allowed only as:

- REGRESSION; or
- truly severe MISSED_BLOCKER with explicit `why_not_detected_initially`.

Otherwise downgrade it to NON_BLOCKING.

---

## 20. PASS Rule

Codex never emits authoritative PASS.

Orchestrator computes:

```text
PASS =
  no OPEN BLOCKING
  AND no ADDRESSED BLOCKING
  AND no NEED_HUMAN
  AND no active Human Gate
  AND proposal.based_on_task_revision == task.task_revision
```

NON_BLOCKING issues never block PASS.

---

## 21. Revision / Ablation / Convergence Budgets

Defaults:

```json
{
  "max_revision_rounds": 1,
  "max_ablation_rounds": 1,
  "max_human_interruptions": 2,
  "max_protocol_retries": 1
}
```

Ablation triggers when either:

- a blocker remains unresolved after normal Revision/Closure; or
- blocker count does not decrease after normal Revision.

### Ablation goal

Stop patching the existing design and find the minimum sufficient design that still satisfies Requirement.

Pi may:

- remove optional capability;
- reduce abstraction;
- reduce automation;
- defer future extensibility;
- shrink implementation surface.

Final review checks the ablated design against Requirement and remaining blocker criteria.

If still unresolved after Ablation budget → HUMAN_HANDOFF.

---

## 22. Human Interruption Budget

Maximum Human Gate interruptions per session: 2.

Typical target:

```text
0 = ideal
1 = normal complex change
2 = maximum V0 low-interruption workflow
```

A third required interruption transitions to HUMAN_HANDOFF instead of asking another question.

If Intake discovers more than 3 interdependent blocking decisions, classify as `REQUIREMENT_TOO_AMBIGUOUS`, ask only the most upstream 1–3 decisions, then rerun Intake as needed within budget.

---

## 23. Finalization Contract

On PASS generate `final.md` containing:

```text
Change Goal
Current Behavior
Final Design
Affected Components
Explicitly Unchanged
Confirmed Human Decisions
Resolved Blocking Issues
Accepted Risks
Non-blocking Suggestions
Verification Plan
Implementation Notes
```

`final.md` must stand alone: a separate coding agent should not need to read the review history to implement the change.

---

## 24. Recovery and Failure Behavior

### Atomicity rule

Persist completed phase output first, then advance `state.json`.

### Ctrl+C

When interrupted:

1. stop/abort the current child agent when possible;
2. persist `phase/status = INTERRUPTED` without destroying prior valid state;
3. exit 130;
4. `review resume` must continue from the last complete boundary.

### FAILED

Use FAILED for tooling/protocol failures such as:

- Pi/Codex unavailable;
- required safe capability unavailable;
- repeated protocol parse failure;
- corrupted required session state.

### HUMAN_HANDOFF

Use HUMAN_HANDOFF for normal task-level boundaries such as:

- convergence budget exhausted;
- Human interruption budget exhausted;
- unresolved material fact;
- irreducible requirement ambiguity;
- real trade-off requiring manual ownership.

Handoff is not a crash.

---

## 25. Audit Events

Append to `events.jsonl` for meaningful state changes, e.g.:

```json
{"event":"SESSION_CREATED"}
{"event":"DISCOVER_STARTED"}
{"event":"DISCOVER_COMPLETED"}
{"event":"HUMAN_GATE_CREATED","gate_id":"HG001"}
{"event":"DECISION_APPLIED","decision_id":"D001"}
{"event":"ISSUE_CREATED","issue_id":"R001"}
{"event":"ISSUE_RESOLVED","issue_id":"R001"}
{"event":"SESSION_DONE"}
```

Do not use event log replay as the only recovery mechanism in V0.

---

## 26. Testing Requirements

### 26.1 Fake adapters are mandatory

Implement `FakePiAdapter` and `FakeCodexAdapter` before real agent adapters so the state machine can be exhaustively tested without model variability.

### 26.2 Required unit scenarios

At minimum:

1. no blocker → one-review PASS;
2. blocker → Revision → Closure → PASS;
3. blocker unchanged → Ablation;
4. Ablation → PASS;
5. Ablation still blocked → HUMAN_HANDOFF;
6. Requirement Human Gate;
7. partial Human response;
8. “都按推荐” with all recommendations;
9. missing recommendation prevents automatic choice;
10. Human decision increments task revision;
11. stale proposal forces redesign;
12. closure review illegal new blocker is downgraded/rejected;
13. third Human interruption → HUMAN_HANDOFF;
14. invalid agent JSON → one repair;
15. second invalid JSON → FAILED;
16. Ctrl+C → INTERRUPTED;
17. resume restores correct boundary;
18. NON_BLOCKING issue does not block PASS.

### 26.3 Integration fixtures

Create small deterministic test repositories for:

**Case A — simple change**  
Expected: Design → Initial Review → PASS.

**Case B — correctable blocker**  
Expected: Initial Review → Revision → Closure → PASS.

**Case C — Human trade-off**  
Expected: Human Gate → decision → task revision/redesign → PASS.

Real Pi/Codex integration tests may be opt-in when credentials/binaries are present; deterministic Fake Adapter tests must remain the CI baseline.

---

## 27. Milestone Execution Plan

Implementation must proceed in this order.

### M0 — Skeleton

Deliver:

- `pyproject.toml`;
- package layout;
- Typer CLI skeleton;
- Pydantic protocol models;
- session directory creation;
- StateStore;
- Fake adapters;
- initial tests.

Acceptance:

- package installs locally;
- `review --help` works;
- a fake session can be created and persisted;
- test suite passes.

### M1 — Deterministic State Machine

Deliver:

- phase enum;
- state transitions;
- Change flow through fake Discover/Design/Review;
- FINALIZE/DONE;
- exit codes.

Acceptance:

- fake no-blocker case reaches DONE;
- `final.md` is generated;
- restart/resume sees persisted state.

### M2 — Issue Lifecycle + Budgets

Deliver:

- Issue models and persistence;
- OPEN → ADDRESSED → RESOLVED;
- PASS calculator;
- normal Revision;
- Closure Review;
- Ablation trigger and budget.

Acceptance:

- unit scenarios 1–5 and 18 pass.

### M3 — Human Gate

Deliver:

- Human Candidate aggregation;
- Decision Packet JSON/Markdown;
- interactive + non-interactive behavior;
- natural-language answer normalization boundary;
- decisions append-only history;
- task revision / stale design logic;
- Human Interruption Budget.

Acceptance:

- unit scenarios 6–13 pass;
- interrupted gate can resume without re-running completed phases.

### M4 — Pi Adapter

Deliver:

- capability detection;
- RPC process wrapper;
- raw event capture;
- structured output parsing;
- Discover, Investigate, Design, Revision, Ablation prompts;
- read-only tool enforcement.

Acceptance:

- adapter contract tests pass;
- real smoke test succeeds when Pi is installed;
- project source cannot be mutated by the configured Pi workflow.

### M5 — Codex Adapter

Deliver:

- capability detection;
- non-interactive process wrapper;
- structured output parsing;
- Initial/Closure/Final Review prompts;
- read-only reviewer enforcement.

Acceptance:

- adapter contract tests pass;
- real smoke test succeeds when Codex is installed;
- reviewer cannot mutate project source.

### M6 — Recovery + End-to-End Validation

Deliver:

- Ctrl+C handling;
- protocol repair;
- events/raw logs;
- `resume/status/show` completion;
- three fixture integration cases;
- README usage update.

Acceptance:

- required unit suite passes;
- Case A/B/C pass;
- failed capability detection fails closed;
- resume after interruption works;
- no V0 non-goal has been implemented.

---

## 28. Required Implementation Quality Gates

At the end of each milestone:

1. run formatter/linter if configured;
2. run targeted tests for the milestone;
3. run the full deterministic test suite;
4. inspect `git diff` for scope creep;
5. update only necessary documentation;
6. do not advance with a known failing test unless the failure is explicitly environment-only and documented.

Prefer simple, testable code over architecture abstraction that is not required by V0.

---

## 29. Configuration

Keep V0 configuration small. A TOML shape is sufficient:

```toml
[pi]
binary = "pi"
model = ""

[codex]
binary = "codex"
model = ""

[budgets]
revision = 1
ablation = 1
human_interruptions = 2
protocol_retries = 1
```

Empty model means use the user's existing/default agent configuration.

Do not implement model routing.

---

## 30. Security Boundary

During V0 design/review workflow:

```text
Pi      → read repository only
Codex   → read repository only
Python Orchestrator → write only .review/ in target repository
```

The Orchestrator project itself may of course be modified while building this tool; the rule above applies to a target repository being reviewed by the finished tool.

No external systems are required for V0.

---

## 31. Execution Source of Truth

When implementation choices conflict, use this priority:

```text
1. Explicit V0 invariants in this document
2. Milestone acceptance criteria in this document
3. V0_AUTONOMOUS.md execution rules
4. Existing implementation/tests
5. Convenience or speculative future needs
```

If the spec contains a true contradiction that blocks implementation, stop and ask the Human one focused question. Do not silently reinterpret a requirement.

---

## 32. Final Acceptance Checklist

V0 is accepted only when all are true:

- [ ] `review "<request>"` works in an existing repository.
- [ ] `review resume` works after an interrupted or Human Gate session.
- [ ] `review status` reports phase, blockers and budgets.
- [ ] `review show` exposes current/final artifacts.
- [ ] Change Mode works end-to-end.
- [ ] Problem Mode refuses unsupported root-cause fix design.
- [ ] Pi is read-only against target source.
- [ ] Codex is read-only against target source.
- [ ] Human Gate supports natural-language answers and partial completion.
- [ ] Decisions are append-only and can be superseded.
- [ ] Task revision invalidates stale proposal deterministically.
- [ ] Issue lifecycle is enforced.
- [ ] PASS is computed by Orchestrator.
- [ ] Revision/Ablation/Human budgets are enforced.
- [ ] Protocol repair is capped.
- [ ] Ctrl+C + resume works.
- [ ] Fake Adapter deterministic suite passes.
- [ ] Integration Case A/B/C pass.
- [ ] Successful run produces standalone `final.md`.
- [ ] No explicit V0 non-goal has been implemented.

When all items pass, V0 is DONE.