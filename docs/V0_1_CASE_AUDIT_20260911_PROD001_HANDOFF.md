# V0.1 案例复盘：PROD-001 会话止步 HUMAN_HANDOFF（20260911-112256-4409）

**范围**：真实业务会话 `20260911-112256-4409`（目标仓库 `C:\DEV\shopify_api`）的执行流程还原、止步 HUMAN_HANDOFF 的根因链，以及对 review 阶段（INITIAL_REVIEW → 路由）过程的潜在问题审计。
**性质**：事后审计（postmortem），不改变已终态的会话；发现的问题作为 V0.1 后续修复候选。

---

## 1. 案例概览

| 项 | 值 |
|---|---|
| Session | `20260911-112256-4409`（created_at `2026-09-11T03:22:56Z`，本地 11:22） |
| 请求 | 为 PROD-001 问题定位根因，并设计修复方案，检查增量和兜底是否有类似问题 |
| 任务标题 | PROD-001全量DONE店残留PENDING根因与修复方案（DISCOVER 产出） |
| 任务类型 | CHANGE（kind_explicit=false，DISCOVER 判定） |
| 结局 | **HUMAN_HANDOFF（exit 10）**，reason: `issues requiring human authority (no decision packet derivable): R001` |
| 预算终态 | revision 0/1，ablation 0/1，human_interruptions 1/2，protocol_retries 0/1 |
| task_revision | 2（HG001 三决策应用后自增） |
| 真实 agent | pi（discover 403.5s / design 283.8s）、codex（initial_review 361.8s）；raw/ 存档 3 份 jsonl（约 12MB） |
| 运行代码 | HEAD `182c04f`（V0.1-RC3），venv editable 安装，与仓库工作树一致（pyc 源戳校验通过） |

## 2. 执行流程时间线

| 本地时间 | 阶段/事件 | 说明 |
|---|---|---|
| 11:22:56 | SESSION_CREATED | 能力探测：pi 4.5s；codex 64.3s |
| 11:24–11:30 | DISCOVER（pi，403.5s） | 产出 discovery、12 个组件、任务标题、kind=CHANGE |
| 11:30:48 | INTAKE | Change Contract rev1；聚合出 3 个人审候选 |
| 11:30:49 | **HG001 创建 → WAITING_FOR_HUMAN** | SCOP / FACT / TRAD 三问，human_interruptions 1/2 |
| 11:30–11:38 | 人工作答（两轮 pass） | 第一轮 3 答 2 中（TRAD 答了自由文本问题），第二轮补答命中 |
| 11:38:08 | 门关闭 → 决策 D001–D003 | full_doc5 / verify_before / compat_ignore；`task_revision 1→2`；重跑 INTAKE（rev2） |
| 11:38–11:42 | DESIGN（pi，283.8s） | proposal 基于 task_revision 2；verification_plan 11 项（A01–A08 等） |
| 11:42–11:48 | INITIAL_REVIEW（codex，361.8s） | 产出 4 个 issue（R001–R004，3 BLOCKING） |
| 11:48:54 | PASS=false → **SESSION_HUMAN_HANDOFF** | R001 被翻转为 NEED_HUMAN，触发终态；exit 10 |

HG001 决策内容（decisions.json，全部 ACTIVE）：

| 决策 | 问题 | 选择 |
|---|---|---|
| D001 SCOP-25dfba92 | 修复范围档位 | **full_doc5**：按问题单§5 全量实施（阻止新增 + 在营查询精确匹配兼容 + **展示统计统一**） |
| D002 FACT-b39c5bbb | 上线前是否先核实残留 | verify_before（check SQL 留回执，验收 A08） |
| D003 TRAD-f5fa0997 | 历史『DONE 店+PENDING』行处置基调 | compat_ignore（保留原始行，精确匹配忽略，零写入） |

注：D001 选项标签明确包含"展示统计统一"，task.json scope 第 3 条即"展示/统计口径盘点（§5.4）"——该语义**已被人审决策纳入范围**。此事实与后文 P1 相关。

## 3. INITIAL_REVIEW 结果与路由

Codex 产出（issues.json，provenance=INITIAL_REVIEW，based_on_task_revision=2）：

| ID | 严重度 | 类别 | 最终状态 | 标题 |
|---|---|---|---|---|
| R001 | BLOCKING | **REQUIREMENT** | **NEED_HUMAN** | 遗漏现有全量日报，§5.4 与 A07 未覆盖 |
| R002 | BLOCKING | DESIGN | OPEN | 兜底和修复口径竟绕开门禁（与 compat_ignore 冲突） |
| R003 | BLOCKING | REGRESSION | OPEN | A06 未考虑非 initial 模式的查询谓词写入 |
| R004 | NON_BLOCKING | FACT | OPEN | （非阻塞事实类） |

