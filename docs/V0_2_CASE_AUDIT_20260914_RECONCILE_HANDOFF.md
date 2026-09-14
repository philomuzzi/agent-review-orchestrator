# V0.2 案例复盘：对账 Java 化会话止步 HUMAN_HANDOFF（20260914-094512-84fb）

**范围**：真实业务会话 `20260914-094512-84fb`（目标仓库 `C:\DEV\shopify_api`）的执行还原、止步 HUMAN_HANDOFF 的根因链、人工体验问题（含请求方直接反馈），以及 V0.2 机制在真实会话中的表现验证。
**性质**：事后审计（postmortem），不改变已终态的会话；发现的问题作为 V0.3/V0.5 后续修复候选。

---

## 1. 任务背景与案例概览

请求方要为 Shopify 订单同步链路建 Java 对账工具：直连 StarRocks 宽表与 Shopify ordersCount 双源计数，支持全量/指定店铺、全史（开店→cutoff）统计、CSV/通知输出、XXL-Job 部署。请求同时规定了时间语义：**"输入时间支持utc格式，不传Z就是香港机器，为utc+8"**——此句与后文 P3 直接相关。

| 项 | 值 |
|---|---|
| Session | `20260914-094512-84fb`（created_at `2026-09-14T01:45:12Z`，本地 09:45） |
| 请求 | 完善 Shopify–StarRocks 对账设计，Java 实现 + 直连 + XXL-Job 部署 + 全量/指定店铺 + 输出对账结果 |
| 任务标题 | Shopify–StarRocks 两源对账 Java 化设计与 XXL-Job 部署（DISCOVER 产出） |
| 任务类型 | CHANGE（kind_explicit=false） |
| 结局 | **HUMAN_HANDOFF（终态）**，reason: `Human interruption budget exhausted (2/2); unresolved decisions: REQU-61b6bc9b, REQU-b0e45426, REQU-e7c99ebc` |
| 预算终态 | revision **0/1**、ablation **0/1**（均未动用），human_interruptions **2/2**，protocol_retries 1/1 |
| task_revision | 3（HG001 三决策 + HG002 一决策，两次自增） |
| 真实 agent | pi（discover 213.8s / design 301.0s / human_authority_check 304.6s）、codex（initial_review 475.1s）；raw/ 存档 4 份 jsonl（约 15MB） |
| 运行代码 | 本仓库 HEAD `c43e3ce`（V0.2-RC3）。按会话日期与 V0.2 特征事件（ISSUE_NEED_HUMAN / 权威判定 / HANDOFF_WRITTEN）推断；state.json 不记录代码版本（见 P7 建议） |
| 总耗时 | 26 分 09 秒（09:45:12–10:11:21），其中人工实际参与约 **3.5 分钟** |

## 2. 执行时间线（本地时间）

| 时间 | 阶段/事件 | 说明 |
|---|---|---|
| 09:45:12 | SESSION_CREATED | 能力探测：pi 3.7s；codex 58.7s |
| 09:46–09:49 | DISCOVER（pi，213.8s） | 15 组件、任务标题、kind=CHANGE |
| 09:49:49 | INTAKE rev1 → **HG001 提问**（3 问） | SCOP/FACT/TRAD 各一；SCOP-87f46fd7（载体选型）被 deferred；打断预算 1/2 |
| 09:51:50 | HG001 首轮答案校验 **PARTIAL** | 2 条未命中（含用户反问，见 P4）；TRAD "3" 命中 |
| 09:52:37 | HG001 二轮补答 **COMPLETE** | D001 csv_and_notify / D002 user_direct_creds / D003 single_then_split；task_revision 1→2 |
| 09:52:37 | INTAKE rev2 → **HG002 提问**（deferred 那 1 问） | 距 HG001 关闭 **同一秒**；打断预算 2/2 |
| 09:53:20 | HG002 回答（43 秒） | D004 demo_first；task_revision 2→3 |
| 09:53–09:58 | DESIGN（pi，301.0s） | proposal 基于 task_revision 3 |
| 09:58–10:06 | INITIAL_REVIEW（codex，475.1s） | 11 issue：R001–R009 BLOCKING（5 DESIGN + 4 REQUIREMENT）+ R010/R011 非阻塞 |
| 10:06:17 | PASS=false；4 条 REQUIREMENT 阻塞翻 NEED_HUMAN | `ISSUE_NEED_HUMAN` ×4（审计事件已补，PROD-001 P2 修复实证） |
| 10:06–10:11 | Human Authority Check（pi，304.6s） | attempt 1 输出违反 `HumanAuthorityCheckResult` schema（281s 处 PROTOCOL_RETRY），attempt 2 成功 |
| 10:11:21 | 判定 3 问 NEEDS_NEW_HUMAN_DECISION + 1 deferred → **预算已 2/2 → SESSION_HUMAN_HANDOFF** | handoff.md 落盘（HANDOFF_WRITTEN），终态不可原地恢复 |

