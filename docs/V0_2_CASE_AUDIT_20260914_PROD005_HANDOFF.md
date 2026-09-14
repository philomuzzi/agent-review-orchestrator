# V0.2 案例复盘：PROD-005 收敛预算耗尽会话止步 HUMAN_HANDOFF（20260914-165600-c454）

**范围**：真实业务会话 `20260914-165600-c454`（目标仓库 `C:\DEV\shopify_api`）的执行还原、止步 HUMAN_HANDOFF 的根因链（"为什么还是 handoff"的正式答复）、V0.2 收敛阶梯在真实会话中的首次全链路验证，以及审计发现。
**性质**：事后审计（postmortem），不改变已终态的会话；发现的问题作为 V0.3+ 后续修复候选。
**关联案例**：同日 `20260914-094512-84fb`（见 `V0_2_CASE_AUDIT_20260914_RECONCILE_HANDOFF.md`，下称 84fb）——两者互补覆盖了 V0.2 路由规约的两个失败分支（§8）。

---

## 1. 任务背景与案例概览

请求方要求为 PROD-005 设计解决方案：Shopify HTTP 200 响应中 `errors[].extensions.code=INTERNAL_SERVER_ERROR` 被 ErrorClassifier 归入 SEMANTIC，不进入 TRANSIENT 有限重试，导致该店当轮全量中断、增量水位不动、兜底跨日不自动补回。

| 项 | 值 |
|---|---|
| Session | `20260914-165600-c454`（created_at `2026-09-14T08:56:00Z`，本地 16:56） |
| 请求 | 为PROD-005问题设计解决方案 |
| 任务标题 | Shopify内部错误纳入瞬时重试的修复设计（DISCOVER 产出） |
| 任务类型 | CHANGE（kind_explicit=false） |
| 结局 | **HUMAN_HANDOFF（终态）**，reason: `convergence budget exhausted: blocking issues remain unresolved after revision (1/1) and ablation (1/1)` |
| 预算终态 | revision **1/1**、ablation **1/1**（阶梯全部耗尽），human_interruptions **2/2**（均在 intake），protocol_retries **0/1**（首次全零） |
| task_revision | 3（HG001 三决策 + HG002 一决策，两次自增） |
| 真实 agent | 11 次调用共 **2338.9s（≈39.0 分钟）**：pi（discover 241.9s / design 231.3s / authority×2 113.8s+98.9s / revise 380.8s / ablate 508.5s）、codex（initial 325.4s / closure 157.3s / final 221.9s）；raw/ 存档 8 份 jsonl |
| 运行代码 | 本仓库 HEAD `c43e3ce`（V0.2-RC3）。按会话日期与 V0.2 特征事件（ISSUE_COVERED_BY_DECISION / ABLATION_TRIGGERED / HANDOFF_WRITTEN）推断；state.json 不记录代码版本（见 P6） |
| 总耗时 | 46 分 02 秒（本地 16:56:00–17:42:02），人工实际输入 4 次"1"（秒级），HG001 人工响应延迟 6m26s（含不在场时间） |

**为什么还是 handoff（一句话）**：会话在单个持续演化的验证计划 blocker（R001）上烧穿整条修正阶梯（rev 1/1 + abl 1/1），终审又新发现一个 blocker（R004），而两次 Human Authority Check 均判定语义已被 ACTIVE 决策覆盖（无新决策可导出 → 不开收敛门 → 回流修正阶梯），预算耗尽后按设计 fail-closed 落 HUMAN_HANDOFF。这是 V0.2 规约三个路由分支中"预算耗尽 → HUMAN_HANDOFF"分支的**设计内**终态，不是 V0.1 式的提前夭折。

## 2. 执行时间线（本地时间）

