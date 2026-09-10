# Agent Review Orchestrator V0.1 Runtime Progress Visibility Specification

**Status:** Proposed
**Target:** V0.1 Evolution
**Purpose:** Make long-running workflows observable and sessions understandable to the person using the CLI without exposing raw agent reasoning.

---

## 1. Background

The first real end-to-end use exposed two usability gaps.

First, while the workflow was executing, the terminal provided almost no indication of what was happening. The user could not tell:

- which workflow phase was active;
- which agent was working;
- whether the process was healthy or stuck;
- whether a protocol retry was happening;
- whether review had found blockers;
- what artifact had just been produced.

Second, session directories were generated from timestamp plus a truncated slice of the original request, producing names such as:

```text
20260910-103638-当前项目全局任务只支持一个同时执行如果需要另起一
```

These names are technically unique enough for storage but poor for human recognition: they are long, semantically truncated, visually noisy, and difficult to scan across multiple sessions.

This is not merely cosmetic CLI polish. A long-running agent workflow must be **recoverable, auditable, perceptible, and identifiable**.

`state.json` and phase checkpoints solve recovery. `events.jsonl` solves auditability. V0.1 adds the missing human-facing runtime visibility and session presentation layer.

---

## 2. Goal

Provide concise, trustworthy, phase-level progress and stable human-readable session presentation while preserving the existing deterministic workflow.

The CLI should answer, at any moment:

> What task is this, what is happening now, who is doing it, how long has it been running, and what happened immediately before this?

V0.1 therefore contains two sub-capabilities:

1. **Runtime Progress** — make execution perceptible while it is happening.
2. **Session Presentation** — make sessions easy to identify, scan, resume, and inspect.

---

## 3. Design Principles

### 3.1 Orchestrator owns progress truth

Progress must be emitted by the Orchestrator from workflow state transitions and agent-call boundaries.

Agents must not invent or control progress state.

### 3.2 Session identity and session title are different concepts

The filesystem identifier must optimize for stability and uniqueness.

The human-facing title must optimize for recognition.

Do not encode the full or truncated user request into the directory name.

### 3.3 Do not stream raw reasoning

Default output must not dump raw agent output or model reasoning. Display workflow facts only.

### 3.4 Never invent percentage completion

Agent execution has no reliable percent-complete signal. Show phase, agent, elapsed time, and heartbeat instead.

### 3.5 Progress and telemetry share one event source

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

## 4. Session Identity and Presentation

### 4.1 Stable short session ID

Session directories should use a compact machine-safe identifier independent of request wording.

Recommended format:

```text
.review/
└── 20260910-103638-a7f3/
```

The exact suffix algorithm is implementation-defined, but the identifier must be:

- unique enough within the repository;
- stable for the life of the session;
- short enough to type and scan;
- filesystem-safe across supported platforms;
- independent of later task-title changes.

The session directory must not be renamed after creation.

### 4.2 Semantic task title

Each session should persist a human-readable `task_title` describing what problem is being solved.

Example:

```json
{
  "session_id": "20260910-103638-a7f3",
  "task_title": "全局任务并行执行能力",
  "original_request": "当前项目全局任务只支持一个同时执行……"
}
```

The title should be produced without an extra standalone model call. Prefer deriving it from an existing DISCOVER / INTAKE agent response or deterministic host logic.

Recommended title constraints:

- concise and semantic;
- describe the problem/change, not the conversation wording;
- typically 10–20 Chinese characters or comparable length in other languages;
- no timestamp;
- no repository name unless required for disambiguation;
- no arbitrary prompt truncation.

Before a semantic title exists, the CLI may temporarily display a neutral placeholder such as `Current request`. Once persisted, the title becomes the default human-facing label.

### 4.3 Optional user-supplied name

Allow an optional explicit title override:

```bash
review --name "全局任务并行化" "当前项目全局任务只支持……"
```

A user-provided name should take precedence over generated presentation titles, while the underlying session ID remains unchanged.

### 4.4 Session-aware CLI commands

`status`, `resume`, and `show` should display both the short stable ID and the semantic title.

Example:

```text
Session: 20260910-103638-a7f3
Task:    全局任务并行执行能力
Repo:    shopify_api
Phase:   INITIAL_REVIEW
```

When showing recent sessions, prefer a compact scan-friendly table/list:

```text
Recent sessions

20260910-103638-a7f3  全局任务并行执行能力       HUMAN_HANDOFF
20260910-091522-b31c  大店同步 Kafka 内存优化    DONE
20260909-164211-97de  同步任务暂停能力           DONE
```

The title is presentation metadata, not a routing key or state-machine key.

---

## 5. Event Model

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

## 6. Default CLI Experience

Example:

```text
Agent Review
Session: 20260910-203912-a7f3
Task: 全局任务并行执行能力
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

## 7. Heartbeat

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

## 8. Output Levels

### Default

Show:

- session ID and task title;
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

## 9. Compatibility and Safety

V0.1 must not change:

- Author / Reviewer semantics;
- Human Authority;
- Issue lifecycle;
- PASS computation;
- phase budgets;
- crash recovery behavior;
- read-only agent guarantees;
- final artifact format.

Progress rendering and session titles are projections of workflow facts, not new authorities over workflow state.

Session ID remains authoritative for persistence and resume semantics. `task_title` is presentation metadata and must never silently change requirement semantics.

---

## 10. Acceptance Criteria

V0.1 is complete when:

1. Every long-running phase visibly announces start and completion.
2. Every real agent call identifies the active agent and phase.
3. Long silent agent calls produce heartbeats without being mistaken for EOF.
4. Human Gate, retry, handoff, failure, and completion are visible immediately.
5. Default output remains concise and does not stream raw reasoning.
6. `--verbose` and `--quiet` behavior are deterministic and tested.
7. The same event source can later feed V0.3 telemetry aggregation.
8. New sessions use a compact stable filesystem-safe session ID independent of the original request wording.
9. A semantic `task_title` is persisted and displayed by normal session-oriented CLI commands.
10. Session directories are never renamed when the semantic title becomes available or changes.
11. An optional user-supplied `--name` can override the presentation title without affecting session identity.
12. Recent-session output is scan-friendly and includes session ID, task title, and outcome/phase.
13. Existing deterministic tests, real smoke tests, resume semantics, and fail-closed safety continue to pass.
14. At least one real Agent E2E run confirms that the workflow is continuously understandable during execution and that the resulting session can be recognized later without reading the original request.

---

## 11. Version Sequence

Minor versions intentionally leave gaps so real-use findings can be inserted without renumbering the entire roadmap.

```text
V0    Fixed Agent Workflow
V0.1  Runtime Progress Visibility + Session Presentation
V0.3  Workflow Telemetry
V0.5  Role-Based Agent Assignment
V0.7  Multi Reviewer
V1    Capability-Based Agent Routing
```

Even-numbered minor slots remain intentionally unassigned for now.

---

## 12. Non-Goals

V0.1 does not implement:

- dashboards;
- telemetry analytics;
- model scoring;
- agent routing;
- multi-reviewer aggregation;
- raw chain-of-thought display;
- fake percentage progress;
- web or desktop UI;
- semantic search across historical sessions;
- automatic task clustering;
- renaming session directories after creation.
