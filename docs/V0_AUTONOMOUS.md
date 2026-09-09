# Agent Review Orchestrator V0 Autonomous Implementation Protocol

**Purpose:** execution instructions for the coding agent implementing V0.  
**Source of truth:** `docs/V0_IMPLEMENTATION_SPEC.md`.

> Execute V0 autonomously from M0 through M6. Do not stop after each milestone to ask for permission. Design is frozen. Your job is implementation, verification and bounded correction — not product redesign.

---

## 1. Mission

Implement Agent Review Orchestrator V0 exactly as defined in `docs/V0_IMPLEMENTATION_SPEC.md`.

The final result must be a working Python CLI whose deterministic core is fully tested and whose real Pi/Codex adapters fail closed when required safe capabilities are unavailable.

Target commands:

```bash
review "<natural language request>"
review resume [session-id]
review status [session-id]
review show [final|gate|task|proposal|issues]
```

You are authorized to create/edit project files, tests and documentation needed to satisfy V0.

You are **not** authorized to expand V0 scope.

---

## 2. Read Before Acting

Before modifying code:

1. read `README.md`;
2. read `docs/V0_IMPLEMENTATION_SPEC.md` completely;
3. inspect the repository tree and current implementation/tests;
4. inspect any project-local instructions such as `AGENTS.md` if present;
5. determine the current milestone from actual repository state rather than assuming the project is empty.

If existing code already satisfies part of a milestone, preserve it unless it conflicts with the spec.

Do not rewrite working code merely for stylistic preference.

---

## 3. Authority Order

When sources disagree, use this priority:

```text
1. User's explicit current instruction
2. V0_IMPLEMENTATION_SPEC.md hard invariants and acceptance criteria
3. This V0_AUTONOMOUS.md execution protocol
4. Project-local instructions that do not conflict with 1–3
5. Existing implementation/tests
6. Your architectural preference
```

If levels 1–3 contain a true contradiction that materially blocks implementation, escalate to Human instead of inventing a resolution.

---

## 4. Autonomous Default

The default action is:

```text
inspect
→ implement
→ test
→ diagnose failures
→ fix
→ re-test
→ continue to next milestone
```

Do **not** ask for confirmation for:

- normal library choices consistent with the spec;
- internal naming;
- module boundaries already implied by the target layout;
- ordinary bug fixes;
- test fixture details;
- refactoring required to make tests pass;
- adding missing typing or validation;
- choosing a simple implementation over a more abstract one;
- proceeding from one milestone to the next after acceptance passes.

Do not stop merely to report progress. Continue execution.

---

## 5. Human Escalation Conditions

Stop and ask the Human only when at least one of these is true:

### H1 — Specification contradiction

Two authoritative V0 requirements cannot both be satisfied and the choice changes behavior or scope.

### H2 — Missing human-owned requirement

A behavior cannot be implemented correctly without a business/product decision not defined by the spec.

### H3 — Unsafe capability boundary

A required Pi/Codex integration can only be made to work by removing the read-only/fail-closed safety boundary.

Do not weaken safety automatically.

### H4 — Required external access/credential

Implementation has reached a point where a required final validation cannot be performed without user-provided installation, authentication, permission or external environment access.

Before escalating, complete all work that does not depend on that external access.

### H5 — Irrecoverable repository conflict

Existing user changes or repository state make the required change unsafe to perform without choosing which user work to discard/replace.

Never discard user changes automatically.

### H6 — Repeated unresolved technical blocker

After bounded investigation and multiple materially different repair attempts, the same blocker remains and no safe next action is available.

When escalating, provide:

```text
- exact blocker;
- evidence;
- what was already tried;
- what remains complete and passing;
- the smallest decision/action needed from Human.
```

Do not ask broad questions such as “what should I do?”.

---

## 6. Scope Guard

Do not implement any V0 non-goal, including:

```text
Web UI
Desktop UI
HTTP service
Database
Cloud deployment
Git/PR automation
Automatic implementation in target repositories
MCP verification
Alibaba Cloud integration
Multiple reviewers
Reviewer voting
Model routing
Generic workflow DSL
Generic multi-agent framework
Plugin system
```

If you notice an attractive future capability:

- do not implement it;
- do not restructure V0 to prepare for it unless current V0 requires that structure;
- optionally mention it in the final implementation report as future work.

A future possibility is not a present requirement.

---

## 7. Simplicity Rule

Prefer the smallest implementation that satisfies the current milestone and preserves the V0 invariants.

Avoid:

- speculative abstraction;
- framework-building;
- dependency injection systems beyond what adapter testing requires;
- generalized workflow engines;
- unnecessary async complexity;
- premature performance work;
- extra configuration surfaces.

The architecture should remain understandable from the package tree and core state machine.

---

## 8. Milestone Execution Loop

Execute milestones strictly in order:

```text
M0 → M1 → M2 → M3 → M4 → M5 → M6
```

For each milestone:

