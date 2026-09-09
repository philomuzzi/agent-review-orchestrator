# Agent Review Orchestrator V0 Implementation Spec

**Status:** V0 Design Frozen  
**Date:** 2026-09-09  
**Implementation:** Python CLI  
**Author Agent:** Pi  
**Reviewer Agent:** Codex

---

# 1. Purpose

Agent Review Orchestrator 是一个运行在本地代码仓库中的 Python CLI 工具。

它解决的问题是：

> 在已有项目开发过程中，当出现中小规模需求变更、功能补缺或问题修复时，由 Pi 自动调查项目并提出设计，由 Codex 独立评审，通过确定性的 Orchestrator 控制 Issue 生命周期、修订次数、消融和 Human Gate，最终形成一份可直接交给开发 Agent 执行的设计方案。

核心目标不是增加更多 Agent，而是减少：

- Pi / Codex 之间的人工切换；
- Proposal / Review 的人工搬运；
- Reviewer 每轮重新发散；
- Agent 无限制互相修改；
- 人类被大量低价值问题打断；
- 为一个中小方案进行无上限 Review。

最终用户体验应该接近：

```text
用户提出自然语言需求
        ↓
自动理解项目
        ↓
自动整理需求
        ↓
自动设计
        ↓
自动 Review / Revision
        ↓
必要时一次性 Human Gate
        ↓
自动收敛
        ↓
final.md
```

---

# 2. V0 Scope

## 2.1 支持

V0 面向**已有代码库**。

典型场景：

1. 开发中期需求变更；
2. 已有功能补缺；
3. 已有模块的小规模能力增强；
4. 测试过程中发现问题后的修复设计；
5. 已知问题的 Root Cause 分析与 Fix Design；
6. 相对独立、影响范围可控的工程变更。

例如：

```text
给同步任务增加暂停能力。

现有任务有分段能力，但失败后没有进度记录，
需要增加任务状态和恢复能力。

测试发现 DB 已更新但 Kafka 消息缺失，
定位原因并设计修复方案。
```

## 2.2 暂不支持

V0 不负责：

- 从 0 到 1 的产品需求探索；
- 新项目完整需求澄清；
- 新系统整体架构设计；
- 大规模重构；
- 自动代码实现；
- 自动 Git commit；
- 自动 Pull Request；
- 自动部署；
- 自动访问生产系统；
- 自动测试环境取证 MCP；
- 多 Reviewer；
- Reviewer 投票；
- 通用 Multi-Agent Framework。

V0 的终点是：

```text
final.md
```

不是：

```text
自动开发完成
```

---

# 3. Fundamental Principles

## 3.1 Human owns Requirement

Human 拥有 Requirement Authority。

Agent 可以：

- 整理用户口述需求；
- 提取约束；
- 发现缺口；
- 提出建议；
- 提供选择。

Agent 不可以：

- 偷偷修改需求；
- 自行改变业务语义；
- 为了让方案成立而扩大 Scope。

原则：

> Agent 可以修改 Solution，但不能擅自修改 Requirement。

## 3.2 Human provides intent, repository provides facts

用户只需要尽量自然地描述：

```text
我要改变什么。
为什么。
有什么明确不能改变。
```

项目当前怎么工作，应由 Pi 自己调查：

```text
代码
测试
配置
设计文档
AGENTS.md
项目规则
```

不要求用户提前填写完整 Requirement 表格。

## 3.3 Orchestrator must be deterministic

系统角色：

```text
Pi
= Author / Investigator

Codex
= Reviewer

Orchestrator
= State Machine

Human
= Requirement / Trade-off Authority
```

Orchestrator 不判断：

```text
Redis 好还是 MySQL 好。
```

Orchestrator 只判断：

```text
是否存在 OPEN BLOCKING ISSUE。
是否达到最大轮数。
是否应该进入 ABLATION。
是否存在 Human Decision。
```

## 3.4 Issue is state, Round is history

Review 系统的核心不是：

```text
Round 1
Round 2
Round 3
```

而是：

```text
R001
OPEN
↓
ADDRESSED
↓
RESOLVED
```

Round 仅用于审计。

Issue 才是收敛状态。

## 3.5 Agent internal state is never authoritative

Pi 和 Codex 的聊天 Session 不能作为唯一事实来源。

所有权威状态必须持久化到：

```text
.review/<session>/
```

因此：

- CLI 被关闭后可以恢复；
- Pi/Codex 进程消失不会丢状态；
- Agent 可以重新启动；
- 流程可以重放和审计。

---

# 4. CLI UX

安装：

```bash
pip install -e .
```

进入已有项目：

```bash
cd shopify-project
```

