# Agent Review Orchestrator V0.3 Workflow Telemetry Specification

**Status:** Proposed
**Purpose:** Build an observability and experiment-data foundation before Role-Based Agent Assignment.

---

# 1. Background

V0 validates that the Agent Review Workflow can replace manual coordination between multiple agents.

V0.1 first adds Runtime Progress Visibility because real usage showed that a long-running workflow cannot remain a terminal black box.

Before introducing dynamic Agent Role Assignment, the system still needs data to answer:

- Which Agent combinations work well?
- Which tasks require stronger Authors?
- Which Reviewers provide useful findings?
- How much Human attention is actually reduced?
- Where does convergence fail?

Therefore V0.3 introduces Workflow Telemetry.

The goal is not analytics infrastructure. The goal is collecting structured workflow evidence for future Agent composition decisions.

---

# 2. Design Principles

## 2.1 Collect first, optimize later

Do not automatically select agents based on insufficient data.

Telemetry exists to support future decisions:

```text
Workflow Data
      ↓
Analysis
      ↓
Role Assignment Strategy
```

## 2.2 Preserve existing workflow

V0.3 must not change:

- Author / Reviewer behavior;
- Human Gate semantics;
- Issue lifecycle;
- State machine;
- Final artifact format.

Only add observation capability.

## 2.3 Reuse V0.1 progress events

V0.3 should aggregate the same stable workflow events already used by Runtime Progress Visibility instead of creating a second instrumentation path.

```text
Orchestrator Events
      ├──→ CLI progress (V0.1)
      └──→ telemetry aggregation (V0.3)
```

---

# 3. Session Telemetry

Each workflow session should generate:

```text
.review/<session>/

├── metrics.json
├── telemetry.json
└── evaluation.md
```

---

# 4. Session Metadata

Record:

```json
{
  "session_id": "xxx",
  "task_kind": "CHANGE",
  "repository_type": "existing_project",
  "author": "pi",
  "reviewers": ["codex"],
  "start_time": "",
  "end_time": ""
}
```

This becomes the foundation for future Role Assignment analysis.

---

# 5. Task Characteristics

Collect:

```json
{
  "task_metrics": {
    "files_inspected": 20,
    "components_involved": 5,
    "phase_count": 8,
    "task_kind": "CHANGE"
  }
}
```

Purpose:

Understand what type of work each Agent combination handles well.

---

# 6. Author Metrics

Record:

```json
{
  "author_metrics": {
    "proposal_length": 5000,
    "initial_blocking_issues": 4,
    "revision_rounds": 1,
    "final_status": "PASS"
  }
}
```

Important signals:

- How often the Author produces acceptable designs;
- How many review cycles are required;
- Which task types require stronger reasoning.

---

# 7. Reviewer Metrics

Record:

```json
{
  "reviewer_metrics": {
    "issues_created": 6,
    "blocking_created": 3,
    "resolved_blocking": 2,
    "non_blocking_suggestions": 3
  }
}
```

Future analysis:

- Issue usefulness;
- false-positive patterns;
- reviewer noise;
- blocker discovery timing.

Issue count alone is not a quality metric.

---

# 8. Human Cost Metrics

The primary product goal is reducing Human Attention Cost.

Record:

```json
{
  "human_metrics": {
    "interruptions": 1,
    "questions_answered": 3,
    "decision_categories": ["TRADE_OFF"]
  }
}
```

Key questions include:

- Are human-interruption budgets appropriate?
- How often does `NEED_HUMAN` cause handoff?
- Which request ambiguities consume Human Gate budget before real trade-offs appear?

---

# 9. Convergence Metrics

Record:

```json
{
  "convergence": {
    "initial_blockers": 5,
    "after_revision": 1,
    "after_ablation": 0,
    "total_agent_rounds": 4
  }
}
```

Purpose:

Measure whether the workflow actually converges efficiently.

---

# 10. Human Evaluation

Machine metrics are insufficient.

After completion provide a lightweight optional evaluation:

```markdown
# Session Evaluation

## Final Design Quality
1-5

## Human Effort Compared With Normal Workflow
1-5

## Would I use this workflow again?
Yes / No

## Notes
```

---

# 11. Future Usage

## V0.5 Role-Based Agent Assignment

Use observed task, convergence, reviewer, and Human-cost data to compare fixed Agent combinations before making assignment configurable.

## V0.7 Multi Reviewer

Use real reviewer-quality data to decide whether additional reviewers add independent value or mainly add noise.

## V1 Capability Routing

```text
Task
 ↓
Required Capability
 ↓
Agent Team Selection
```

---

# 12. Non-Goals

V0.3 does not implement:

- Dashboard;
- database analytics platform;
- automatic Agent selection;
- model scoring system;
- reinforcement learning;
- embedding-based optimization.

The objective is collecting reliable workflow data first.

---

# 13. Version Sequence

```text
V0    Fixed Agent Workflow
V0.1  Runtime Progress Visibility
V0.3  Workflow Telemetry
V0.5  Role-Based Agent Assignment
V0.7  Multi Reviewer
V1    Capability-Based Agent Routing
```
