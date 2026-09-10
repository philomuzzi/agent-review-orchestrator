# Agent Review Orchestrator V0.2 Role-Based Agent Assignment

**Status:** Proposal
**Target:** V0.2 Evolution

## 1. Goal

V0 validates the workflow with fixed roles:

- Pi = Author
- Codex = Reviewer

V0.1 introduces Workflow Telemetry to collect real execution data and understand workflow effectiveness.

V0.2 uses those observations to remove the coupling between Agent identity and workflow responsibility.

The goal is:

> Agent identity should not define workflow responsibility. Roles define responsibilities; agents provide capabilities.

Support:

- Codex as Author + Pi as Reviewer;
- Pi as Author + Codex as Reviewer;
- one strong Author + one or more supporting Reviewers;
- future multi-agent combinations.

## 2. Evolution Context

The planned evolution path:

```
V0
Fixed Agent Workflow
(Pi Author + Codex Reviewer)

    ↓

V0.1
Workflow Telemetry

    ↓

V0.2
Role-Based Agent Assignment

    ↓

V0.3
Multi Reviewer

    ↓

V1
Capability-Based Agent Routing
```

Role-Based Agent Assignment should be driven by observed workflow data, not assumptions.

## 3. Core Model

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

## 4. Target Architecture

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

The workflow consumes roles, not concrete agents.

## 5. Capability Model

Do not route by agent name.

Future routing should consider:

- task characteristics;
- historical convergence metrics;
- Human cost;
- reviewer effectiveness.

Automatic capability routing remains outside V0.2 scope.

## 6. Implementation Roadmap

### M7 — Role Abstraction

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

### M8 — Multiple Reviewers

Support:

- review fan-out;
- issue aggregation;
- source tracking.

### M9 — Capability Routing

Future direction:

```
Task
 ↓
Required Capability
 ↓
Agent Selection
```

## 7. Non Goals

Do not implement:

- automatic model selection;
- reviewer voting;
- embedding-based issue merge;
- dynamic agent creation;
- unlimited reviewers;
- agent marketplace.

## 8. Long-term Direction

The goal is not a fixed Pi/Codex workflow.

The goal is an orchestrator that composes the right agent team for each engineering problem.