| 时间 | 阶段/事件 | 说明 |
|---|---|---|
| 16:56:00 | SESSION_CREATED | 能力探测：pi 3.7s；codex 55.4s（第三次出现 ≈1min，见 P6） |
| 16:56:59 | DISCOVER（pi，241.9s） | 15 组件、任务标题、kind=CHANGE |
| 17:01:01 | INTAKE rev1 → **HG001 提问**（3 问） | TRAD 重试预算 / SCOP 语义修复范围 / SCOP 六店处置；REQU-ff2b261d（混合错误优先级）被 **deferred**；打断预算 1/2 |
| 17:07:27 | HG001 答案校验 COMPLETE | 人工响应延迟 6m26s；D001 reuse_transient / D002 fix_together / D003 code_then_ops（全部 = 推荐）；task_revision 1→2 |
| 17:07:27 | INTAKE rev2 → **HG002 同秒开门**（deferred 那 1 问） | HG001 关闭后 **0 秒**；打断预算 2/2（84fb P1 同族复发，见 P1） |
| 17:08:03 | HG002 回答（36 秒） | D004 transient_wins（= 推荐）；task_revision 2→3 |
| 17:08:03 | DESIGN（pi，231.3s） | proposal 基于 task_revision 3 |
| 17:11:55 | INITIAL_REVIEW round1（codex，325.4s） | 2 issue：R001 BLOCKING REQUIREMENT + R002 BLOCKING REGRESSION；PASS=false |
| 17:17:20 | R001 翻 NEED_HUMAN → **权威判定 #1**（pi，113.8s） | `ISSUE_COVERED_BY_DECISION(R001, [D003])` → 判为方案缺口，回流修正阶梯（不开门、不问人） |
| 17:19:14 | REVISION（pi，380.8s） | R001/R002 均标记 ADDRESSED；revision 1/1 |
| 17:25:35 | CLOSURE_REVIEW round2（codex，157.3s） | R002 RESOLVED；R001 remaining → `ABLATION_TRIGGERED` |
| 17:28:12 | ABLATION（pi，508.5s） | 删 6 项（均带等价性论证）；R001 再 ADDRESSED；ablation 1/1 |
| 17:36:41 | FINAL_REVIEW round3（codex，221.9s） | `satisfies_requirement=false, passed=false`；R001 仍 ADDRESSED（追加新 note）；**新增 R003（非阻塞）+ R004（BLOCKING）** |
| 17:40:23 | R004 翻 NEED_HUMAN → **权威判定 #2**（pi，98.9s） | `ISSUE_COVERED_BY_DECISION(R004, [D001, D004])` → 回流，但 rev/abl 预算均尽 |
| 17:42:02 | **SESSION_HUMAN_HANDOFF** | handoff.md 落盘（HANDOFF_WRITTEN），终态不可原地恢复 |

HG001/HG002 决策内容（decisions.json，全部 ACTIVE，推荐接受率 4/4）：

| 决策 | 问题 | 选择 |
|---|---|---|
| D001 TRAD-4ae541f3 | INTERNAL_SERVER_ERROR 的重试预算如何设定 | reuse_transient（复用现有 TRANSIENT 通道，5 次/全抖动/轮窗预算） |
| D002 SCOP-7e8fbf27 | SemanticQueryException 终态分类失真是否随本单一并修复 | fix_together |
| D003 SCOP-161d865c | 六家存量失败店铺的人工续跑处置是否纳入本次交付 | code_then_ops（先交付代码，处置/发布证据后置运维） |
| D004 REQU-ff2b261d | 混合错误（INTERNAL_SERVER_ERROR + ACCESS_DENIED）且 data 可用时优先级 | transient_wins（内部错误存在即整体按可重试处理，data 不照收） |

## 3. 评审结果与权威判定路由（收敛阶梯全链路）

```text
INITIAL_REVIEW: R001(BLOCKING/REQUIREMENT) + R002(BLOCKING/REGRESSION)，PASS=false
→ _need_human_ids 翻 R001（R002 非 REQUIREMENT/FACT，直接走阶梯）
→ 权威判定 #1: R001 covered_by [D003]（code_then_ops 允许后置的是发布/存量处置，
   不能替代合同要求的代码回归 → 是方案没做到位，不是缺人的决策）
→ REVISION（rev 1/1 耗尽）
→ CLOSURE_REVIEW: R002 RESOLVED，R001 remaining
→ ABLATION（abl 1/1 耗尽），R001 再 ADDRESSED
→ FINAL_REVIEW: R001 仍 ADDRESSED（note：预算/中断用例在旧分类器下同样通过，无区分力）
   + R004(BLOCKING/REQUIREMENT，A03 混合错误无 data 场景缺测试) + R003(非阻塞)
→ 权威判定 #2: R004 covered_by [D001, D004]（语义已被"复用 TRANSIENT"+"transient_wins"裁决
   → solution coverage gap）
→ 回流 continue_blocker_routing: revision 1/1 ✗ → ablation 1/1 ✗ → HUMAN_HANDOFF
```