HG001/HG002 决策内容（decisions.json，全部 ACTIVE）：

| 决策 | 问题 | 选择 |
|---|---|---|
| D001 SCOP-79259163 | 对账结果输出载体 | csv_and_notify（CSV + 钉钉汇总播报） |
| D002 FACT-2b52f4fa | StarRocks 直连信息与表结构来源 | user_direct_creds（选项 impact 明示"表口径/去重键/时区需自行核对"——与后文 R002 相关） |
| D003 TRAD-b99cb776 | 全史订单量 Shopify 侧取数 | single_then_split（单查 EXACT，INEXACT 降级按月） |
| D004 SCOP-87f46fd7 | Java 实现载体 | demo_first（java-demo 先行，XXL-Job 出迁移文档） |

## 3. 评审结果与权威判定路由

Codex 初审质量高：9 条阻塞均有 file:line / 既有文档证据（如 R001 引 `docs/review-evidence/.../summary.json:55-64` 的 ordersCount 边界反例，R008 引 java-demo 具体构造函数行号，R004 直接引用请求原文）。按 V0.2 路由：

```text
_need_human_ids → R002/R004/R006/R007（BLOCKING + REQUIREMENT + OPEN）翻转 NEED_HUMAN
→ ISSUE_HUMAN_AUTHORITY_CHECK_STARTED（4 issues × 4 ACTIVE 决策）
→ Pi 权威判定（304.6s，含 1 次协议重试）：
    R002 → NEEDS_NEW_HUMAN_DECISION（REQU-61b6bc9b，StarRocks 口径无法证明时处置）
    R004 → NEEDS_NEW_HUMAN_DECISION（REQU-b0e45426，无后缀时区的解析与月界时区）
    R006 → NEEDS_NEW_HUMAN_DECISION（REQU-e7c99ebc，死人开关本轮落地方式）
    R007 → NEEDS_NEW_HUMAN_DECISION（REQU-dcdd4ce9，凭证注入通道）——被 deferred
→ 剩余人审预算 0 ⇒ 收敛门不可开 ⇒ SESSION_HUMAN_HANDOFF（终态）
```

**根因一句话**：deferred 的载体问题被拆成 HG001 关闭同一秒的 HG002，把 2/2 打断预算在"需求澄清"上烧光；评审期权威判定产出 4 个合格决策候选（V0.2 收敛机制本身工作正常）却无预算开门，5 条 DESIGN 阻塞（R001/R003/R005/R008/R009，REVISION 可修）连同 revision/ablation 预算（0/1、0/1）一并陪葬。

## 4. 审计发现（遇到的问题）

### P1（高）连环门烧光打断预算——本 case 直接根因 ⭐

- SCOP-87f46fd7 在 INTAKE rev1 被 deferred，rev2 立刻作为 HG002 开门（HG001 关闭后 **0 秒**），用户 43 秒答完。该问题与其余三问相互独立，完全可以并入 HG001 同批提问。
- 若合并提问，预算消耗 1/2，评审后 4 个 NEEDS_NEW_HUMAN_DECISION 至少还能开一道收敛门，会话大概率收敛而非终态。
- 打断预算按"门数"而非"人工会话窗口"计费，放大了拆分成本：同一人工在场时段内的连续两门，对人的打断体验是一次，对预算是两次。

### P2（高）"对方案有疑惑"时既问不出也答不上——请求方直接反馈 ⭐

请求方原话（复盘时）："**对于方案有疑惑，给出的答复现在的做法不太让人满意**"。对应两条机制性缺陷：

1. **HG001 内的反问被静默丢弃**（详见 P4）：用户对选项有疑惑反问"这个文件怎么读取出来呢？"，系统只记为 unmatched 等待重答，无任何回应通道。
2. **评审后真正需要人的问题因预算耗尽直接终态**：26 分钟里最贵的产出（proposal + 11 条带证据的评审意见）之后，用户得到的"答复"是一份 handoff.md 和"本会话不可原地恢复、请开新会话重述结论"。用户此刻对方案有疑惑、有决策意愿，却被架构推出门外。HUMAN_HANDOFF 会话不允许带答案 resume（`resume_phase` 恒为 null），交互闭环在人的参与意愿最高点断裂。

