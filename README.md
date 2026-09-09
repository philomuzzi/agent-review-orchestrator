# Agent Review Orchestrator

A local Python CLI orchestrator for converging design changes in existing software projects through a controlled **Pi Author + Codex Reviewer + Human Gate** workflow.

## V0 Goal

Given a natural-language change request or problem description inside an existing repository, the tool should:

1. let Pi investigate the current codebase and establish the current state;
2. turn user intent + repository facts into a Change Contract;
3. ask the human only when a real requirement, scope, fact, or trade-off decision is required;
4. let Pi produce the minimum implementable design;
5. let Codex review it using structured issues and acceptance criteria;
6. automatically control revision, closure review, ablation, and convergence budgets;
7. produce a final implementation-ready `final.md` without requiring manual copy/paste between agents.

## V0 Scope

V0 focuses on existing repositories and medium/small engineering changes:

- mid-development requirement changes;
- missing functionality;
- bounded capability additions;
- problem investigation and fix design;
- design review convergence.

V0 intentionally does **not** include automatic implementation, Git commits, deployment, production access, MCP-based environment verification, multi-reviewer voting, or a generic multi-agent framework.

## Architecture

```text
Human
  │
  ▼
Python CLI Orchestrator
  ├── Pi        → Discover / Investigate / Design / Revision / Ablation
  ├── Codex     → Initial Review / Closure Review / Final Review
  └── State     → deterministic lifecycle, budgets, Human Gate, persistence
```

Core rule:

> Agents may change the solution, but must not silently change the requirement.

## Status

**V0 design frozen. Repository is ready for autonomous implementation.**

Execution documents:

- [`docs/V0_IMPLEMENTATION_SPEC.md`](docs/V0_IMPLEMENTATION_SPEC.md) — what V0 must implement, protocol contracts, milestones and acceptance criteria.
- [`docs/V0_AUTONOMOUS.md`](docs/V0_AUTONOMOUS.md) — how an implementation agent must autonomously execute M0→M6, test, repair failures and escalate only real blockers.

## Autonomous Implementation Trigger

A coding agent can be started with a short instruction:

```text
Read docs/V0_IMPLEMENTATION_SPEC.md and docs/V0_AUTONOMOUS.md.
Implement V0 autonomously from the current repository state through M6.
Follow milestone acceptance gates, run tests and fix failures yourself.
Do not expand V0 scope. Only stop for a Human Escalation condition defined in V0_AUTONOMOUS.md.
```

## Planned CLI

```text
review "<natural language request>"
review resume
review status
review show
```

Each run persists its authoritative state under the target repository's `.review/<session>/` directory so the workflow is resumable and auditable.
