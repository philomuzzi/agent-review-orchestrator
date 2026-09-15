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
review show [final|result|gate|task|proposal|issues|events|handoff] [session-id]
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

### Human Gate answering (V0.2)

Every gate question lists the Agent-proposed options **plus a reserved
custom path**:

```text
1. [option_a] ...
2. [option_b] ...
0. [custom] none of the above — I will define the decision

Your answer (number/key/label, 0=custom, '都按推荐', empty to skip):
```

- `0` / `custom` / `自定义` opens custom-decision mode: your own text
  becomes an **authoritative session decision** (same semantics as an
  offered option: ACTIVE decision, `task_revision++`, stale proposals
  archived, redesign). Custom answers never consume an extra Human
  interruption.
- Unmatched free text is **never** promoted to a decision — it stays an
  unresolved attempt (you can re-answer on a later `review resume`;
  only the latest answer per question counts).
- Empty input skips the question; the gate stays open and resumable.

When a review discovers a blocking `REQUIREMENT`/`FACT` issue, the
orchestrator first runs a **Human Authority Check** against your ACTIVE
decisions:

- already decided → the issue is routed back into revision as a solution
  gap (the session does **not** stop just because the reviewer used the
  REQUIREMENT category);
- genuinely undecided → a bounded **Convergence Gate** opens (consumes
  one Human interruption, answer options or custom like any gate); your
  answer rebuilds the task basis and the same session continues;
- undeterminable or out of budget → the session terminates with
  `HUMAN_HANDOFF` and a structured `.review/<session>/handoff.md`
  (inspect with `review show handoff [session-id]`) describing exactly
  what the Human needs to decide, the blocking issues and any derivable
  option packet.

Gate state (`human-gate.json` current/history and `human-gate.md`) stays
consistent after partial answers, resumes and closes; `review show gate`
always renders the persisted truth, marking Human-defined decisions
explicitly.

### Exit codes

| Code | Meaning |
|------|---------|
| 0    | DONE — `final.md` + `session-result.md` (APPROVED) written |
| 10   | Terminal boundary — see `session-result.md` for the classification: DESIGN_NOT_APPROVED / NEEDS_HUMAN_DECISION / DECOMPOSITION_REQUIRED / OUT_OF_SCOPE |
| 20   | WAITING_FOR_HUMAN — gate packet persisted, needs answers |
| 30   | FAILED — tooling/protocol failure (fails closed) |
| 130  | INTERRUPTED — Ctrl+C; resume with `review resume` |

## Workflow

```text
request → DISCOVER → SCOPE GUARD (V0.3)
├─ DECOMPOSITION_REQUIRED → stops BEFORE DESIGN + decomposition proposal
├─ OUT_OF_SCOPE → stops + unsupported reason
└─ BOUNDED → [INVESTIGATE for problem mode] → INTAKE (Change Contract)
→ [Human Gate only when required; independent questions batch (V0.3)] → DESIGN → INITIAL_REVIEW
→ [Human Authority Check on blocking REQUIREMENT/FACT issues]
→ correction by REVIEWER-RECOMMENDED action (V0.3 generic routing):
   FULL_REVISION / FOCUSED_REVISION / ABLATION (explicit only) / HUMAN_DECISION / STOP
→ CLOSURE_REVIEW (differential; material-progress assessment)
→ FINAL_REVIEW (readiness; acceptance completeness) → FINALIZE → final.md
   (a genuinely new Human decision found in review opens a Convergence
    Gate and rebuilds the task basis in the same session)
```

Every terminal session writes `session-result.md` (V0.3) — the primary
human-facing artifact — plus `telemetry.json`. Result statuses:
`APPROVED`, `DESIGN_NOT_APPROVED` (engineering conclusion; authority
settled), `NEEDS_HUMAN_DECISION` (genuine new Human authority required),
`DECOMPOSITION_REQUIRED`, `OUT_OF_SCOPE`, `FAILED`. Internal workflow
state and user-facing classification are separate concepts; e.g. an
internal `HUMAN_HANDOFF` may classify as `DESIGN_NOT_APPROVED`.
Inspect with `review show result [session-id]`.

Core rules (full contracts in [`docs/V0_IMPLEMENTATION_SPEC.md`](docs/V0_IMPLEMENTATION_SPEC.md)):

- Human owns requirement semantics; repository owns current-state facts.
- Every gate question offers the Agent options **and** an explicit custom
  path — your own decision text is authoritative; unmatched prose is not.
- Codex raises structured issues; the orchestrator computes PASS mechanically.
- A blocking REQUIREMENT/FACT issue is checked against your ACTIVE decisions
  before any Human interruption or handoff (V0.2).
- Agents RECOMMEND generic correction actions; the deterministic orchestrator
  controls execution (V0.3). ABLATION is never the default fallback.
- Pi may mark an issue ADDRESSED; only Codex verifies RESOLVED.
- Budgets are hard limits (full revision 1, focused revision 1, ablation 1,
  2 human interruptions, 1 protocol repair).
- A human decision that changes the design basis bumps `task_revision`; the old
  proposal goes to `history/` marked STALE and the session redesigns.

## Roadmap

```text
V0    Fixed Agent Workflow
V0.1  Runtime Progress Visibility / Session Presentation
V0.2  Human Decision & Convergence
V0.3  Convergence Quality
V0.5  Role-Based Agent Assignment
V0.7  Multi Reviewer
V1    Capability-Based Agent Routing
```

V0.3 was promoted from the telemetry slot after two real 20260914 sessions
both ended in ambiguous `HUMAN_HANDOFF`: a composite task that should never
have entered a single session, and a bounded task whose settled-authority
engineering blocker burned the whole correction ladder. V0.3 adds the Scope
Guard, the Terminal Result Contract, generic correction actions (incl.
Focused Revision), the Review Convergence Contract and Human Gate batching;
telemetry collection ships as part of it. See
[`docs/V0_3_CONVERGENCE_QUALITY_DESIGN.md`](docs/V0_3_CONVERGENCE_QUALITY_DESIGN.md)
and [`docs/V0_3_IMPLEMENTATION_AUDIT.md`](docs/V0_3_IMPLEMENTATION_AUDIT.md).

## Session state

Everything lands under the target repository:

```text
<repo>/.review/<session-id>/
├── input.md, discovery.md, scope-assessment.md (V0.3), investigation.md
├── task.md + task.json          # Change Contract
├── proposal.md + proposal.json  # current design
├── change-map.json, issues.json, decisions.json
├── acceptance-coverage.json     # V0.3: criteria recorded at initial review
├── human-gate.json + human-gate.md   # gate truth (current/history agree)
├── state.json                   # authoritative phase/budget state
├── ablation.md, focused-revision.md (V0.3), final.md
├── session-result.md + telemetry.json  # V0.3 terminal result + metrics
├── handoff.md                   # written on terminal boundaries
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
revision = 1              # FULL_REVISION budget
focused_revision = 1      # FOCUSED_REVISION budget (V0.3)
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