Issue 终态一览（issues.json）：

| Issue | 严重度/类别 | 来源 | 终态 | covered_by |
|---|---|---|---|---|
| R001 | BLOCKING / REQUIREMENT | INITIAL_REVIEW | ADDRESSED（三轮未 RESOLVED，note 持续细化） | [D003] |
| R002 | BLOCKING / REGRESSION | INITIAL_REVIEW | RESOLVED（closure 轮关闭） | — |
| R003 | NON_BLOCKING / REQUIREMENT | FINAL_REVIEW | OPEN | — |
| R004 | BLOCKING / REQUIREMENT | FINAL_REVIEW | OPEN | [D001, D004] |

## 4. 审计发现（遇到的问题）

### P1（高）deferred 问题同秒开门复发——84fb P1 同族 ⭐

- REQU-ff2b261d 在 INTAKE rev1 被 deferred，rev2 于 HG001 关闭**同一秒**（17:07:27）作为 HG002 开门，用户 36 秒答完。该问（混合错误优先级）与 HG001 三问（预算/修复范围/六店处置）相互独立，完全可并入同批。
- 本会话未因此致死**只是侥幸**：两次权威判定都走了 covered 分支，收敛门从未需要开。若终审权威判定产出 NEEDS_NEW_HUMAN_DECISION，打断预算 0 剩余 → 必然重演 84fb"有决策候选却开不了门"的终局。
- 两个真实会话（84fb、c454）连续出现同模式，证明这是系统性问题而非个例；84fb P1 的修复建议（独立问题同批提问 / 预算按人工会话窗口计费 / 为评审后收敛门预留 1 次）至今未实施，本 case 构成其复发证据。

### P2（高）FINAL_REVIEW 才浮出新的 BLOCKING 问题（R004）⭐

- A03（混合错误、双顺序、有/无 data）自 rev1 合同即存在（task.md 验收第 20 行）；初审 R001 只盯 A07–A09 的验证移交运维，未发现 A03"无 data 形态"的测试覆盖缺口；R002 在 closure 轮关闭后，该缺口直到终审（无任何剩余阶梯预算）才以 R004 形式出现——**晚期发现 + 零预算 = 结构性死局**。
- 部分缺口确由方案演化引入（消融重设计测试后），但"终审才出新 blocker"整体反映评审深度在轮间不一致：初评浅（只查验证计划归属）、终审深（逐用例审计证明力）。
- 改进方向：closure review 检查单锚定合同验收项逐项过（A01–A09 checklist）；为 final-round 新发现的 blocker 考虑允许一次定向修订（或调高 `max_revision_rounds`）；把"终审新 blocker 数"纳入 V0.3 遥测作为评审一致性信号。

### P3（中）单个 blocker 烧穿整条阶梯

- R001 三轮未死：初审提出 → revision 声称 ADDRESSED → closure 判 remaining → ablation 再 ADDRESSED → 终审仍 ADDRESSED 并追加更深的 note（用例在旧分类器下同样可通过、无区分力）。
- 阶梯每级都"诚实工作"（reviewer 拒绝假关闭值得肯定——R001 的关闭条件确实没满足），但预算形态（1+1）意味着**一个持续演化的 blocker 必然耗尽全部阶梯**：约 19 分钟 agent 时间（revise+ablate+closure+final）花在同一个验证计划问题上。
- note 逐轮变细（从"缺验证"到"验证设计无区分力"）说明初评深度不足、后轮逐步深挖；若初评即达终审深度，一轮 REVISION 可能就关闭。评审深度一致性比预算加码更治本。

### P4（中）预算耗尽型 handoff 的"决策包缺失"表达不匹配

- handoff.md 写的是 "What the Human needs to decide: (no explicit decision packet derivable)"、"Suggested Options: none"、"Recommended next action: …state the Human conclusions directly in the request"。
- 但本会话**根本没有待人裁决的语义问题**（两次判定均为 covered）；人需要的不是"陈述结论"，而是带着 R001 的 note 与 R004 的 acceptance 开新会话继续改方案（或自己改）。模板是决策中心主义的，方案缺口型交接需要不同的 next-action 段：把残余 blocker 的 note/acceptance 直接列为新会话的硬性输入，而不是引导用户去"陈述决策"。