1. inspect current state;
2. identify the minimal delta required by that milestone;
3. implement the delta;
4. add/update tests before declaring completion;
5. run targeted tests;
6. fix failures;
7. run the full deterministic test suite;
8. inspect the diff for scope creep and accidental regressions;
9. verify milestone acceptance criteria from the spec;
10. continue automatically to the next milestone.

Do not skip a milestone because a later implementation seems easier.

---

## 9. M0 — Skeleton Execution

Implement:

- Python 3.11+ package metadata;
- Typer CLI entry point named `review`;
- package/module skeleton from the spec;
- core Pydantic models required for initial state/session creation;
- StateStore/session directory primitives;
- FakePiAdapter and FakeCodexAdapter interfaces;
- baseline pytest setup.

Required checks:

```bash
python -m pytest
review --help
```

Equivalent environment-specific commands are acceptable.

Do not connect real Pi/Codex yet.

M0 is accepted only when installation/import/CLI/session-persistence basics work and tests pass.

---

## 10. M1 — Deterministic State Machine Execution

Implement deterministic orchestration using fake adapters first.

Must support at least:

```text
INIT
→ DISCOVER
→ INTAKE
→ DESIGN
→ INITIAL_REVIEW
→ FINALIZE
→ DONE
```

Implement:

- state transitions;
- persist-before-transition behavior;
- base rendering for task/proposal/final artifacts;
- required exit-code mapping;
- basic `resume/status/show` behavior.

Acceptance scenario:

```text
Fake review returns no blockers
→ session reaches DONE
→ final.md exists
```

Do not add Human Gate or real agent complexity early.

---

## 11. M2 — Issue Lifecycle and Convergence Execution

Implement:

```text
OPEN → ADDRESSED → RESOLVED
```

plus required special states.

Implement:

- Issue persistence;
- BLOCKING/NON_BLOCKING behavior;
- mechanical PASS calculation;
- one Revision round;
- Closure Review;
- new-blocker restrictions;
- Ablation trigger;
- Ablation budget;
- HUMAN_HANDOFF after exhausted convergence.

Required scenarios include:

```text
no blocker → PASS
blocker → revision → resolved → PASS
blocker unchanged → ABLATION
ablation → PASS
ablation still blocked → HUMAN_HANDOFF
NON_BLOCKING → does not block PASS
```

Do not proceed until deterministic scenarios pass.

---

## 12. M3 — Human Gate Execution

Implement the Human Gate as a protocol/state-machine feature, not ad-hoc `input()` calls spread through phases.

Implement:

- Human candidate aggregation;
- allowed Human Gate categories;
- suppression rules;
- maximum 3 questions per packet;
- `human-gate.json`;
- `human-gate.md`;
- interactive terminal flow;
- non-TTY WAITING_FOR_HUMAN exit;
- natural-language decision normalization boundary;
- COMPLETE/PARTIAL/AMBIGUOUS/QUESTION_ONLY handling;
- “都按推荐” rules;
- append-only decisions;
- SUPERSEDED decisions;
- task revision;
- stale proposal invalidation;
- Human Interruption Budget.

Do not re-run completed phases for a partial answer.

Required scenarios from the implementation spec must pass before M4.

---

## 13. M4 — Pi Adapter Execution

Only after deterministic orchestration is stable, implement real Pi integration.

Requirements:

1. detect Pi binary/capabilities;
2. use the supported programmatic/non-interactive RPC path defined in the implementation spec;
3. launch one phase with complete context;
4. capture raw events under session `raw/`;
5. obtain one structured final result;
6. validate with Pydantic;
7. allow one protocol repair only;
8. enforce read-only repository tools;
9. fail closed when safe read-only operation cannot be established.

Implement phase methods:

```text
discover
investigate
design
revise
ablate
```

Do not give Pi edit/write/shell authority over a target repository for convenience.

### Missing local Pi

If Pi is not installed/configured in the implementation environment:

- finish adapter implementation;
- finish capability-detection behavior;
- test with fake/mock subprocess fixtures;
- continue subsequent work that does not require real Pi;
- defer only the real smoke-test acceptance item;
- report the exact missing external prerequisite at the end unless it blocks later implementation.

Do not replace Pi with another model/tool without Human authorization.

---

## 14. M5 — Codex Adapter Execution

Implement real Codex reviewer integration after M4 adapter boundaries are stable.

Requirements:

1. detect Codex binary/capabilities;
2. use a supported non-interactive execution path;
3. capture raw events/output;
4. require structured output whenever supported;
5. validate via Pydantic;
6. enforce reviewer read-only behavior;
7. fail closed when safe reviewer execution cannot be established.

Implement:

```text
initial_review
closure_review
final_review
```

Prompts must preserve the reviewer role:

- no proposal rewriting;
- no architecture-preference blockers;
- blocking acceptance criteria required;
- closure review is not another full review.

### Missing local Codex

Use the same policy as missing Pi: complete code/tests/capability detection, continue deterministic work, and defer only real smoke validation.

Do not silently substitute another reviewer.

---

