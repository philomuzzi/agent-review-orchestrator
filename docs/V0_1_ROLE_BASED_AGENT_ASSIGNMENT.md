# Agent Review Orchestrator V0.1 Role-Based Agent Assignment

**Status:** Proposal
**Target:** V0.1 Evolution

## 1. Goal

V0 fixes the workflow problem by establishing:

- Pi = Author
- Codex = Reviewer

V0.1 removes this coupling.

The goal is:

> Agent identity should not define workflow responsibility. Roles define responsibilities; agents provide capabilities.

Support:

- Codex as Author + Pi as Reviewer;
- Pi as Author + Codex as Reviewer;
- one strong Author + one or more supporting Reviewers;
- future multi-agent combinations.

---

## 2. Core Model

Current model:

```
Pi
 |
 Author

Codex
 |
 Reviewer
```

Target model:

```
Role
 |
 +-- Author
 +-- Reviewer

Agent
 |
 +-- Pi
 +-- Codex
 +-- GPT
 +-- Claude
```

Agent = capability provider.

Role = workflow responsibility.

---

## 3. Target Architecture

```
                 Orchestrator

                       |

              Role Assignment Layer

                       |

        -------------------------------

        Author Role          Reviewer Roles

             |                    |

          Agent A              Agent B/C
```

Example:

```yaml
roles:
  author: codex
  reviewers:
    - pi
```

or:

```yaml
roles:
  author: codex
  reviewers:
    - pi
    - gpt
```

---

## 4. Capability Model

Do not route by agent name.

Bad:

```yaml
author: codex
reviewer: pi
```

Better:

```yaml
agents:
  codex:
    capabilities:
      - reasoning
      - architecture
      - coding
      - large_context

  pi:
    capabilities:
      - fast_review
      - risk_detection
      - simplification
```

Roles define required capabilities.

```yaml
roles:
  author:
    required:
      - reasoning
      - architecture

  reviewer:
    required:
      - risk_detection
```

Automatic capability routing is not part of V0.1.

---

## 5. Configuration

V0:

```toml
Pi = Author
Codex = Reviewer
```

V0.1:

```toml
[agents.pi]
binary = "pi"

[agents.codex]
binary = "codex"

[roles]
author = "codex"
reviewers = ["pi"]
```

The workflow consumes roles, not concrete agents.

---

## 6. Adapter Refactoring

Current:

```
PiAdapter
  discover()
  design()

CodexAdapter
  review()
```

Target:

```
AuthorAdapter
  discover()
  investigate()
  design()
  revise()
  ablate()

ReviewerAdapter
  initial_review()
  closure_review()
  final_review()
```

Concrete implementations:

```
CodexAuthorAdapter
PiReviewerAdapter
```

or the reverse.

---

## 7. Multi Reviewer Support

V0.1 supports:

```
1 Author
+
1~2 Reviewers
```

Flow:

```
Proposal

   |
   |
----------------
|       |       |
Pi     GPT    Claude
Review Review Review

   |

Issue Aggregator

   |

Unified Issue Set
```

---

## 8. Issue Source Tracking

Multiple reviewers require provenance.

Issue schema extension:

```json
{
  "id": "R001",
  "source": {
    "agent": "pi",
    "role": "reviewer"
  }
}
```

Purpose:

- identify issue origin;
- evaluate reviewer quality;
- optimize future routing.

---

## 9. Reviewer Independence

Reviewer permissions:

Allowed:

- read repository;
- create issues;
- provide evidence;
- define acceptance criteria.

Forbidden:

- modify proposal;
- change requirement;
- resolve own issues.

Author permissions:

Allowed:

- investigate;
- design;
- revise;
- ablate.

Author cannot close issues.

---

## 10. Agent Combination Patterns

### Pattern A

Strong Author + Weak Reviewer

```
Author:
Codex

Reviewer:
Pi
```

Default engineering mode.

---

### Pattern B

Strong Author + Multiple Reviewers

```
Author:
Codex

Reviewers:
Pi
GPT
```

Architecture changes.

---

### Pattern C

Weak Author + Strong Reviewer

```
Author:
Pi

Reviewer:
Codex
```

Cost optimization.

---

## 11. Implementation Roadmap

### M7 — Role Abstraction

Goal:

Separate Agent and Role.

Changes:

- Agent Registry;
- Role Assignment;
- Author Adapter;
- Reviewer Adapter.

Acceptance:

```toml
author="codex"
reviewers=["pi"]
```

works without changing workflow logic.

---

### M8 — Multiple Reviewers

Changes:

- review fan-out;
- issue aggregation;
- source tracking.

Acceptance:

Multiple reviewers produce one unified issue set.

---

### M9 — Capability Routing

Future:

```
Task
 ↓
Required Capability
 ↓
Agent Selection
```

Not included in V0.1.

---

## 12. Non Goals

Do not implement:

- automatic model selection;
- reviewer voting;
- embedding-based issue merge;
- dynamic agent creation;
- unlimited reviewers;
- agent marketplace.

---

## 13. Long-term Direction

The evolution path:

```
V0
Fixed Agent Roles

    ↓

V0.1
Role-Based Agent Assignment

    ↓

V1
Capability-Based Agent Team Composition
```

The long-term goal is not a fixed Pi/Codex workflow.

It is an orchestrator that composes the right agent team for each engineering problem.