启动：

```bash
review "同步任务需要增加暂停能力，尽量最小改动，不要重构整个任务框架。"
```

默认：

```text
repository = current working directory
```

## 4.1 V0 Commands

### Start

```bash
review "<request>"
```

可选：

```bash
review --repo /path/to/project "<request>"
```

可选强制模式：

```bash
review --kind change "<request>"
review --kind problem "<request>"
```

默认由 DISCOVER 判断。

### Resume

```bash
review resume
```

继续当前仓库最近一个未完成 Session。

也支持：

```bash
review resume <session-id>
```

### Status

```bash
review status
```

输出示例：

```text
Session: 20260909-pause-sync
Phase: CLOSURE_REVIEW
Task revision: 1

Blocking:
  OPEN: 1
  RESOLVED: 2

Human interruptions:
  0 / 2

Revision:
  1 / 1

Ablation:
  0 / 1
```

### Show

```bash
review show
```

默认：

- DONE → 显示 final.md
- WAITING_FOR_HUMAN → 显示 human-gate.md
- 其他 → 显示当前状态摘要

允许：

```bash
review show final
review show gate
review show task
review show proposal
review show issues
```

---

# 5. High-Level Architecture

```text
                CLI
                 │
                 ↓
           Orchestrator
                 │
       ┌─────────┼─────────┐
       ↓         ↓         ↓
   StateStore  PiAdapter  CodexAdapter
       │         │         │
       ↓         ↓         ↓
 .review/      Pi RPC    Codex Exec
```

模块职责：

```text
CLI
负责用户交互。

Orchestrator
负责状态机。

StateStore
负责文件持久化。

PiAdapter
负责调用 Pi。

CodexAdapter
负责调用 Codex。

Renderer
把结构化数据渲染为 Markdown。

Models
定义所有 Schema。
```

---

# 6. Python Project Structure

```text
agent-review/
├── pyproject.toml
├── README.md
├── schemas/
│   └── codex-review.schema.json
│
├── src/
│   └── agent_review/
│       ├── __init__.py
│       ├── cli.py
│       ├── orchestrator.py
│       ├── state_machine.py
│       ├── models.py
│       ├── storage.py
│       ├── rendering.py
│       ├── config.py
│       │
│       ├── agents/
│       │   ├── base.py
│       │   ├── pi.py
│       │   └── codex.py
│       │
│       ├── phases/
│       │   ├── discover.py
│       │   ├── investigate.py
│       │   ├── intake.py
│       │   ├── design.py
│       │   ├── review.py
│       │   ├── revision.py
│       │   ├── ablation.py
│       │   ├── human_gate.py
│       │   └── finalize.py
│       │
│       └── prompts/
│           ├── discover.md
│           ├── investigate.md
│           ├── design.md
│           ├── revision.md
│           ├── ablation.md
│           ├── initial_review.md
│           └── closure_review.md
│
└── tests/
    ├── unit/
    ├── integration/
    └── fixtures/
```

推荐：

```text
Python >= 3.11
Typer
Pydantic v2
```

不需要数据库。

---

# 7. Repository Session Structure

每次执行生成：

```text
<repository>/
└── .review/
    └── 20260909-pause-sync/
        ├── input.md
        ├── discovery.md
        ├── investigation.md
        ├── task.md
        ├── proposal.md
        ├── change-map.json
        ├── issues.json
        ├── decisions.json
        ├── human-gate.json
        ├── human-gate.md
        ├── state.json
        ├── ablation.md
        ├── final.md
        ├── events.jsonl
        │
        ├── raw/
        │   ├── pi-discover.jsonl
        │   ├── pi-design.jsonl
        │   └── codex-review.jsonl
        │
        └── history/
            ├── task-r1.md
            ├── proposal-r1.md
            ├── review-r1.json
            └── proposal-r2.md
```

`.review/` 完全由 Orchestrator 写入。

Pi 和 Codex 不直接编辑这里的文件。

---

# 8. State Machine

Phase Enum：

```text
INIT

DISCOVER
INVESTIGATE
INTAKE

WAITING_FOR_HUMAN

DESIGN
INITIAL_REVIEW

REVISION
CLOSURE_REVIEW

ABLATION
FINAL_REVIEW

FINALIZE

DONE
HUMAN_HANDOFF
INTERRUPTED
FAILED
```

---

# 9. Main Flow

## Change Mode

