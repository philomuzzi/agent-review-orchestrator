# Agent Review Orchestrator V0.1 Runtime Progress Visibility Specification

**Status:** Proposed
**Target:** V0.1 Evolution
**Purpose:** Make long-running workflows observable to the person using the CLI without exposing raw agent reasoning.

---

## 1. Background

The first real end-to-end use exposed a usability gap: while the workflow was executing, the terminal provided almost no indication of what was happening.

The user could not tell:

- which workflow phase was active;
- which agent was working;
- whether the process was healthy or stuck;
- whether a protocol retry was happening;
- whether review had found blockers;
- what artifact had just been produced.

This is not merely cosmetic CLI polish. A long-running agent workflow must be **recoverable, auditable, and perceptible**.

`state.json` and phase checkpoints solve recovery. `events.jsonl` solves auditability. V0.1 adds the missing human-facing runtime visibility layer.

---

## 2. Goal

Provide concise, trustworthy, phase-level progress while preserving the existing deterministic workflow.

The CLI should answer, at any moment:

> What is happening now, who is doing it, how long has it been running, and what happened immediately before this?

---

## 3. Design Principles

### 3.1 Orchestrator owns progress truth

Progress must be emitted by the Orchestrator from workflow state transitions and agent-call boundaries.

Agents must not invent or control progress state.

### 3.2 Do not stream raw reasoning

Default output must not dump raw agent output or model reasoning. Display workflow facts only.

### 3.3 Never invent percentage completion

Agent execution has no reliable percent-complete signal. Show phase, agent, elapsed time, and heartbeat instead.

### 3.4 Progress and telemetry share one event source

Do not implement separate instrumentation for CLI progress and later telemetry.

```text
Orchestrator
    ↓
Progress Events
    ├──→ CLI Renderer
    └──→ events.jsonl
              ↓
         V0.3 Telemetry
```

---

## 4. Event Model

V0.1 should emit stable workflow events such as:

```text
PHASE_STARTED
AGENT_CALL_STARTED
AGENT_CALL_HEARTBEAT
AGENT_CALL_COMPLETED
PROTOCOL_RETRY
ISSUES_INGESTED
HUMAN_GATE_OPENED
PHASE_COMPLETED
SESSION_COMPLETED
SESSION_HANDOFF
SESSION_FAILED
```

Each event should carry only deterministic or directly observed facts, for example:

```json
{
  "event": "AGENT_CALL_STARTED",
  "phase": "DESIGN",
  "agent": "pi",
  "timestamp": "..."
}
```

The event stream remains append-only.

---

## 5. Default CLI Experience

Example:

```text
Agent Review
Session: 20260910-203912
Mode: CHANGE
Author: Pi
Reviewer: Codex

[00:00] → DISCOVER
         Pi inspecting repository...
[00:18] ✓ DISCOVER
         42 files inspected · 6 relevant components

[00:18] → INTAKE
[00:20] ! HUMAN GATE
         2 decisions required

[01:06] → DESIGN
         Pi designing...
[01:24]   Pi still working... 18s
[01:43] ✓ DESIGN
         proposal.md generated

[01:43] → INITIAL REVIEW
         Codex reviewing proposal...
[02:11] ✓ INITIAL REVIEW
         2 blocking · 1 non-blocking

[03:04] ✓ DONE
         final.md generated
```

Exact wording is not normative. The information model is.

---

## 6. Heartbeat

Long agent calls must produce a lightweight heartbeat after a configurable quiet interval.

Example:

```text
[00:25] DESIGN · Pi working... 19s
[00:40] DESIGN · Pi working... 34s
[00:55] DESIGN · Pi working... 49s
```

Heartbeat means only:

> the orchestrator is still waiting on a live agent call.

It must not imply model progress percentage or success probability.

---

## 7. Output Levels

### Default

Show:

- phase transitions;
- agent call start/completion;
- heartbeat;
- phase result summary;
- blocker counts;
- Human Gate;
- retry notices;
- final outcome.

### `--verbose`

Additionally show:

- artifact paths;
- issue IDs;
- task revision;
- protocol retry details;
- state/budget changes.

### `--quiet`

Show only:

- Human Gate / Human Handoff;
- errors;
- final result.

This mode is intended for scripting and CI usage.

---

## 8. Compatibility and Safety

V0.1 must not change:

- Author / Reviewer semantics;
- Human Authority;
- Issue lifecycle;
- PASS computation;
- phase budgets;
- crash recovery behavior;
- read-only agent guarantees;
- final artifact format.

Progress rendering is a projection of workflow facts, not a new source of state.

---

## 9. Acceptance Criteria

V0.1 is complete when:

1. Every long-running phase visibly announces start and completion.
2. Every real agent call identifies the active agent and phase.
3. Long silent agent calls produce heartbeats without being mistaken for EOF.
4. Human Gate, retry, handoff, failure, and completion are visible immediately.
5. Default output remains concise and does not stream raw reasoning.
6. `--verbose` and `--quiet` behavior are deterministic and tested.
7. The same event source can later feed V0.3 telemetry aggregation.
8. Existing deterministic tests, real smoke tests, resume semantics, and fail-closed safety continue to pass.

---

## 10. Version Sequence

Minor versions intentionally leave gaps so real-use findings can be inserted without renumbering the entire roadmap.

```text
V0    Fixed Agent Workflow
V0.1  Runtime Progress Visibility
V0.3  Workflow Telemetry
V0.5  Role-Based Agent Assignment
V0.7  Multi Reviewer
V1    Capability-Based Agent Routing
```

Even-numbered minor slots remain intentionally unassigned for now.

---

## 11. Non-Goals

V0.1 does not implement:

- dashboards;
- telemetry analytics;
- model scoring;
- agent routing;
- multi-reviewer aggregation;
- raw chain-of-thought display;
- fake percentage progress;
- web or desktop UI.