### P3（高）权威判定未把"请求原文已有答案"从决策候选中剥离

- R004 的升级问题（REQU-b0e45426）三个选项中，`reuse_window_tz`（当前提案做法）直接违反请求原文"不传Z就是香港机器，为utc+8"；即**解析规则其实已被请求文本裁决，不需要人再答**。真正开放的只剩"对账月界是否也强制香港时区"（fixed_utc8 vs fixed_utc8_strict）。
- 权威判定已拿到请求原文（issue evidence 里引用了"用户要求"），但没有做"候选问题 → 请求原文/ACTIVE 决策已覆盖部分"的拆分：把已覆盖部分判为"设计违反已定需求，打回 REVISION 修正"，只把残余真空留给收敛门。这与 V0.2 的 covered_by_decisions 检查同构，缺的是 **covered_by_request** 维度。
- 类似地，R002 的口径缺口在 D002 选项 impact（"表口径/去重键/时区需自行与大数据组核对"）里已有预警，intake 期未深挖，最终以最贵的形式（终态交接）回收。

### P4（中）人审门没有"人对选项的疑惑"的表达与回应通道

- HG001 首轮答案原文：SCOP 答"1和3方案，这个文件怎么读取出来呢？"、FACT 答"1，提供了仅读取权限账号"——两条均 unmatched，触发 PARTIAL 重答（多花 47 秒）。
- "1和3"是多选冲突（本协议单选），"这个文件怎么读取出来呢？"是对选项机理的真实疑问。两者都被简化为"未命中，请重答"。协议既不容纳对选项的澄清问答，也不在 unmatched 反馈中回显"你输入了什么、为何未命中"。
- RC3 的别名空间（数字/键/标签）工作正常（HG002 的"1"正确解析），但答案语义模型里没有"提问"这个动作。

### P5（中）权威判定协议重试整轮重跑（281s 浪费）

- attempt 1 在 281 秒后输出不符合 `HumanAuthorityCheckResult` schema，attempt 2 从头再来，总耗时 304.6s。Pi 侧长输出/格式漂移在 revise/ablate 已知复发（V0.1-RC2、V0.2-RC2 各有记录），本 case 在新调用点 human_authority_check 再次出现。流式或分段校验可把浪费从"整轮"降到"尾部"。

### P6（低）deferred 决策候选的选项包未进 handoff.md

- REQU-dcdd4ce9（R007 凭证注入，推荐 secrets_env_only）的完整候选（类别/why_human/3 选项/影响/推荐）只存在于 raw jsonl 与权威判定结果里；handoff.md 的 "What the Human needs to decide" 列出了 R007，但 "Suggested Options" 只渲染了 3 问。读交接文档的人看不到 R007 的候选项与推荐，续作会话要重新翻 raw。
- handoff.md 是"既有真相的重组"（V0.2 经验 10.2.8），但重组漏了 deferred 批次。

### P7（低）可观测性残留

- state.json 不记录运行代码版本（HEAD/commit），事后审计只能按事件特征推断（本报告"运行代码"一行即受此限）。
- codex 能力探测 58.7s（pi 3.7s），同一环境内无缓存；PROD-001 案例亦为 64.3s，属稳定开销。

## 5. 表现良好的部分（对既有修复的实证 + 本次亮点）

1. **V0.2 收敛机制在真实会话中端到端工作**：NEED_HUMAN 翻转发出审计事件（PROD-001 P2 修复实证）、权威判定产出结构化决策候选（类别 + why_human + 选项 + 影响 + 推荐 + source_issue_ids，B203 溯源要求全部满足）、handoff.md 完整落盘（PROD-001 P5 修复实证，含 Blocking Issues 全文与相关决策索引）。
2. **有效答案语义修复实证（PROD-001 P4）**：HG001 两轮答案中历史 unmatched 不再拖累验证——首轮 PARTIAL、补答后 COMPLETE，与 V0.2 "最新有效答案覆盖"设计一致。
3. **门答案别名解析（RC3 B301）真实可用**：HG001 的 "3"、"1"、HG002 的 "1" 三种数字形态全部正确解析命中；"1和3方案"（多义）被 fail-closed 拒绝而不是 first-match-wins。
4. **评审质量高且证据可溯**：codex 475s 产出 9 条阻塞全部带 file:line 或既有证据文件引用；R004 抓住了设计对请求明示要求的违反（时区），R001 抓住了 ordersCount 半开边界反例——两源对账任务最容易翻车的口径问题被初审拦住，说明"设计→评审"的分工在真问题上是有效的。
5. **全程无崩溃、无丢工作**：26 分钟 5 次真实 agent 调用 + 1 次协议重试 + 2 道门，产物链（events/issues/decisions/human-gate/proposal/handoff）完整互恰，事后可逐秒还原（本报告即证据）。
6. **人工杠杆高**：人工实际参与约 3.5 分钟（两道门作答），换取了调研、契约、提案与 11 条评审问题。