```text
INIT
 ↓
DISCOVER
 ↓
INTAKE
 ↓
[Human Gate]
 ↓
DESIGN
 ↓
INITIAL_REVIEW
 ↓
 ├─ no blocking → FINALIZE
 │
 ├─ human → WAITING_FOR_HUMAN
 │
 └─ blocking
       ↓
    REVISION
       ↓
 CLOSURE_REVIEW
       ↓
 ├─ resolved → FINALIZE
 │
 ├─ human → WAITING_FOR_HUMAN
 │
 └─ unresolved
       ↓
    ABLATION
       ↓
  FINAL_REVIEW
       ↓
 PASS / HUMAN_HANDOFF
```

## Problem Mode

```text
INIT
 ↓
DISCOVER
 ↓
INVESTIGATE
 ↓
ROOT CAUSE SUPPORTED?
 ↓
no → FACT HUMAN GATE
 ↓
yes
 ↓
INTAKE
 ↓
DESIGN
 ↓
后续与 Change Mode 相同
```

---

# 10. DISCOVER Protocol

Pi 的第一项任务不是设计。

目标：

> 建立 Current State。

Pi 可使用：

```text
read
grep
find
ls
```

V0 默认禁止：

```text
write
edit
bash
powershell
```

限制应尽可能由进程级工具 allowlist 完成，而不是只写在 Prompt 中。

DISCOVER 输出：

```json
{
  "task_kind": "CHANGE",
  "current_state": "...",
  "relevant_components": [],
  "existing_constraints": [],
  "change_surface": [],
  "unknowns": [],
  "human_candidates": []
}
```

同时 Renderer 生成：

```text
discovery.md
```

---

# 11. Problem Investigation Protocol

仅 `task_kind=PROBLEM` 执行。

Pi 输出：

```json
{
  "evidence": [],
  "hypotheses": [],
  "root_cause": "...",
  "root_cause_status": "SUPPORTED",
  "causal_chain": [],
  "missing_evidence": [],
  "human_candidates": []
}
```

`root_cause_status` 仅允许：

```text
SUPPORTED
UNRESOLVED
```

不使用模型生成的 72%、85% 等虚假精确 Confidence。

`SUPPORTED` 必须同时具备：

- 明确证据；
- 可解释的因果链；
- 没有关键矛盾证据。

否则：

```text
UNRESOLVED
```

创建 FACT Human Candidate。

V0 不允许在 Root Cause 未支持的情况下直接设计修复方案。

---

# 12. INTAKE / Change Contract

Orchestrator 根据：

```text
用户原始输入
+
Discovery
+
Investigation（如有）
```

形成：

```text
task.md
```

结构：

```text
User Intent

Current Behavior

Desired Behavior

Must Preserve

Scope

Known Constraints

Assumptions

Confirmed Decisions

Open Questions

Out of Scope
```

---

# 13. Assumption Rule

未知不等于 Human Gate。

如果未知：

```text
不会改变主要设计方向
```

允许：

```text
ASSUMPTION
```

例如：

```text
本次只设计后端能力，不包含运营平台 UI。
```

Assumption 必须记录：

```text
value
reason
impact_if_wrong
```

如果 `impact_if_wrong` 会导致方案方向改变：

不能 Assumption。

必须 Human Gate。

---

# 14. Human Gate Candidate

Agent 不能直接暂停流程。

Agent 只能产生：

```json
{
  "decision_key": "pause_semantics",
  "category": "REQUIREMENT",
  "blocking": true,
  "question": "...",
  "why_human": "...",
  "options": [],
  "recommended_option": "A"
}
```

Orchestrator 决定是否创建 Human Gate。

---

# 15. Human Gate Categories

只允许：

```text
REQUIREMENT
FACT
TRADE_OFF
SCOPE
CONVERGENCE
```

典型触发：

### REQUIREMENT

行为语义需要 Human 定义。

### FACT

仓库无法确定、且会改变设计的事实。

### TRADE_OFF

存在多个技术正确方案，但选择依赖价值偏好。

### SCOPE

继续实现必须明显扩大原始范围。

### CONVERGENCE

自动流程已经耗尽预算。

---

# 16. Human Gate Suppression

以下内容禁止触发 Gate：

```text
命名偏好
局部代码组织
已有项目惯例可以推导的问题
不影响方向的小事实
Non-blocking Suggestion
Reviewer 单纯偏好其他架构
未来扩展优化
```

---

# 17. Decision Packet

最多一次提供：

```text
3 个 Blocking Decision
```

每个必须包括：

```text
Question

Why Human

Options

Impact

Recommendation（可为空）
```

Option 数：

```text
2～4
```

超过 4 个说明 Agent 尚未完成抽象。

---

# 18. Human Interaction

Human 可以回答：

```text
Q001 A
Q002 B
```

也可以：

```text
都按推荐。
```

或者自然语言：

```text
当前 segment 跑完再停，
暂停状态一定要落库，重启后也不能丢。
```