### P5（低）R003 在 handoff.md 中完全缺席

- 非阻塞问题不强制关闭没有问题，但终态交接文档只渲染 blocker；读者不知道还有一个 OPEN 的 R003（"等待中断证明与历史重放耗尽覆盖仍未闭合"——实质与 R001 同族），续作会话若只按 handoff.md 工作，会漏掉这条与 R001 note 互补的线索。

### P6（低）可观测性残留（与 84fb P7 同族）

- state.json 不记录运行代码版本（HEAD/commit），事后审计只能按事件特征推断（本报告"运行代码"一行即受此限）。
- codex 能力探测 55.4s（pi 3.7s），第三次出现 ≈1min 级开销，同环境无缓存。

## 5. 表现良好的部分（对既有修复的实证 + 本次亮点）

1. **V0.2 收敛阶梯首次在真实会话端到端全链路走通**：NEED_HUMAN 翻转 → 权威判定 → covered_by_decisions 回流 → REVISION → CLOSURE → ABLATION_TRIGGERED → FINAL → 二次权威判定 → 预算尽 fail-closed handoff，全程审计事件齐备（`ISSUE_NEED_HUMAN`、`ISSUE_HUMAN_AUTHORITY_CHECK_STARTED`、`ISSUE_COVERED_BY_DECISION` 含 decision_ids、`SESSION_HUMAN_HANDOFF`、`HANDOFF_WRITTEN`）。
2. **covered_by_decisions 路由避免两次无谓打断**：R001（D003 范围内）、R004（D001+D004 已裁决）被正确判为方案缺口回流——正是 V0.1 PROD-001"已定语义的 issue 直接终态"反模式的修复在野化验证，V0.2 核心价值的直接实证。
3. **零协议重试（protocol_retries 0/1）**：11 次真实 agent 调用全部一次通过 schema 校验，含两次 human_authority_check（84fb 该调用点曾 281s 整轮重跑）——RC 系列修复后的首次全零。
4. **门交互零摩擦**：4 问全部裸 "1" 首答命中、零 unmatched、零自定义、零多选歧义；推荐接受率 4/4。RC3 别名空间在无歧义输入下的低摩擦路径得到验证（与 84fb 的 33% unmatched 形成对照，说明摩擦主要来自歧义表达而非解析器）。
5. **评审深度可溯且逐轮递进**：终审 R001 note 引用 GraphqlExecutor L115/L126/L204 真实时序，证明提案的预算/中断用例会在进入 TRANSIENT 前退出、"在旧分类器下同样通过、无区分力"——评审审计的是测试计划的**证明力**而非存在性，显著高于 LGTM 式评审（尽管该深度来得太晚，见 P2/P3）。
6. **消融纪律良好**：6 项删除均带等价性论证（如 Mockito final 类注入 → 固定时刻纯函数断言等价），生产代码改动面收缩为 4 文件 + 执行器 1 行字符串拼接。
7. **全程无崩溃、无丢工作**：46 分钟 11 次真实调用 + 2 道门 + 3 轮评审，产物链（events/issues/decisions/human-gate/proposal/ablation/handoff）完整互恰，事后可逐秒还原（本报告即证据）。
8. **人工杠杆极高**：人工实际输入 4 次"1"（秒级），换取调研、契约、四项决策、三轮设计修订与 4 条带证据的评审问题。

## 6. 改进建议（按优先级）

