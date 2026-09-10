# Agent Review Orchestrator V0.1 Workflow Telemetry Specification

**Status:** Proposed
**Purpose:** Build observability foundation before Role-Based Agent Assignment.

---

# 1. Background

V0 validates that the Agent Review Workflow can replace manual coordination between multiple agents.

Before introducing dynamic Agent Role Assignment, the system needs data to answer:

- Which Agent combinations work well?
- Which tasks require stronger Authors?
- Which Reviewers provide useful findings?
- How much Human attention is actually reduced?
- Where does convergence fail?

Therefore V0.1 introduces Workflow Telemetry.

The goal is not analytics infrastructure. The goal is collecting structured workflow evidence for future Agent composition decisions.

---

# 2. Design Principles

## 2.1 Collect first, optimize later

Do not automatically select agents based on insufficient data.

Telemetry exists to support future decisions:

```
Workflow Data
      ↓
Analysis
      ↓
Role Assignment Strategy
```

---

## 2.2 Preserve existing workflow

V0.1 must not change:

- Author / Reviewer behavior;
- Human Gate semantics;
- Issue lifecycle;
- State machine;
- Final artifact format.

Only add observation capability.

---

# 3. Session Telemetry

Each workflow session should generate:

```
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

- Issue recall;
- False positive rate;
- Reviewer usefulness.

---

# 8. Human Cost Metrics

The primary product goal is reducing Human Attention Cost.

Record:

```json
{
  "human_metrics": {
    "interruptions": 1,
    "questions_answered": 3,
    "decision_categories": [
      "TRADE_OFF"
    ]
  }
}
```

Key metric:

> How much human involvement was required compared with traditional workflow?

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

After completion provide a lightweight evaluation:

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

Keep this optional and lightweight.

---

# 11. Future Usage

Telemetry enables later versions:

## V0.2 Role-Based Agent Assignment

Example:

```
Architecture Tasks:
Codex Author performs better

Simple Changes:
Pi Author is sufficient
```

## V0.3 Multi Reviewer

Example:

```
Pi:
High recall, more suggestions

Codex:
Lower noise, stronger blocking detection
```

## V1 Capability Routing

```
Task
 ↓
Required Capability
 ↓
Agent Team Selection
```

---

# 12. Non-Goals

V0.1 does not implement:

- Dashboard;
- Database analytics platform;
- Automatic Agent selection;
- Model scoring system;
- Reinforcement learning;
- Embedding based optimization.

The objective is collecting reliable workflow data first.