内部由 Human Gate Parser 规范化。

原则：

> Machine protocol structured, human interaction natural language.

---

# 19. “All Recommended” Rule

只有当全部 Pending Questions 都存在：

```text
recommended_option
```

才能接受：

```text
都按推荐
```

如果其中一个没有推荐：

只自动确认存在推荐的项目。

其余继续等待 Human。

---

# 20. Human Decision Validation

回答分为：

```text
COMPLETE
PARTIAL
AMBIGUOUS
QUESTION_ONLY
```

### COMPLETE

全部 Decision 已明确。

继续执行。

### PARTIAL

只保留未完成 Question。

不重新运行 Agent。

### AMBIGUOUS

只重新询问相关 Question。

### QUESTION_ONLY

Human 只是询问：

```text
为什么推荐 A？
```

Gate 保持 OPEN。

---

# 21. Decisions

`decisions.json` 是 append-only。

示例：

```json
{
  "decision_id": "D001",
  "gate_id": "HG001",
  "decision_key": "pause_semantics",
  "decision": "A",
  "normalized_value": "PAUSE_AFTER_SEGMENT",
  "source": "HUMAN",
  "original_response": "当前 segment 跑完再停",
  "task_revision_before": 1,
  "task_revision_after": 2,
  "status": "ACTIVE"
}
```

Decision 不允许原地修改。

用户改变主意时：

```text
旧 Decision → SUPERSEDED
新 Decision → ACTIVE
```

---

# 22. Task Revision

每份 Change Contract 有：

```text
task_revision
```

初始：

```text
1
```

任何改变设计基础的 Human Decision：

```text
task_revision += 1
```

Proposal 必须记录：

```json
{
  "based_on_task_revision": 2
}
```

如果：

```text
proposal.task_revision < task.task_revision
```

Proposal 自动：

```text
STALE
```

---

# 23. Design Invalidating Decision

以下 Decision 默认属于：

```text
DESIGN_INVALIDATING
```

如果改变：

- Requirement；
- Scope；
- 关键 Fact；
- Trade-off 方向。

处理：

```text
task_revision + 1

旧 proposal → history

旧 issues → SUPERSEDED / STALE

重新 DESIGN
```

V0 不尝试聪明地增量修补旧 Proposal。

原则：

> Design basis changed → redesign.

---

# 24. Pi Design Protocol

输入：

```text
task.md
discovery.md
investigation.md（如有）
repository
active decisions
```

目标：

> 输出满足当前 Change Contract 的最小可实施方案。

不是：

```text
最佳未来架构
```

也不是：

```text
顺便重构历史系统
```

Proposal 固定包含：

```text
Summary

Current Flow

Proposed Flow

Changes

Data Model Changes

Interface Changes

State / Lifecycle Changes

Failure Handling

Compatibility

Risks

Alternatives Considered

Verification Plan

Explicitly Unchanged
```

`Explicitly Unchanged` 必须存在。

---

# 25. Change Map

Pi 同时输出：

```json
{
  "affected_components": [],
  "data_changes": [],
  "api_changes": [],
  "config_changes": [],
  "behavior_changes": [],
  "unchanged_behaviors": []
}
```

生成：

```text
change-map.json
```

---

# 26. Issue Schema

核心结构：

```json
{
  "id": "R001",
  "category": "DESIGN",
  "severity": "BLOCKING",
  "status": "OPEN",
  "title": "...",
  "problem": "...",
  "evidence": [],
  "impact": "...",
  "acceptance": [],
  "introduced_round": 1,
  "provenance": "INITIAL_REVIEW",
  "based_on_task_revision": 1,
  "addressed_by": null,
  "resolution": null
}
```

---

# 27. Issue Category

允许：

```text
DESIGN
REQUIREMENT
FACT
REGRESSION
SUGGESTION
```

---

# 28. Severity

V0 仅：

```text
BLOCKING
NON_BLOCKING
```

不引入：

```text
Critical
High
Medium
Low
```

避免制造新的边界争议。

---

# 29. Issue Lifecycle

```text
OPEN
 ↓ Pi 修改
ADDRESSED
 ↓ Codex 验证
RESOLVED
```

另外：

```text
NEED_HUMAN
ACCEPTED_RISK
SUPERSEDED
```

Pi 没有：

```text
RESOLVE
```

Issue 的权限。

---

# 30. Blocking Acceptance

每个 BLOCKING Issue 必须包含：

```text
acceptance[]
```

Reviewer 不能只写：

```text
恢复机制不够完善。
```

必须明确：

```text
达到什么状态，该 Issue 就关闭。
```

---