1. **门合并与打断预算会计（P1，与 84fb 建议合并实施）**：独立问题一律同批提问；deferred 仅保留给真正依赖本轮答案的问题；预算计费从"每门一次"改为"每人工会话窗口一次"，或至少为评审后收敛门预留 1 次。两个真实会话已连续命中此模式，建议升级为 V0.3 前置修复项。
2. **终审新 blocker 的处置（P2）**：closure review 锚定合同验收项 checklist；考虑 final-round 新发现 blocker 允许一次定向修订；"终审新 blocker 数"纳入遥测。
3. **评审深度前移（P3）**：initial review 提示词要求对验证计划做"证明力审计"（用例是否具备区分力），而不是只查覆盖项存在性；这是比调高预算更治本的收敛手段。
4. **handoff.md 分型渲染（P4）**：区分"决策真空型"（84fb，渲染决策候选）与"方案缺口型"（本 case，渲染残余 blocker 的 note/acceptance 为新会话硬性输入）两种 next-action 模板。
5. **handoff.md 附带非阻塞 issue（P5）**：终态交接至少索引全部 OPEN issue。
6. **小项（P6）**：state.json 记录运行 commit；同环境能力探测结果缓存。

## 7. 对本会话的人工结论（供续作会话引用）

本会话无可裁决的语义问题（D001–D004 维持不变）；续作请求建议直接携带以下事实（成为新会话硬性输入，避免重新演化三轮）：

| 残余 blocker | 续作要求（case 复盘视角，非定论） |
|---|---|
| R001 第三关闭条件 | 预算/中断用例必须**先实际进入 TRANSIENT**（断言 FAULT_RETRY 事件/重试日志已发生）再触发轮预算耗尽或中断，断言及时退出且不再发 HTTP；handoff.md note 已给出可执行设计（每次调用推进假时钟 350s / 经 metrics 钩子在 FAULT_RETRY 时置中断位使 L161 等待路径抛 InterruptedException） |
| R004 | 在 ErrorClassifierTest 既有参数化测试中补齐"混合错误**无 data**"双顺序形态，断言 TRANSIENT、INTERNAL_SERVER_ERROR、dataUsable=false；同步修正验收映射 |
| R003（非阻塞） | 等待中断验证须实际覆盖等待路径、历史重放耗尽覆盖——与 R001 同族，可一并处理 |

## 8. 与 84fb 的对照：两个失败分支的互补实证

| 维度 | 84fb（对账 Java 化） | c454（本 case，PROD-005） |
|---|---|---|
| revision / ablation | 0/1、0/1（**未动用**） | 1/1、1/1（**全部耗尽**） |
| 打断预算 | 2/2（intake 连环门烧光） | 2/2（intake，但收敛门从未需要开） |
| 权威判定产出 | 4 个 NEEDS_NEW_HUMAN_DECISION（有候选开不了门） | 2 次均 covered（无候选，纯方案缺口） |
| handoff 类型 | 决策真空型（Suggested Options 应渲染候选，P6 漏渲染） | 方案缺口型（本 case P4：模板不匹配） |
| 死因 | 打断预算在需求澄清期烧光，产出陪葬 | 收敛预算在方案修正期耗尽，fail-closed |

两者共同点：deferred 问题同秒第二门（P1 系统性复发）；state.json 无代码版本（P6）。两个会话合计覆盖了 V0.2 路由规约的全部三个分支及两个失败出口，V0.2 机制本身在两个方向上都工作正常——**handoff 不是回归，而是预算边界下的正确行为**；需要修的是预算形状与交接表达。

---

## 附录 A：证据文件索引

| 内容 | 路径（`C:\DEV\shopify_api\.review\20260914-165600-c454\`） |
|---|---|
| 终态与预算 | `state.json`（handoff_reason、budgets：revision 1/1、ablation 1/1、interruptions 2/2、protocol_retries 0/1） |
| 全量事件轨迹 | `events.jsonl`（HG001→HG002 同秒接力、两次 ISSUE_COVERED_BY_DECISION、ABLATION_TRIGGERED、SESSION_HUMAN_HANDOFF 均可见） |
| 评审问题 | `issues.json`（R001–R004，含终态与 covered_by_decisions） |
| 门与答案 | `human-gate.json`（4 问全部裸 "1" 首答命中）、`decisions.json`（D001–D004） |
| 交接包 | `handoff.md`（"no explicit decision packet derivable" 即 P4 证据） |
| 契约与设计 | `task.json`（rev3）、`proposal.json`/`proposal.md`、`change-map.json`、`discovery.md`、`ablation.md`（6 项删除的等价性论证） |
| agent 原始 IO | `raw/`（pi×5 + codex×3 共 8 份 jsonl，其中 `pi-human_authority_check.jsonl` 含两次判定；能力探测另计） |