## 15. M6 — Recovery and End-to-End Execution

Complete:

- Ctrl+C handling;
- child-process abort best effort;
- INTERRUPTED persistence;
- `review resume` from last complete boundary;
- protocol-repair cap;
- `events.jsonl`;
- `raw/` logging;
- full `status/show` behavior;
- integration fixture repositories;
- README usage instructions;
- end-to-end deterministic Case A/B/C.

Validate:

### Case A

```text
simple change
→ initial review passes
→ DONE
```

### Case B

```text
initial blocker
→ targeted revision
→ closure resolves
→ DONE
```

### Case C

```text
Human trade-off
→ WAITING_FOR_HUMAN
→ decision
→ task revision
→ redesign
→ review
→ DONE
```

If real Pi/Codex binaries are available, run bounded smoke tests after deterministic tests are green.

---

## 16. Test-Fix Policy

When a test fails:

1. determine whether the failure is implementation, test, environment or spec-related;
2. inspect the smallest relevant code path;
3. fix root cause rather than weakening the assertion;
4. rerun the smallest failing test;
5. rerun the relevant milestone suite;
6. rerun full deterministic suite before advancing.

Do not “fix” failures by:

- deleting meaningful tests;
- marking required tests skipped without an external-environment reason;
- broad exception swallowing;
- weakening safety checks;
- increasing budgets beyond the spec;
- changing acceptance criteria.

Environment-dependent real-agent tests may be explicitly skipped only when the binary/authentication truly is unavailable; deterministic adapter tests may not be skipped for that reason.

---

## 17. Bounded Repair Behavior

Autonomy does not mean infinite loops.

For one repeated implementation blocker:

- attempt the obvious fix;
- if it fails, investigate and try a materially different correction;
- if still failing, inspect assumptions/dependencies and try one final evidence-based correction;
- if no safe new path exists, use Human Escalation H6.

Do not endlessly toggle the same implementation.

Before escalating, complete unrelated milestones/work that can safely proceed, unless doing so would compound the blocker.

---

## 18. Repository Safety

While implementing this repository:

- preserve user-authored changes;
- do not reset/clean/revert unrelated work;
- do not force-push;
- do not delete documents/specifications to simplify implementation;
- do not modify repository visibility/settings;
- do not introduce secrets or credentials into the repository.

When the finished tool reviews another target repository, its Pi/Codex workflow must obey the read-only target-source boundary defined in the spec.

---

## 19. Documentation Policy

During implementation, update documentation only when required to keep actual CLI behavior and the frozen V0 contract consistent.

Do not rewrite the specification to justify implementation shortcuts.

If implementation exposes a genuine contradiction in the spec, escalate rather than silently editing the requirement.

README should eventually contain:

- install instructions;
- basic CLI examples;
- Pi/Codex prerequisites;
- safety model;
- `.review/` behavior;
- known V0 non-goals.

Keep detailed protocol semantics in the implementation spec rather than duplicating them throughout README.

---

## 20. Progress Reporting

If the execution environment supports long autonomous runs, keep progress messages brief and milestone-oriented.

Useful updates:

```text
M1 complete: fake no-blocker flow reaches DONE; full deterministic suite passes.

M3 partial: Human Gate persistence and partial answers work; task-revision invalidation test still failing and is being fixed.
```

Avoid narrating every file edit or command.

Do not ask for approval simply because a milestone completed.

---

## 21. Completion Verification

Before declaring V0 complete:

1. run the full deterministic test suite;
2. run formatter/linter/type checks configured by the project;
3. run Case A/B/C integration tests;
4. run real Pi/Codex smoke tests when prerequisites are available;
5. verify `review --help`;
6. verify all four public CLI commands;
7. inspect repository diff/status;
8. inspect the V0 final acceptance checklist item by item;
9. confirm no explicit non-goal was implemented;
10. confirm no secret/credential was added.

Do not declare success with known required deterministic test failures.

---

## 22. Final Report Format

At the end, report concisely:

```text
Status: DONE | BLOCKED

Implemented:
- M0 ...
- M1 ...
...

Validation:
- unit tests: ...
- integration Case A/B/C: ...
- Pi smoke: pass / unavailable / failed
- Codex smoke: pass / unavailable / failed

Remaining external prerequisites (if any):
- ...

Known V0 limitations:
- only limitations already implied by the spec
```

If blocked, include the smallest Human action required.

---

## 23. Start Command for an Implementation Agent

When this document is used to trigger autonomous implementation, the user should only need a short instruction such as:

```text
Read docs/V0_IMPLEMENTATION_SPEC.md and docs/V0_AUTONOMOUS.md.
Implement V0 autonomously from the current repository state through M6.
Follow milestone acceptance gates, run tests and fix failures yourself.
Do not expand V0 scope. Only stop for a Human Escalation condition defined in V0_AUTONOMOUS.md.
```

After receiving that instruction, begin by inspecting the repository and executing the earliest incomplete milestone. Do not return another implementation plan instead of starting work.