# 31. Initial Codex Review

检查：

```text
Requirement Coverage

Correctness

Compatibility

Complexity

Failure Modes

Maintainability
```

BLOCKING 只能用于：

```text
需求无法满足

明显 Bug

数据正确性问题

严重兼容问题

明显不可接受工程风险
```

以下不得 Blocking：

```text
“我更喜欢另一种架构”

“以后扩展会更漂亮”

“可以抽象一个 Strategy”

“也许可以顺便重构”
```

---

# 32. Closure Review

第二轮以后 Codex 不再 Full Review。

只检查：

```text
R001 acceptance 是否满足？

R002 acceptance 是否满足？

本轮是否引入 Blocking Regression？

当前 Proposal 是否仍满足 task_revision？
```

原则：

> First review discovers issues. Later reviews close issues.

---

# 33. New Blocking Issue Rule

Initial Review 后只能新增：

```text
REGRESSION
MISSED_BLOCKER
```

`MISSED_BLOCKER` 必须包含：

```text
why_not_detected_initially
```

无法解释时自动降为：

```text
NON_BLOCKING
```

---

# 34. Revision Protocol

Pi 输入：

```text
当前 Proposal
+
OPEN BLOCKING Issues
+
Acceptance Criteria
```

Prompt 必须明确：

```text
只处理当前 Blocking Issues。

保持已经确认的设计不变。

不得主动扩大 Scope。

不得为了 Non-blocking Suggestion 修改方案。
```

Pi 输出：

```text
新的 proposal

issue_responses:
  R001 → ADDRESSED
```

---

# 35. PASS Calculation

Codex 不拥有 PASS 权限。

PASS 由 Orchestrator 机械计算：

```text
no OPEN BLOCKING
AND
no ADDRESSED BLOCKING
AND
no NEED_HUMAN
AND
no active human gate
AND
proposal.task_revision == task.task_revision
```

`NON_BLOCKING` 不影响 PASS。

---

# 36. Convergence Algorithm

默认：

```text
Initial Review
+
1 normal Revision
+
1 Ablation
```

正常目标：

```text
1～2 Review
```

最大：

```text
3 Review stages
```

---

# 37. Ablation Trigger

满足任一：

```text
同一 Blocking Issue
经过 Revision 后仍 OPEN
```

或者：

```text
Revision 后 Blocking 数量没有减少
```

进入：

```text
ABLATION
```

---

# 38. Ablation Protocol

Pi 不继续局部修补。

目标变成：

> 找到满足 Requirement 的最小充分方案。

允许：

```text
删除非必要能力

降低自动化程度

减少抽象

推迟未来能力

缩小实现面
```

输出：

```text
Variant A
Variant B
Variant C
```

每个包含：

```text
removed capability

requirement impact

complexity

risk
```

Codex 只评：

> 哪个是仍满足 Requirement 的最小充分方案？

---

# 39. Budgets

V0 默认：

```json
{
  "max_revision_rounds": 1,
  "max_ablation_rounds": 1,
  "max_human_interruptions": 2,
  "max_protocol_retries": 1
}
```

对应：

### Retry Budget

单次 Agent 调用发生技术 / Protocol 错误时允许有限重试。

### Convergence Budget

限制 Agent 间讨论次数。

### Human Interruption Budget

限制对用户的打扰次数。

---

# 40. Human Interruption Budget

正常：

```text
0
```

复杂：

```text
1
```

最大：

```text
2
```

即将创建第三次 Human Gate：

```text
HUMAN_HANDOFF
```

而不是继续询问。

---

# 41. REQUIREMENT_TOO_AMBIGUOUS

如果一次 Intake 产生：

```text
> 3 Blocking Human Decisions
```

不要展示十个问题。

只保留依赖最上游的 1～3 个。

进入：

```text
REQUIREMENT_TOO_AMBIGUOUS
```

Human 回答后重新：

```text
DISCOVER / INTAKE
```

让下游问题重新计算。

---

# 42. Pi Integration

Python V0 使用 Pi 的程序化非交互接口，例如：

```text
pi --mode rpc
```

通过 stdin/stdout JSONL 通信。

建议每一个 Phase 使用独立的短生命周期调用，不依赖 Pi 长期 Session。

权威 Context 来自 `.review/` 文件。

Pi 必须以只读工具 allowlist 运行，至少在 Discover / Design Review 阶段不得拥有源码写权限。

---

# 43. PiAdapter Contract

接口：

```python
class PiAdapter:

    def discover(...) -> DiscoveryResult:
        ...

    def investigate(...) -> InvestigationResult:
        ...

    def design(...) -> DesignResult:
        ...

    def revise(...) -> RevisionResult:
        ...

    def ablate(...) -> AblationResult:
        ...
```