PASS 计算 = false（3 个 OPEN BLOCKING）。随后 `route_after_failed_pass(allow_revision=True)`（`phases/review.py:133`）：

```text
_need_human_ids(o)                       # review.py:117
  → BLOCKING + (REQUIREMENT|FACT) + OPEN ⇒ 翻转为 NEED_HUMAN
  → 命中 R001（R004 是 FACT 但 NON_BLOCKING，不影响）
need_human 非空 ⇒ try_gate_for_need_human_issues(...)   # human_gate.py:374
  → handoff("issues requiring human authority (no decision packet derivable): R001")
  → phase/status = HUMAN_HANDOFF，exit 10（终态）
```

**根因一句话**：R001 被 Codex 归类为 BLOCKING+REQUIREMENT，按 V0 规则视作"需要人类权威"，而 V0 没有实现从 issue 反向构造决策包的收敛门（代码注释自认 "NEED_HUMAN issues require a CONVERGENCE Human Gate (M3)"），于是直接终态交接——REVISION（0/1）与 ABLATION（0/1）预算完全未动用，R002/R003 这两个本可进入 REVISION 的 DESIGN/REGRESSION 阻塞也一并被陪葬。

## 4. Review 过程潜在问题（审计发现）

### P1（高）REQUIREMENT/FACT 阻塞短路终态，且不与 ACTIVE 决策交叉检查 ⭐ 本 case 直接根因

- 路由顺序：`_need_human_ids` 在 REVISION 预算判断**之前**执行，单个 REQUIREMENT/FACT 阻塞即可终止会话，即使收敛预算全满、其余阻塞明显可由 REVISION 消化。
- 分类裁量决定工作流命运：R001 若被标为 DESIGN/REGRESSION（"proposal 未落实已定 scope"），本会话会走 REVISION；标为 REQUIREMENT 即终态。reviewer 的类别用词成了最大的单点分叉。
- **与既有决策的张力**：D001（full_doc5）的选项标签与 task scope 均已把"展示统计统一/§5.4"纳入范围。R001 主张的缺口更像"设计未覆盖已定需求"（实现缺口，REVISION 可修），而非"需求语义未定"（才需要人）。当前路由不查 decisions.json，无法区分这两种情形。
- 风险：Codex 只需一次偏严的分类（把实现缺口说成需求缺口），就废掉整个 26 分钟会话，且终态不可 resume。

### P2（中）OPEN→NEED_HUMAN 翻转无审计事件

- `_need_human_ids` 原地改 issue.status 并落盘，但不发 event。events.jsonl 里 PASS_COMPUTED（11:48:54）仍把 R001 记为 "OPEN BLOCKING issues: R001, R002, R003"，随后 handoff reason 却称 R001 为 NEED_HUMAN——审计轨迹口径断裂，事后排障（如本次）需读源码才能还原翻转时点。
- 建议：翻转时发 `ISSUE_NEED_HUMAN` 事件（含 issue_id 与理由）。

### P3（中）gate 持久化一致性：`gates[]` 历史冻结在创建态

本 case 实测证据（human-gate.json，mtime 11:38）：

```text
current : status=CLOSED, answers=4（3 matched + 1 unmatched）, answered_at=03:38:08Z  ← 真相
gates[0]: status=OPEN,   answers=[], answered_at=None                              ← 陈旧副本
```

- 根因：`create_gate` 在内存里把同一个 HumanGate 对象同时挂到 `GateLog.current` 与 `gates[]`，但 JSON 序列化/反序列化断裂共享引用；之后 reload 再 save，只有 `current` 被更新，`gates[]` 永远停留在创建时刻。已用最小脚本验证当前代码可复现"current 更新、gates[0] 不更新"的分裂（见附录 B）。
- 连带影响：`human-gate.md` 仅在 `create_gate` 时渲染一次（本 case mtime 停在 11:30），`review show gate` 展示的是**未作答版本**；门是否回答过只能翻 decisions.json/events。历史门（多门场景）在 `gates[]` 里全部是 OPEN/空，不可作为审计依据。

### P4（低）未命中答案累积导致验证结果永远 PARTIAL