## 6. 改进建议（按优先级）

1. **门合并与打断预算会计（P1/P2）**：
   - INTAKE 聚合候选时，独立问题一律同批提问；deferred 仅保留给"依赖本轮答案才能表述"的问题，并在开门前检查依赖是否真的成立。
   - 预算计费从"每门一次"改为"每人工会话窗口一次"（如门关闭后 N 分钟内开下一门不计新打断），或至少为评审后收敛门预留 1 次（`max_human_interruptions ≥ intake 期望门数 + 1`）。
2. **HUMAN_HANDOFF 可续跑（P2）**：权威判定产出的决策候选包已持久化，允许 `review resume` 对 handoff 会话开门收答（复用收敛门路径），而不是强制"开新会话重述事实"。`resume_phase` 字段已存在，仅未启用。
3. **covered_by_request 判定（P3）**：权威判定输入加入请求原文与 ACTIVE 决策全文；候选问题先做"请求文本已裁决部分"的剥离——已裁决部分按"设计违反既定需求"回 REVISION，只把真空部分升级为收敛门。
4. **人审门的澄清通道（P4）**：unmatched 反馈回显原始输入与未命中原因；自由文本含问句时进入 QUESTION_ONLY 澄清应答（编排器或门 UI 层回应，不落决策）；"1和3"类多选冲突给出明确报错而非静默 PARTIAL。
5. **handoff.md 渲染全部 NEED_HUMAN 候选（P6）**：含 deferred 批次的选项与推荐。
6. **权威判定流式/尾部校验（P5）**：降低 schema 违规的整轮重跑成本；统计各调用点截断/格式失败率归入 V0.3 遥测。
7. **小项（P7）**：state.json 记录运行 commit；同环境能力探测结果缓存。

## 7. 对本会话的人工结论（供续作会话引用）

续作请求建议直接写明以下结论（成为新会话事实，避免再次落入同族门）：

| 未决问题 | 建议结论（case 复盘视角，非定论） |
|---|---|
| REQU-61b6bc9b（R002 StarRocks 口径无法证明时） | fail_closed：拒绝比较，不产出数量结论 |
| REQU-b0e45426（R004 无后缀时区） | fixed_utc8_strict：解析固定 UTC+8（请求原文已裁决），对账月界强制 Asia/Hong_Kong |
| REQU-e7c99ebc（R006 死人开关落地） | migration_doc_todo：撤回 handleFail=死人开关的说法，独立缺报检查写入迁移文档 |
| REQU-dcdd4ce9（R007 凭证注入，handoff.md 未渲染） | secrets_env_only：password/webhook/secret 走环境变量，非敏感项留配置 |

同时携带：R001/R003/R005/R008/R009 五条 DESIGN 阻塞应进入 REVISION（预算 0/1 未动用），新会话可直接要求按 issues.json 验收标准改稿。

---

## 附录 A：证据文件索引

| 内容 | 路径（`C:\DEV\shopify_api\.review\20260914-094512-84fb\`） |
|---|---|
| 终态与预算 | `state.json`（handoff_reason、budgets：revision 0/1、ablation 0/1、interruptions 2/2） |
| 全量事件轨迹 | `events.jsonl`（HG001→HG002 同秒接力、PROTOCOL_RETRY、SESSION_HUMAN_HANDOFF 均可见） |
| 评审问题 | `issues.json`（R001–R011；R002/R004/R006/R007 NEED_HUMAN） |
| 门与答案 | `human-gate.json`（含 HG001 首轮 unmatched 反问原文）、`decisions.json`（D001–D004） |
| 交接包 | `handoff.md`（Suggested Options 仅 3 问，REQU-dcdd4ce9 缺失即 P6 证据） |
| 契约与设计 | `task.json`（rev3）、`proposal.json`/`proposal.md`、`change-map.json`、`discovery.md` |
| agent 原始 IO | `raw/pi-discover.jsonl`、`raw/pi-design.jsonl`、`raw/codex-initial_review.jsonl`、`raw/pi-human_authority_check.jsonl`（尾部含 R007 完整决策候选） |