每次调用：

```text
spawn
↓
send prompt
↓
collect events
↓
wait completion
↓
extract final assistant message
↓
parse structured result
↓
validate Pydantic model
```

---

# 44. Codex Integration

Reviewer 使用 Codex 的非交互执行入口，例如：

```text
codex exec
```

优先使用结构化输出 / JSONL / output schema 能力。

Codex 必须运行在：

```text
read-only reviewer mode
```

不能修改：

```text
source code
config
.review/
```

如果当前 Codex 版本无法提供安全的只读执行方式：

```text
fail closed
```

不允许退化为 unrestricted mode。

---

# 45. CodexAdapter Contract

```python
class CodexAdapter:

    def initial_review(...) -> ReviewResult:
        ...

    def closure_review(...) -> ReviewResult:
        ...

    def final_review(...) -> ReviewResult:
        ...
```

优先使用：

```text
structured output / output schema
```

如果 CLI 版本支持。

---

# 46. Capability Detection

第一次运行时检查：

```text
pi executable
codex executable
Pi RPC support
Pi tool allowlist support
Codex exec support
Codex JSON support
Codex read-only/sandbox capability
```

不满足必需能力：

```text
直接报错
```

不能偷偷换成：

```text
shell scraping
unrestricted execution
```

---

# 47. Agent Output Protocol

Agent 的最终回答必须是：

```text
single structured JSON object
```

Markdown 不由 Agent 直接写文件。

例如 Pi：

```json
{
  "proposal_markdown": "...",
  "change_map": {},
  "human_candidates": []
}
```

Codex：

```json
{
  "review_summary": "...",
  "issues": [],
  "human_candidates": []
}
```

Orchestrator：

```text
validate JSON
↓
write JSON
↓
render Markdown
```

---

# 48. Protocol Repair

如果 Agent 返回非法 JSON：

第一次：

```text
发送 protocol repair request
```

内容只能要求：

```text
重新按照 Schema 输出。
不要重新分析问题。
不要改变结论。
```

仍失败：

```text
FAILED
```

不允许无限 Prompt 修 JSON。

因此：

```text
max_protocol_retries = 1
```

---

# 49. File Ownership

只有：

```text
Orchestrator
```

写 `.review/`。

Pi / Codex：

```text
read repository
return structured response
```

Agent 不直接写：

```text
task.md
proposal.md
issues.json
state.json
final.md
```

避免文件写权限和角色边界混乱。

---

# 50. state.json

核心字段：

```json
{
  "session_id": "...",
  "repository": "...",
  "task_kind": "CHANGE",
  "phase": "CLOSURE_REVIEW",
  "task_revision": 1,
  "active_gate": null,
  "round": 2,
  "budgets": {
    "revision_used": 1,
    "ablation_used": 0,
    "human_interruptions_used": 0,
    "protocol_retries_used": 0
  },
  "status": "RUNNING"
}
```

每次 Phase Transition 后立即落盘。

---

# 51. Crash Recovery

原则：

> Persist before transition.

例如：

```text
REVISION completed
↓
proposal 写入成功
↓
issues 更新
↓
state.phase = CLOSURE_REVIEW
```

不能先修改 state 再写输出。

CLI 异常退出：

```text
review resume
```

从最后一个完整 Phase 恢复。

---

# 52. Ctrl+C

如果 Agent 正在运行：

1. 尝试 abort Agent；
2. 写：

```text
phase = INTERRUPTED
```

3. 保留当前 Session；
4. 用户之后：

```bash
review resume
```

继续。

不能删除 Session。

---

# 53. Technical Failure vs Human Handoff

必须区分：

### FAILED

工具级错误：

```text
Pi 无法启动
Codex 无法启动
协议连续解析失败
文件损坏
```

### HUMAN_HANDOFF

任务级正常退出：

```text
Convergence Budget exhausted
Human Interruption Budget exhausted
Requirement 仍过度模糊
事实无法获得
真实 Trade-off 无法自动解决
```

Human Handoff 不是系统失败。

---

# 54. Audit Log

`events.jsonl` append-only。

例如：

```json
{"event":"SESSION_CREATED"}
{"event":"DISCOVER_STARTED"}
{"event":"DISCOVER_COMPLETED"}
{"event":"HUMAN_GATE_CREATED"}
{"event":"DECISION_APPLIED"}
{"event":"DESIGN_COMPLETED"}
{"event":"ISSUE_CREATED","id":"R001"}
{"event":"ISSUE_RESOLVED","id":"R001"}
{"event":"SESSION_DONE"}
```

