# Agent Review Orchestrator

A local Python CLI orchestrator for converging design changes in existing software projects through a controlled **Pi Author + Codex Reviewer + Human Gate** workflow.

The tool never implements code itself. Given a natural-language request inside an existing repository, it converges an **implementation-ready design** (`final.md`) or stops at an explicit boundary (`HUMAN_HANDOFF`).

## Install

```bash
python -m pip install -e .
```

Requires Python 3.11+. External agents are optional at test time but required for real runs:

- **Pi** (`pi`, tested with 0.85.x) — used via `pi --mode rpc`;
- **Codex CLI** (`codex`, tested with 0.153.x) — used via non-interactive `codex exec`.

## Usage

```bash
review "给同步任务增加暂停能力，尽量最小改动"
review --repo /path/to/repo "request"        # default repo: current directory
review --kind change "request"               # or: problem
review --name "同步任务暂停" "request"        # explicit presentation title
review resume [session-id]                   # resume interrupted / gate sessions
review status [session-id]                   # phase, blockers, budgets
review status --list                         # recent sessions (id, title, outcome)
review show [final|gate|task|proposal|issues|events] [session-id]
review --version                             # package version
```

Output levels (V0.1): default shows phase transitions, agent activity,
heartbeats on long calls, gate/retry/outcome lines; `--verbose` adds
artifact paths, issue IDs, task revisions and budget state; `--quiet`
shows only gates, errors and the final result (for scripting/CI).

Sessions live under `.review/<session-id>/` where the id is compact and
request-independent (`20260910-103638-a7f3`); the id timestamp is the
host machine's **local wall-clock time** (ordering always uses the
persisted `created_at` metadata, never the visible id). A semantic
`task_title` (produced by DISCOVER, overridable with `--name`) is persisted
in `state.json` and shown by `status` / `resume` / `show` / `status --list`;
the directory itself is never renamed.

Answer a Human Gate by running `review resume` in a terminal; or read
`.review/<session>/human-gate.md` and answer later. Non-interactive runs
(stdin not a TTY) persist the gate packet and exit `20`.

### Exit codes

| Code | Meaning |
|------|---------|
| 0    | DONE — `final.md` written |
| 10   | HUMAN_HANDOFF — task-level boundary (budget exhausted, unresolved fact, real trade-off) |
| 20   | WAITING_FOR_HUMAN — gate packet persisted, needs answers |
| 30   | FAILED — tooling/protocol failure (fails closed) |
| 130  | INTERRUPTED — Ctrl+C; resume with `review resume` |

## Workflow

```text
request → DISCOVER → [INVESTIGATE for problem mode] → INTAKE (Change Contract)
→ [Human Gate only when required] → DESIGN → INITIAL_REVIEW
→ REVISION if blocked → CLOSURE_REVIEW → ABLATION if unresolved
→ FINAL_REVIEW → FINALIZE → final.md
```

Core rules (full contracts in [`docs/V0_IMPLEMENTATION_SPEC.md`](docs/V0_IMPLEMENTATION_SPEC.md)):

- Human owns requirement semantics; repository owns current-state facts.
- Codex raises structured issues; the orchestrator computes PASS mechanically.
- Pi may mark an issue ADDRESSED; only Codex verifies RESOLVED.
- Budgets are hard limits (1 revision, 1 ablation, 2 human interruptions, 1 protocol repair).
- A human decision that changes the design basis bumps `task_revision`; the old
  proposal goes to `history/` marked STALE and the session redesigns.

## Roadmap

```text
V0    Fixed Agent Workflow
V0.1  Runtime Progress Visibility / Session Presentation
V0.2  Human Decision & Convergence
V0.3  Workflow Telemetry
V0.5  Role-Based Agent Assignment
V0.7  Multi Reviewer
V1    Capability-Based Agent Routing
```

V0.2 was promoted from a reserved slot after real Shopify workflow evidence showed two prerequisite gaps: a Human could only choose Agent-proposed options, and downstream `NEED_HUMAN` review issues could terminate the session even when the required semantics were already decided or could have been resolved through another bounded Human Gate. See [`docs/V0_2_HUMAN_DECISION_CONVERGENCE_SPEC.md`](docs/V0_2_HUMAN_DECISION_CONVERGENCE_SPEC.md).

## Session state

Everything lands under the target repository:

```text
<repo>/.review/<session-id>/
├── input.md, discovery.md, investigation.md
├── task.md + task.json          # Change Contract
├── proposal.md + proposal.json  # current design
├── change-map.json, issues.json, decisions.json
├── human-gate.json + human-gate.md
├── state.json                   # authoritative phase/budget state
├── ablation.md, final.md
├── events.jsonl                 # audit trail
├── raw/                         # pi-*.jsonl / codex-*.jsonl agent I/O
└── history/                     # STALE proposals
```

Structured JSON is authoritative; Markdown is the human-readable projection.

Each phase uses a durable `phase-checkpoint.json` undo snapshot. Resume restores
an unfinished phase's artifacts and state together, then reruns that phase.
Confirmed Human answers are checkpointed before decision application. Proposal
archiving retains the last valid files; stale designs are excluded from active
proposal loading. Run only one workflow owner per session. Events and history
may include attempts rolled back after a crash.

## Safety model

- **Pi** runs with a read-only tool allowlist (`--tools read,grep,find,ls`); no edit/write/shell.
- **Codex** runs in the `read-only` sandbox.
- Both adapters probe capability at startup — including a write-probe in a
  scratch directory — and **fail closed** (exit 30) when safe read-only
  execution cannot be established.
- The Python orchestrator writes only `.review/` inside the target repository.

## Configuration (optional)

`~/.agent-review/config.toml` (or path in `AGENT_REVIEW_CONFIG`):

```toml
[pi]
binary = "pi"
model = ""            # empty = your existing default

[codex]
binary = "codex"
model = ""

[budgets]
revision = 1
ablation = 1
human_interruptions = 2
protocol_retries = 1
```

Binary names can also be overridden with `AGENT_REVIEW_PI_BIN` /
`AGENT_REVIEW_CODEX_BIN`. No model routing in V0.

## Development

```bash
python -m pip install -e .[dev]
python -m pytest                    # deterministic suite (fake/mock adapters)
AGENT_REVIEW_SMOKE=1 python -m pytest   # additionally run real pi/codex smoke tests
```

- `AGENT_REVIEW_FAKE_ADAPTERS=1` forces deterministic fake adapters (used by CLI tests).
- The structured reviewer contract is exported in [`schemas/codex-review.schema.json`](schemas/codex-review.schema.json).

## V0 non-goals

No automatic source implementation, Git commit/PR automation, deployment, production access, web/desktop UI, HTTP server, database persistence, multi-reviewer voting, model router, generic workflow DSL, multi-agent framework, or plugin architecture.