- HG001 第一轮 TRAD 收到自由文本"是否可以重跑一轮进行修复？"（unmatched），第二轮补答命中。但 `validate_answers` 对 `gate.answers` 全量计算（4 条中 3 matched ⇒ PARTIAL），因此两轮日志都是 PARTIAL——即使所有问题已解决也不会出现 COMPLETE。
- 无工作流影响（推进条件是 `unresolved_questions()` 为空，不是 COMPLETE），但日志语义误导排障。

### P5（中）终态交接缺少持久化交接包

- HUMAN_HANDOFF 仅在 CLI 回显 reason + exit 10；没有等价 human-gate.md 的 `handoff.md`（人工下一步该决策什么、可选方案、相关证据链接）。用户必须自行翻 issues.json/proposal.md 还原"要我拍什么板"。
- 且 HUMAN_HANDOFF 为幂等终态：`review resume` 直接返回 10，不接受补充输入；唯一出路是带着人工结论**开新会话**（本 case 中 PROD-001 的日报口径决定即如此），前一会话的 discovery/proposal 只能人工搬运。

### P6（低）预算视角的语义偏差

- README 把 HUMAN_HANDOFF 描述为 "budget exhausted, unresolved fact, real trade-off"；本 case 实际是**评审分类触发的语义边界**，三类预算（revision/ablation/interruption）均未耗尽。对外呈现（status --list 只见 HUMAN_HANDOFF）无法区分"真耗尽"与"被短路"，不利于信任校准。

## 5. 改进建议（按优先级）

1. **M3 收敛门（对应 P1/P5）**：NEED_HUMAN issue 不再直接终态，而是由 Pi 从 issue 反向构造决策候选（类别 + 选项 + 推荐），在剩余人审预算内开收敛门；预算耗尽或无候选时才 handoff，并持久化 handoff.md（决策点 + 选项 + 证据引用）。
2. **ACTIVE 决策交叉检查（P1）**：`_need_human_ids` 翻转前核对 decisions.json——若 issue 声称的需求缺口已被某条 ACTIVE 决策覆盖，降级为 DESIGN 处理（走 REVISION），仅在语义真空时才 NEED_HUMAN。
3. **补审计事件（P2）**：`ISSUE_NEED_HUMAN` 事件；必要时 PASS_COMPUTED 与翻转合并为一次计算。
4. **gate 一致性修复（P3）**：save 时同步更新 `gates[]` 内对应条目（按 gate_id 回写），门关闭时重渲染 human-gate.md；或直接废弃 `gates[]` 冗余，以 append-only 事件为历史真相。
5. **验证语义（P4）**：`validate_answers` 按决策键取最新一条答案计算，未命中的历史答案不再拖累结果。

## 6. 对本会话的人工结论（供后续会话引用）

R001 提出的实际决策点：现有全量日报（DailySyncReportRenderer 链路）在 full_doc5 口径下如何统一展示统计（§5.4 / A07）。开新会话时建议在请求中直接给出该口径结论（例如"日报统计按精确匹配口径重算/或保持现状并注明历史分类"），避免再次落在 REQUIREMENT 阻塞上。

---

## 附录 A：证据文件索引

| 内容 | 路径（`C:\DEV\shopify_api\.review\20260911-112256-4409\`） |
|---|---|
| 终态与预算 | `state.json`（phase/status=HUMAN_HANDOFF, handoff_reason） |
| 全量事件轨迹 | `events.jsonl`（含心跳；关键事件见 §2） |
| 评审问题 | `issues.json`（R001–R004，R001 status=NEED_HUMAN） |
| 门与答案 | `human-gate.json`（current vs gates[0] 分裂证据）、`decisions.json`（D001–D003） |
| 契约与设计 | `task.json`（scope 第 3 条 §5.4）、`proposal.json`（verification_plan 11 项） |
| agent 原始 IO | `raw/pi-discover.jsonl`、`raw/pi-design.jsonl`、`raw/codex-initial_review.jsonl` |

## 附录 B：P3 复现要点（最小验证）

使用与线上一致的 HEAD（`182c04f`）+ aro-venv editable 安装：

```python
from agent_review.models import GateLog, HumanGate, GateQuestion, GateOption, GateAnswer, GateStatus
from agent_review.storage import StateStore
# 1) create 后 save → reload → 只改 current（模拟 run() 的 gate = gate_log.current）
#    再 save：磁盘上 current=CLOSED+answers，gates[0] 仍 OPEN+[] 
# 2) 同一进程内不 reload 直接改（create_gate 场景）：current 与 gates[0] 同步
# 结论：分裂仅在"load→mutate current→save"路径出现，与 human_gate.run() 的实际路径一致。
```

（另注：序列化本身（`model_dump_json` 往返）无丢失；问题纯粹是共享引用在持久层断裂。）