用于：

- Debug；
- 评估；
- 统计 Human Attention；
- 回放流程。

---

# 55. Raw Agent Output

所有 Agent 原始事件保存：

```text
raw/
```

但业务状态永远不直接从 Raw Event 恢复。

Raw 只用于：

```text
debug / audit
```

---

# 56. Finalization

PASS 后生成：

```text
final.md
```

必须包含：

```text
Change Goal

Current Behavior

Final Design

Affected Components

Explicitly Unchanged

Confirmed Human Decisions

Resolved Blocking Issues

Accepted Risks

Non-blocking Suggestions

Verification Plan

Implementation Notes
```

它必须可以脱离 Review 历史单独阅读。

---

# 57. final.md Contract

它应该达到：

> 一个新的开发 Agent 只读取 final.md + repository，就能理解此次变更并开始实现。

不要求它阅读：

```text
Round 1 review
Round 2 review
Ablation discussion
```

---

# 58. CLI Interactive Human Gate

如果 Terminal 支持交互：

```text
Human Decision Required

Q001 暂停时什么时候停止？

A 当前 segment 完成后停止 [recommended]
B 当前记录完成后停止
C 尽可能立即停止

>
```

用户输入后继续运行。

---

# 59. Non-interactive Human Gate

如果：

```text
stdin is not TTY
```

或者未来：

```text
--non-interactive
```

遇到 Human Gate：

1. 写 `human-gate.json`；
2. 写 `human-gate.md`；
3. Phase = `WAITING_FOR_HUMAN`；
4. CLI 退出。

之后：

```bash
review resume
```

继续。

---

# 60. Suggested Exit Codes

```text
0  DONE

10 HUMAN_HANDOFF

20 WAITING_FOR_HUMAN

30 FAILED

130 INTERRUPTED
```

---

# 61. Configuration

V0 配置只保留必要参数：

```toml
[pi]
binary = "pi"
model = ""

[codex]
binary = "codex"
model = ""

[budgets]
revision = 1
ablation = 1
human_interruptions = 2
protocol_retries = 1
```

用户没有明确配置 model：

```text
使用 Agent 自己当前默认配置
```

V0 不承担 Model Router。

---

# 62. Security Model

V0 原则：

> Review workflow itself must not mutate project code.

Pi：

```text
read-only tool allowlist
```

Codex：

```text
read-only sandbox
```

Orchestrator：

只允许写：

```text
.review/
```

不得修改：

```text
src/
config/
database
external systems
```

V0 不允许任何阿里云 MCP、数据库、Kafka、生产系统调用。

这些属于后续 Verification Layer。

---

# 63. Prompt Design Principle

所有 Prompt 分为：

```text
Role
Authority
Input
Task
Forbidden Actions
Output Schema
Stop Conditions
```

避免使用：

```text
“请仔细看看”
“尽量完善”
“继续优化”
```

这类无限发散指令。

---

# 64. Initial Review Prompt Constraint

Codex 必须被明确告知：

```text
你不是方案作者。

不要重写方案。

不要为了架构偏好创建 Blocking。

你需要建立有限 Issue Set。

每个 Blocking 必须具有 Acceptance Criteria。
```

---

# 65. Closure Review Prompt Constraint

```text
不要重新执行 Full Review。

只检查已有 Blocking Acceptance。

只允许新增 Regression / 真正 Missed Blocker。
```

---

# 66. Revision Prompt Constraint

```text
不要重新设计。

不要处理 Suggestion。

只解决指定 Blocking Issue。

保持其他已确认设计稳定。
```

---

# 67. Test Strategy

必须优先测试：

```text
State Machine
Human Gate
Issue Lifecycle
Budget
Crash Recovery
```

不要一开始依赖真实 Pi / Codex 做全部测试。

---

# 68. Fake Agent Adapters

测试目录必须实现：

```text
FakePiAdapter
FakeCodexAdapter
```

允许脚本化结果：

```text
Initial Review → R001 OPEN

Revision → R001 ADDRESSED

Closure → R001 RESOLVED
```

测试 Orchestrator 本身。

---

# 69. Required Unit Tests

至少覆盖：

1. 无 Issue 一轮 PASS；
2. 一个 Blocking → Revision → PASS；
3. Blocking 不下降 → Ablation；
4. Ablation 后 PASS；
5. Ablation 后仍失败 → HUMAN_HANDOFF；
6. Requirement Gate；
7. Partial Human Answer；
8. “都按推荐”；
9. 无 Recommendation 时不能自动选择；
10. Human Decision 导致 task revision；
11. stale proposal 自动重做；
12. Reviewer 第二轮违规新增 Blocking；
13. Human interruption 第三次 → HANDOFF；
14. Protocol invalid JSON → repair；
15. Protocol 第二次失败 → FAILED；
16. Ctrl+C → INTERRUPTED；
17. Resume 正确恢复；
18. Non-blocking Issue 不阻塞 PASS。

