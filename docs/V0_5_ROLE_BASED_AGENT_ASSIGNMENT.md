# Agent Review Orchestrator V0.5 Role-Based Agent Assignment

**Status:** Proposal
**Target:** V0.5 Evolution

## 1. Goal

V0 validates the workflow with fixed roles:

- Pi = Author
- Codex = Reviewer

V0.1 adds Runtime Progress Visibility so long-running workflows are no longer a terminal black box.

V0.3 adds Workflow Telemetry to collect real execution data and understand workflow effectiveness.

V0.5 uses those observations to remove the coupling between Agent identity and workflow responsibility.

The goal is:

> Agent identity should not define workflow responsibility. Roles define responsibilities; agents provide capabilities.

Support:

- Codex as Author + Pi as Reviewer;
- Pi as Author + Codex as Reviewer;
- one strong Author + one or more supporting Reviewers;
- future multi-agent combinations.

## 2. Evolution Context

The planned evolution path:

```text
V0
Fixed Agent Workflow
(Pi Author + Codex Reviewer)

    ↓

V0.1
Runtime Progress Visibility

    ↓

V0.3
Workflow Telemetry

    ↓

V0.5
Role-Based Agent Assignment

    ↓

V0.7
Multi Reviewer

    ↓

V1
Capability-Based Agent Routing
```

Role-Based Agent Assignment should be driven by observed workflow data, not assumptions.

## 3. Core Model

```text
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

```text
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

Automatic capability routing remains outside V0.5 scope.

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

Deferred to V0.7. V0.5 should keep the role abstraction compatible with a reviewer list, but does not need to implement multi-review aggregation yet.

### M9 — Capability Routing

Future direction:

```text
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