---

# 70. Integration Tests

使用真实小型 Fixture Repo。

准备三个案例：

### Case A

简单 Change。

目标：

```text
1 round PASS
```

### Case B

故意遗漏关键设计。

目标：

```text
Initial Review
→ Revision
→ Closure
→ PASS
```

### Case C

存在真实 Trade-off。

目标：

```text
Human Gate
→ Decision
→ Re-design
→ PASS
```

---

# 71. V0 Success Metrics

每个 Session 记录：

```text
Review rounds

Blocking issue count

Human interruptions

Ablation used

Final PASS / Handoff

Protocol failures

Total agent calls
```

后续重点观察：

```text
Human Attention Cost 是否下降？

原来人工 6 次切换的任务，
现在需要几次 Human Interruption？

最终开发是否因为设计错误返工？
```

---

# 72. Acceptance Criteria

V0 完成必须满足：

### CLI

```text
review "<request>"
review resume
review status
review show
```

全部工作。

### Change Flow

可以完成：

```text
Discover
→ Intake
→ Design
→ Review
→ Revision
→ Final
```

### Problem Flow

可以完成：

```text
Discover
→ Investigate
→ Root Cause
→ Design
```

### Human Gate

支持：

```text
结构化 Decision Packet
自然语言回答
Partial Answer
All Recommended
Resume
```

### Convergence

严格执行：

```text
1 Revision
1 Ablation
2 Human Interruptions
```

### Safety

Pi / Codex 无法修改项目源码。

### Recovery

CLI 中断后：

```text
review resume
```

能够继续。

### Final Artifact

成功后必须存在：

```text
.review/<session>/final.md
```

---

# 73. Implementation Order

建议严格按以下顺序开发。

## M0 — Skeleton

实现：

```text
CLI
Session directory
Pydantic models
StateStore
Fake adapters
```

## M1 — Deterministic State Machine

先完全不接真实 Agent。

用 Fake Adapter 跑通：

```text
Discover
Design
Review
Revision
PASS
```

## M2 — Issue Lifecycle + Budget

实现：

```text
OPEN
ADDRESSED
RESOLVED

Revision Budget
Ablation Trigger
PASS Calculation
```

## M3 — Human Gate

实现：

```text
Decision Packet
Answer Parser
Decision History
Task Revision
Resume
Human Interruption Budget
```

## M4 — Pi Adapter

接 Pi 程序化调用。

完成：

```text
Discover
Investigate
Design
Revision
Ablation
```

Pi 应作为短生命周期、无状态 Adapter；权威状态始终在 `.review/`。

## M5 — Codex Adapter

接 Codex 非交互调用。

完成：

```text
Initial Review
Closure Review
Final Review
```

优先使用 Codex 的 JSON / structured output 能力，并强制 Reviewer 运行于只读范围。

## M6 — Recovery + Real Integration Test

完成：

```text
Ctrl+C
resume
raw logging
events
status
show
```

使用真实小项目验证三个 Integration Cases。

---

# 74. Explicit Non-Goals for Implementation Agent

实现 V0 时禁止主动增加：

```text
Web UI

Desktop UI

HTTP Server

Database

Docker deployment

Cloud service

MCP

Git integration

Automatic code implementation

Automatic testing

Multiple reviewers

Agent supervisor

Plugin system

Complex workflow DSL

Generic multi-agent framework
```

如果发现这些能力“以后可能有用”：

记录：

```text
Future Work
```

不要实现。

---

# 75. Final Architectural Rule

整个 V0 最重要的设计原则：

```text
Human
负责意图、需求和真正 Trade-off

Pi
负责理解现状和提出方案

Codex
负责发现风险和验证关闭

Orchestrator
负责状态、权限、预算和收敛
```

Orchestrator 不应该逐渐变成第三个智能 Agent。

Agent 可以很聪明。

流程必须尽量简单、确定、可停止。

---

# 76. Definition of Done

当用户能够在一个已经开发一半的真实项目中执行：

```bash
review "这里需要增加一个暂停能力，尽量最小修改，不要重构整个任务框架。"
```

并在最多少量 Human Decision 后得到：

```text
.review/<session>/final.md
```

且该文档能够直接交给另一个开发 Agent 实施，同时整个过程不需要用户手工在 Pi / Codex 间复制方案和 Review 意见，则 Agent Review Orchestrator V0 达到完成标准。
