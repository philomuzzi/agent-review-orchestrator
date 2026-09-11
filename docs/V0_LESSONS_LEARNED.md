# V0 实施经验总结（Lessons Learned）

**范围**：V0 从空仓库到可用（M0–M6）、真实 agent 联调、Windows 环境攻坚、以及第一个真实业务会话（shopify_api）的复盘。
**用途**：给后续 V0.1/V0.3/V0.5 的实施者和维护者留一份可复用的经验清单。

---

## 1. 结果概览

| 项 | 结果 |
|---|---|
| 实现 | M0–M6 全部完成并通过验收清单（spec §32） |
| 确定性测试 | 109 passed（含 RC2 审计回归），假适配器/mock 子进程驱动 |
| 真实 smoke | pi 0.85.1 + codex 0.153.4 双通过（`AGENT_REVIEW_SMOKE=1`） |
| 真实 E2E | 完整会话：人审门 → 3 决策 → task_revision 2 → 真实 Pi 设计 → 真实 Codex 评审 → PASS → final.md |
| 部署形态 | venv editable 安装 + npm 目录双 shim（cmd / Git Bash） |

最有价值的架构决策（事后验证）：**确定性核心 + 失败关闭的适配器**。编排逻辑只依赖协议接口，真实 agent 只是可替换的末端；因此环境层的所有崩溃都没有污染状态机。

---

## 2. 流程经验

### 2.1 里程碑纪律有效，但顺序是关键
- M0–M6 严格串行、每个里程碑先跑验收再前进，避免了"边写编排边调真实 agent"的混乱。
- **假适配器先行**（spec §26.1）是整个项目回报率最高的决定：状态机、预算、人审门、恢复路径全部用确定性脚本穷举后，真实 agent 接入只暴露"传输层"问题，而不是逻辑问题。

### 2.2 18 个必测场景是验收主干
spec §26.2 的场景清单（无阻塞直通、阻塞→改稿→闭环、消融、预算耗尽交接、部分应答、都按推荐、协议修复上限、Ctrl+C 恢复……）直接映射成测试文件骨架。经验：**每写一个协议规则，立刻配一个"违反它必然失败"的测试**，例如"closure 新 BLOCKING 非 REGRESSION 必须降级"。

### 2.3 持久化先于状态迁移
"先落盘阶段产物、再迁移 state.json"的原子写（tmp + `os.replace`）让 resume 变得平凡：中断恢复 = 从 state.json 读相位重放，不需要事件日志回放。V0 规格禁止 event replay 作为唯一恢复手段，这条在实践中完全正确。

---

## 3. Windows 环境踩坑实录（最大的一块）

### 3.1 rich legacy Win32 控制台渲染导致 python.exe 原生崩溃 ⭐ 最严重
- **现象**：PowerShell 下运行时弹「0x... 指令引用了 0xFFFFFFFFFFFFFFFF 内存。该内存不能为 read」。
- **定位链**：Windows 事件日志（无 1000 级记录）→ 复现实验隔离路径 → rich 源码。崩溃地址读 **-1（INVALID_HANDLE_VALUE）** 是"无效句柄被当指针解引用"的指纹。
- **根因**：stdout 被重定向/分离时，rich（typer 依赖）仍判定走"传统 Win32 控制台渲染"，对非控制台句柄调 kernel32 console API。
- **修复**（`cfcdbda`）：CLI 入口用 `GetConsoleMode` 验证 stdout 是真控制台；不是则 patch `rich.console.detect_legacy_windows = lambda: False` 并设 `NO_COLOR`。
- **经验**：
  1. Python 程序的原生崩溃未必是自己的代码——依赖的渲染层可能在做 ctypes 调用；
  2. `0xFFFFFFFFFFFFFFFF` 读取地址 ≈ 无效句柄，看到即可按句柄失效方向查；
  3. 修复必须对着**最初复现路径**回归验证，不能只看新用例。

### 3.2 GBK/UTF-8 是真问题，但不是唯一的真问题
- 第一个崩溃（msys 管道下 `OSError [Errno 22]`）先按编码修（入口强制 UTF-8 stdio），**只治了一半**——Errno 22 在 UTF-8 下依旧，真因是 3.1 的句柄误判。
- **经验**：症状相似的两个 bug 可能叠加存在；"修复后复测原始 repro"是不可跳过的步骤。

### 3.3 msys 管道会谎报 isatty
Git Bash 的管道让 `sys.stdin/stdout.isatty()` 返回 True，触发一连串下游误判（rich legacy 路径、交互门误开、EOF 行为）。**经验**：Windows 上判断"真控制台"要用 `GetConsoleMode`，不要信 `isatty()`。

### 3.4 长文本/多行内容绝不能走命令行参数
- `.cmd` 包装层会重解析参数：多行 prompt 直接丢失、超长被截断（cmd 8191 字符限制）。
- **修复**：codex prompt 一律走 stdin（`codex exec -`）；pi RPC 本来就走 stdin。
- **经验**：Windows 上"spawn 包装脚本 + 复杂参数"的组合是雷区，结构化内容首选 stdin/临时文件。

### 3.5 shim 与进程清理
- npm 目录放 shim 需要**两份**：`review.cmd`（cmd/PowerShell）+ 无扩展名 sh 脚本（Git Bash 只认后者）。printf 写 .cmd 会吃反斜杠，用文件写入工具。
- 杀子进程要杀**进程树**（`taskkill /T /F`）：`.CMD` 包装的 node 子进程活得比 `terminate()` 久，还会锁住临时目录导致清理失败。
- `winpty` 自身有断言崩溃，不能作为自动化伪 TTY 的可靠方案。

### 3.6 管道 EOF 必须映射为 WAITING_FOR_HUMAN 而非 FAILED
stdin 关闭时 `input()` 抛 EOFError，最初落进兜底 `except Exception` → 错误地 FAILED(30)。协议要求非交互场景持久化问题包后退出 20。**经验**：把"用户输入不可用"和"系统故障"分成两条明确路径。

---

## 4. Agent 集成经验（pi / codex）

### 4.1 只读工具与可发现性的矛盾，由宿主解决
pi 的 `--tools read` 能读文件**但不能列目录**（EISDIR），纯只读授权直接导致 discovery 认为"仓库是空的"。修复：编排器在 prompt 里内嵌**有界的文件清单**（`repository_listing`，跳过 .git/node_modules 等，上限 400 条）。
**经验**：收紧 agent 能力时，要补偿"被收掉的能力"里任务必需的部分——用宿主侧确定性手段补，而不是放宽授权。

### 4.2 codex `--output-schema` 要求 strict 形态
Pydantic 默认 schema 不满足 OpenAI strict 约束（`additionalProperties:false`、全字段 `required`、无 `default`）。写了 `strict_output_schema()` 转换器。**经验**：结构化输出功能能用就尽量用，它把协议修复率降到接近零；但每种 runtime 的 schema 方言都要适配层。

### 4.3 能力探测要"正反对照"验证只读
- pi：`--tools read` 下探针写文件 → 被拒；放开工具 → 探针文件真出现。两个方向都验证过才敢信。
- codex：`-s read-only` 下写入得到 `PermissionDenied`；`-s workspace-write` 下成功写入。
- **经验**：只读保障不能靠文档承诺，要靠**实测写探针**（在临时目录，不碰目标仓库），失败即 fail closed。

### 4.4 流式读取：EOF 与超时必须用不同哨兵
RPC reader 线程里 `queue.get(timeout)` 超时和流关闭最初都返回 `None`，导致模型"思考静默 5 秒"被误判为进程退出（真实 E2E 抓到的 bug）。修复：独立 `_EOF` 哨兵对象。
**经验**：多路复用读取里，"没有数据"和"没有来源"是两个语义。

### 4.5 无状态调用 + 同进程修复
每次阶段调用 spawn 新进程（spawn → 完整上下文 → 收集 → 校验 → 退出），协议修复在同进程内发第二条 prompt。agent 侧不留会话记忆，状态唯一真源在 `.review/`——恢复与审计从未因此出问题。

---

## 5. 协议设计经验（来自 shopify_api 真实会话复盘）

真实会话（全局任务并行化）走向 `HUMAN_HANDOFF` 的因果链：

```text
原始请求四层歧义 → 两道门把打断预算(2/2)耗在"需求澄清"上
→ Pi 设计 → Codex 初审发现 2 个 NEED_HUMAN（互斥语义 + 容量边界）
→ PASS 被 NEED_HUMAN 卡死（人拥有语义，agent 不得代答）
→ 第三道门被禁止（预算）且 issue 无选项包可推导
→ HUMAN_HANDOFF（现场完整保留）
```

**经验**：
1. **请求质量决定体验**：gate 预算会被"本可以写清楚的需求歧义"消耗掉，留给真正的权衡问题。发起请求时把目标层、形态、边界约束尽量写明，收敛轮次显著下降。
2. **评审会暴露"下游才能发现"的语义问题**（如"正式路径根本不取那把锁"），这类问题在 intake 时不可知——NEED_HUMAN → 交接是正确出口，不是缺陷。
3. **V0 已知边界**：NEED_HUMAN 的 issue 不带决策选项，无法自动生成第三道门。后续版本可让 reviewer 在打 NEED_HUMAN 时同时给出可选方案（带影响），把这类交接变成可续跑的门。
4. 机械 PASS + task_revision/STALE 归档比任何"聪明的增量复用"都可靠：设计依据一变，旧提案/旧评审整体作废重来，从不产生半新半旧的设计。

---

## 6. 测试策略经验

| 手段 | 作用 |
|---|---|
| `FakePiAdapter/FakeCodexAdapter`（按方法脚本化） | 状态机/预算/门协议穷举，零模型成本 |
| `mock_pi.py`（RPC 协议模拟）/ `mock_codex.py`（exec 模拟） | 适配器传输层：帧解析、修复重试、raw 捕获、退出码 |
| `AGENT_REVIEW_FAKE_ADAPTERS=1` | CLI 层测试不触发真实探测 |
| `AGENT_REVIEW_SMOKE=1`（opt-in） | 有真实二进制时才跑的真实 smoke |
| 真实 E2E 手动跑一轮 | **不可省**——假适配器全绿的情况下，真实运行仍然抓出 3 个 bug（目录清单缺失、EOF 处理、控制台崩溃） |

**核心教训：确定性测试证明"逻辑对"，真实 E2E 证明"能用"，两者互不可替代。**

---

## 7. 对 V0.1 / V0.3 / V0.5 的衔接建议

1. **V0.1 先解决 Runtime Progress Visibility**：第一次真实使用已经确认，阶段执行完全黑盒会直接损害信任和可用性。复用 `events.jsonl` 的领域事件，在终端显示 Phase、Agent、耗时、Heartbeat、Retry、Issue 摘要和 Human Gate，不输出原始推理，也不伪造百分比进度。
2. **遥测（V0.3）优先回答这些问题**：gate 预算 2 次是否合理？NEED_HUMAN 交接占比多少？哪类请求消耗预算在"歧义澄清"上？——这些直接决定 V0.5 的方向。
3. 候选小改进（未实现，仅记录）：
   - reviewer 打 NEED_HUMAN 时附带决策选项包（把交接变可续跑的门）；
   - `review --version` 与 `review show events` 便利命令。
4. Windows 崩溃修复（`cfcdbda`）与 UTF-8 加固（`cea4c83`）是环境层基线，后续进度输出和遥测都必须继续覆盖 PowerShell、Git Bash、pipe/redirect 场景。

当前路线：

```text
V0    Fixed Agent Workflow
V0.1  Runtime Progress Visibility
V0.3  Workflow Telemetry
V0.5  Role-Based Agent Assignment
V0.7  Multi Reviewer
V1    Capability-Based Agent Routing
```

偶数小版本暂时保留，为后续真实体验中必须插队解决的问题留空间。

---

## 8. V0.1 实施记录（Runtime Progress Visibility，2026-09-10）

V0.1 在 V0 基线上增加运行期可观测性与会话呈现层，未改动任何 V0 语义（PASS、门、预算、恢复、只读边界全部原样）。

### 7.1 结果概览

| 项 | 结果 |
|---|---|
| 实现 | 进度渲染器（default/`--verbose`/`--quiet`）、心跳、短稳定 session id、语义 task_title、status/resume/show 会话呈现、`--name`、`status --list` |
| 确定性测试 | 152 passed（含 28 个 V0.1 新回归），2 smoke skip→真实环境实跑 2 passed |
| 真实 E2E | pi 0.85.1 + codex 0.154.0 完整会话：DISCOVER→门(3 决策,都按推荐)→task_revision 2→设计→初审→阻塞→改稿（首跑 JSON 缺尾括号→协议修复→FAILED→resume 重试成功）→闭环→DONE，全程心跳可见 |

### 7.2 架构决策

1. **单事件源**：`Orchestrator.event()` 是唯一进度真源，同时写 `events.jsonl` 与 CLI 渲染器；适配器协议重试通过 `event_sink` 回流同一条流。为 V0.3 遥测零改造铺路。心跳也落 events.jsonl（231 条/真实会话，锁序列化后无交错）。`append_event` 加了 `threading.Lock`：心跳线程与主线程并发追加必须串行化。
2. **心跳由编排器后台线程产生**（`agent_call` 包装器：stop-Event + daemon 线程），渲染器只消费事件。心跳含义严格限定为“仍在等待活跃 agent 调用”，无百分比、无成功率暗示。能力探测（capability probe，真实环境 4–55s）也走同一包装器，否则启动阶段会重新变成黑盒。
3. **渲染器是纯投影**：未知事件忽略、写流异常吞掉（渲染永不反噬工作流）；无 ANSI 色（符号 → ✓ ! ✗ ↻ 承担语义，Windows 最安全）；不渲染任何 agent 原文。
4. **session id 与标题彻底分离**：id = `YYYYMMDD-HHMMSS-4hex`（`secrets.token_hex(2)`），目录永不改名；标题三优先级 `--name` > DISCOVER 产出 > 占位符 `Current request`。DiscoveryResult 加了可选 `task_title` 字段，标题由既有 DISCOVER 调用顺带产出，零额外模型调用。真实 Pi 首跑即给出合格标题（「为同步任务添加步骤最大重试计数」，14 字，语义而非截断）。
5. **级别过滤在渲染器内静态判定**（QUIET_EVENTS / _VERBOSE_EVENTS 白名单），确定性可测；门交互问答走 UI 层不受 --quiet 影响（quiet 模式下门仍可见可答，符合规格）。

### 7.3 新踩坑与验证结论

1. **真实 E2E 再次抓到假适配器抓不到的问题**：Pi 在 revise 阶段两次输出 18921 字符、恰好缺最后一个 `}` 的 JSON（两次字节级相同）。协议修复重发同样缺括号→按规格 FAILED；`review resume` 从 REVISION 边界重跑即成功。结论：fail-closed + 边界恢复链路在真实故障下工作正常；超长结构化输出是 agent 侧现实风险，V0 不猜测修补（不得代 agent 补括号），保持 FAILED+resume 是正确行为。
2. **PowerShell 5.1 管道捕获会把 UTF-8 字节按 OEM(936) 解码**：真控制台（WriteConsoleW）与 Git Bash/重定向均正常，仅 `review ... | Select-Object` 这类 PS 管道捕获出现乱码。这是 PS 侧解码选择，发射端无法同时满足 msys(UTF-8) 与 PS 管道(GBK)；维持 UTF-8 输出（与 V0 中文门文本一致），文档化而非 hack。**V0 的两处崩溃修复（rich legacy guard、UTF-8 stdio）在新增渲染路径下均未回归**——重定向/管道下无 Errno 22、无原生崩溃。
3. **驱动脚本必须走 `cli.main()` 入口**：直连 API 的驱动绕过了 `_harness_windows_stdio()`，GBK 控制台立刻花屏。教训：任何打印非 ASCII 的入口都要复用 CLI 的 stdio 加固，而不是各自 print。
4. **同秒多会话排序**：目录名排序在同秒内随机（后缀随机），`status --list` 必须按 `state.created_at`（微秒）排序而非目录名。
5. **心跳竞态无害**：失败/完成前一拍心跳可能落在终局事件之后（线程时序），属可接受的外观噪声；AGENTS_CALL_FAILED/COMPLETED 语义不受影响。

### 7.4 衔接提示（给 V0.3）

- 事件流已具备遥测骨架：AGENT_CALL_STARTED/COMPLETED（含耗时）、AGENT_CALL_HEARTBEAT、PROTOCOL_RETRY(_SUCCEEDED/_EXHAUSTED)、ISSUES_INGESTED（含计数与 ID）、TASK_TITLE_SET、SESSION_RESUMED。V0.3 聚合器可直接消费 events.jsonl，不需要新埋点。
- 可回答的新问题：每阶段 agent 真实时长分布、心跳密度与“卡死”区分、协议重试集中在哪个阶段/哪个 schema、resume 后重试成功率。
- 未做（按规格非目标）：仪表盘、百分比进度、原始推理展示、目录改名、语义搜索。

---

## 8.5 V0.1-RC2 实施记录（2026-09-11）

RC1（`24eb2b5`）在真实联调中表现良好，但审计发现三类同一根源的缺陷：**凡是新增“进入 CLI 呈现面的数据通路”，都必须在宿主侧确定性收口**。详见 `docs/V0_1_IMPLEMENTATION_AUDIT.md`。

### 8.5.1 新经验：呈现层的三条铁律

> 注：远程 RC1 审计（B101–B103）与本地复核在 RC2 一并解决；本节含两批发现。

0. **随机后缀的 id 会瞬间作废一切“按目录名排序”的代码**（远程 B101）：短 id 引入随机 4hex 后，同秒内字典序完全无时间含义；而 `latest_session` 仍在用目录名排序，且“未完成”只认 RUNNING——更新的 FAILED/INTERRUPTED（可恢复）会被更旧的 RUNNING 挡住。修复：唯一排序策略 = 持久化 `created_at`（损坏会话剔除、id 决定性决胜），未完成 = 状态机 `RESUMABLE_STATUSES`。教训：**改 id 方案时，全仓搜一遍依赖旧 id 性质的代码**（排序、去重、latest）。
0. **进度渲染不得强于编排器结论**（远程 B102）：closure 行只报 resolved 不报同一评审新引入的阻塞；final 行直接渲染 reviewer 的 satisfies_requirement——用户先看到“requirement satisfied”紧接着 HANDOFF。修复：两个事件改在 ingest+生命周期+机械 PASS 之后发射，携带 `passed`/`new_blocking`/`remaining`；渲染层“requirement satisfied”只能与编排器 PASS 同现。教训：**渲染器消费的应是编排器后处理字段，不是评审员原始字段**——与 V0 的“Codex 不决定 PASS”同源。
1. **Agent 文本进入持久化元数据前必须过宿主消毒器**（远程 B103 ≡ 本地 B001）：task_title 是 agent 自由文本，RC1 直接落盘——探针会话存出 317 字符含 `\n`/`\t` 的标题，直接把 `status --list` 行切裂。修复：`sanitize_title()`（单行、空白折叠、控制符剔除、≤80 字符）在两个入口（DISCOVER、`--name`）统一执行，渲染端 `display_title()` 再消毒一次（防御历史/手改数据）。这与 V0 的 issue 生命周期归一（B001/V0）是同一个模式：**收数据的一方拥有数据形态**。
2. **渲染器必须保证“一行一事实”与载荷内容无关**（B002）：`SESSION_FAILED` 的 reason 会内嵌 codex stderr 尾部（含换行），一个事件渲染成三行。修复：`_one_line()` 应用于所有自由文本字段 + verbose 回退 dump。教训：**事件流是结构化的，但字段内容不是**；渲染层的线宽契约不能依赖上游文本干净。
3. **查我清单的路径要把“坏会话”当一等公民**（B003）：一个 state.json 损坏的会话让 `status`/`status --list`/`show`/`resume` 全部裸异常退出，而代码里那行“(corrupt state)”降级分支其实是死代码——**写了降级路径不等于降级路径可达**，必须用探针验证。修复：`load_state` 对缺失/不可读/非法一律返回 None（fail closed），CLI 层接住 AgentError/ValueError 转干净退出码；`recover_phase` 对非法 checkpoint 依旧硬失败（恢复真相不容含糊）。

### 8.5.2 新经验：细节

- **Ctrl+C 不计入 agent 失败**（远程 N101）：`agent_call` 捕获 BaseException 时把 KeyboardInterrupt 也发成 AGENT_CALL_FAILED，遥测会把用户取消算成 agent 故障。修复：独立 `AGENT_CALL_INTERRUPTED` 事件（仅 verbose 渲染），终态提示仍由 SESSION_INTERRUPTED 承担。
- **协议重试事件的 phase 必须走同一词表**（远程 N103）：适配器说方法名（`initial_review`），事件流必须说相位名（`INITIAL_REVIEW`），否则 V0.3 聚合会把一个相位劈成两个值。修复点选在共享的 `protocol_retry_reporter`（真实/假适配器同路）。
- **任务修订行只说真实发生的事**（远程 N105）：门发生在提案存在之前时，“旧提案已归档 STALE”是流报。事件携带 `archived` 布尔，渲染按事实拼句；真实运行已验证（门后无提案 → 仅 “design basis changed”）。
- **ID 碰撞退路不能破坏格式不变量**（R203）：`-2` 后缀让 id 超出 `YYYYMMDD-HHMMSS-xxxx` 契约；改为重掷随机后缀。任何“格式即契约”的标识符，其异常路径也要过同一正则。
- **`step()` 恢复路径重载失败时保留内存态**：`load_state` 变宽松后，恢复路径若拿到 None 会把 `self.state` 置空——改为“重载成功才覆盖”，与旧行为（异常时不赋值）语义对齐。改宽一个 API 时，逐个检查它的全部调用点方向是否变宽/变窄。
- **自动化真实 E2E 的门答答**：msys 管道对 isatty 撒谎（有时 True），`printf | review resume` 又是真管道（False）→ 门答不可依赖；改用脚本化 UI 驱动 `Orchestrator.resume`（真实适配器 + 真实渲染器，复用 CLI 的 stdio 加固），仅人类按键是常量。这也再次验证了 7.3.3：驱动脚本必须走 CLI 入口/复用其加固。
- **真实 E2E 再次复现 NEED_HUMAN→交接边界**（R001，FACT 类阻塞 + 门预算 2/2 耗尽）：这是正确行为而非缺陷；N007（reviewer 附带决策选项包）继续挂在 V0.5。

### 8.5.3 RC2 验证结论

| 项 | 结果 |
| --- | --- |
| 确定性测试 | 181 passed（+29 RC2 回归），2 smoke skip |
| 真实 smoke | 2 passed（pi 0.85.1 / codex 0.154.0，≈150s） |
| 真实 E2E① | 门(3+2 决策)→task_revision 3→设计→初审 2 blocking→NEED_HUMAN→HUMAN_HANDOFF(10)，全程心跳/重试/任务修订可见 |
| 真实 E2E② | 无 --name：占位符→DISCOVER 语义标题（13 字，非截断）→1 门→DONE(0) |
| 真实 E2E③（RC2 后） | N105 真实生效（门后无提案不虚报归档）；DONE(0)；默认解析、--list 首行、created_at 三者一致（B101 实证） |
| Windows 加固 | 两处崩溃修复（rich legacy guard、UTF-8 stdio）在全部新渲染路径下无回归 |

明确移交 V0.3：N102（心跳产生策略与渲染器解耦）、N104（事件流 attempt/commit 语义，聚合前必须解决双计数）。

---

## 8.6 V0.1-RC3 实施记录（2026-09-11）

RC2 后的复查发现三个同族残留缺陷（远程/本地审计 B201–B203，详见
`docs/V0_1_RC3_FIX_SPEC.md` 与审计文档的 RC3 记录）。修复未触碰任何
V0/V0.1 工作流语义。

### 8.6.1 新经验：呈现层的收口清单又补了三条

1. **“加了消毒器” ≠ “所有出口都消毒了”**（B201）：RC2 给渲染器加了
   `_one_line`，但 CLI 自己的 `_report()` 终局摘要（`FAILED: {state.error}`、
   `HUMAN_HANDOFF: {state.handoff_reason}`）是**第二条呈现通路**，仍在裸打印
   状态里的自由文本（失败原因内嵌 agent stderr 尾部）。修复：把渲染器的
   私有函数升为公共 `sanitize_line()`，CLI 终局摘要与 resume 失败消息全部过
   同一个函数。教训：**引入安全边界时，枚举“进入终端的每一条通路”——
   事件驱动的渲染、CLI 直接拼接的摘要、错误处理分支里的 echo，三者缺一即破**。
   回归测试必须打穿完整 `_report()` 路径，只测渲染器回放会漏掉旁路。
2. **fail-closed 的校验必须先于任何输出，且测试要构造“危险的成功”**
   （B202）：`review show` 先读产物再验状态——产物存在 + state 损坏时照常
   打印正文并退出 0；RC2 的损坏会话测试之所以通过，只因那个会话**恰好没有**
   被请求的产物。修复：先验 state，再碰产物，六种 kind 一致退出 30。教训：
   **验证 fail-closed 语义的回归，必须先造出“如果不拦就会成功”的前置条件**
   （真实 DONE 会话 + 真实 final.md + 损坏 state.json），再断言危险输出从未
   出现；“缺文件导致的失败”证明不了拦截器存在。
3. **给人看的时钟 ≠ 排序权威时钟**（B203）：无时区后缀的
   `YYYYMMDD-HHMMSS` 会被读者当本地时间，用 UTC 生成即“显示错误的时间”。
   修复：`local_now()`（`datetime.now().astimezone()`，可注入）供 id 展示；
   `created_at`/`updated_at` 依旧时区感知 UTC，会话解析只读持久化元数据，
   id 时钟零排序语义。教训：**人面时间要么标明时区要么直接用本地钟；任何
   排序/恢复/遥测一律读持久化权威时间戳，绝不读展示形态**。时钟必须可注入，
   测试不依赖 CI 机器时区。

### 8.6.2 验证方法补充

- **回归必须先证伪**：12 个 RC3 回归在暂存（未修复）源码上跑一遍，
  9 个按缺陷方向失败、3 个为双侧行为保持的“守卫测试”两侧均绿——
  区分“复现缺陷的测试”与“防语义漂移的测试”，两者都要，但要分开记账。
- 真实控制台冒烟（UTC+8 主机）：新会话 id 与本地钟一致（UTC 会差 8 小时）；
  损坏会话的 show/resume 干净退 30；Windows 两处崩溃加固依旧无回归。
- 验证汇总：确定性 193 passed（+12 RC3）、真实 smoke 2 passed
  （pi 0.85.1 / codex 0.154.0）。V0.1-RC3 直接进入真实 Shopify 验收。

---

## 9. 快速备忘

```bash
# 安装/升级（editable venv：代码 git pull 即生效）
cd C:\frank\agent-review-orchestrator && git pull
C:\frank\aro-venv\Scripts\python -m pip install -e . --upgrade   # 仅依赖/版本变更时

# 测试
C:\frank\aro-venv\Scripts\python -m pytest                # 确定性套件
AGENT_REVIEW_SMOKE=1 C:\frank\aro-venv\Scripts\python -m pytest   # + 真实 smoke

# 使用
cd <目标仓库>
review "需求……"        # 发起（写清楚目标层/形态/边界，少耗 gate 预算）
review status           # 相位、阻塞、预算
review show issues      # 看评审结论
review resume           # 答人审门 / 中断恢复
```

环境变量：`AGENT_REVIEW_FAKE_ADAPTERS=1`（强制假适配器）、`AGENT_REVIEW_SMOKE=1`（启用真实 smoke）、`AGENT_REVIEW_CONFIG`（配置文件路径）。
---

## 10. V0.2 实施记录（Human Decision & Convergence，2026-09-11）

V0.2 把人审门从「人类确认」升级为「人类权威」，并把评审期发现的 NEED_HUMAN 从终态交接改成可续跑的收敛门。详见 `docs/V0_2_HUMAN_DECISION_CONVERGENCE_SPEC.md` 与 `docs/V0_2_IMPLEMENTATION_AUDIT.md`。

### 10.1 结果概览

| 项 | 结果 |
|---|---|
| 实现 | 显式自定义决策、Human Authority Check（Pi 只读判定 + 编排器机械校验）、收敛门、handoff.md、门持久化一致性、有效答案验证、6 个新审计事件 |
| 确定性测试 | 229 passed（+36 V0.2 回归，含 PROD-001 永久回放），0 回归 |
| 真实 smoke | 2 passed（pi 0.85.1 / codex 0.154.0，≈153s） |
| 真实 E2E | 4 个会话：自定义决策（含跨进程 resume 补答）、覆盖路由（真实 REQUIREMENT 阻塞 → COVERED → REVISION → DONE）、收敛门（真实 NEEDS_NEW → HG002 → 自定义答案 → task_revision 3 → 重建）、真实 handoff.md |
| 已知残留 | 权威判定质量仍属 Pi（结构校验拦不住"格式正确的误判"）；revise 长输出截断复发一次（按 V0.1 既定 FAILED+resume 处理，两次恢复成功） |

### 10.2 新经验

1. **路由状态必须有持久化落点，否则每个相位入口都会"重新路由"**：覆盖判定最初只回写 `resolution` 备注，结果 REVISION 入口的防御性 `_need_human_ids` 又把同一 issue 翻回 NEED_HUMAN、二次消耗权威判定。修复：`Issue.covered_by_decisions`（编排器所有，ingest 时清零防评审员伪造）。教训：**任何"由判定产生的新路由事实"都要变成持久化字段/标记，且要枚举所有会重推导该路由的入口**（相位入口、恢复路径、防御性重查）。
2. **`allow_revision=False` 在两个调用点语义不同**：closure 路由里它意味着"走消融/交接阶梯"，而 REVISION/ABLATION 入口重查里它意味着"回本相位继续"。一个布尔参数承载两种语义差点造成闭环死循环（closure 返回 None → 相位不变 → 重跑评审）。教训：**路由函数的"继续"出口要显式区分"继续到哪个所有者"**（continue_routing 独立成参），并问一句"返回 None 之后循环会停在哪一步"。
3. **空输入是 skip 不是 attempt**：交互门里空回车最初也被记录为一条答案，成了"最新有效答案"，把上一轮的 QUESTION_ONLY 降级成 AMBIGUOUS。教训：**有效答案语义引入"最新覆盖"后，所有产生答案的路径（含跳过/EOF/空自定义）都要重新过一遍"它算不算一次尝试"**。
4. **保留字协议要先查碰撞**：`0`/`custom` 作为自定义决策的保留选择器后，选项 key 与之碰撞会让该题永远进不了自定义模式。处理：候选过滤 + 收敛包校验双入口拒绝碰撞 key。教训：**给交互协议加保留字时，把"谁可能撞上来"写进校验**。
5. **E2E 场景编排要顺着系统的设计意图找缝**：上游 intake 门本来就优先拦截歧义（架构如此工作），所以"评审期才发现的语义真空"在真实运行里是小概率路径；e2e_d 用"冻结报表契约 + 只在失败日志降级路径上留真空"才稳定触发收敛门。教训：**构造下游才可见的决策真空，要让 intake 能看到的部分全部被请求文本预先决定，让真空长在新设计自身引入的机制上**（alert.log 的写失败处理是 D002 决策的衍生品，intake 不可见）。
6. **真实收敛门的完整链路含"二次覆盖"**：收敛决策 D004 落地重建后，第二轮评审的新 REQUIREMENT 阻塞又被权威判定按 [D002, D004] 覆盖——一次会话里覆盖与收敛两条路径串联工作，且覆盖标记跨 FAILED→resume 存活。这类串联路径是假适配器很难自然复现的，值得在审计文档里留真实会话证据。
7. **工具性失败与任务边界要分开出口**：权威判定的 agent 调用失败最初被兜底成交接（exit 10），会把工具故障伪装成业务边界。改为传播 → FAILED（exit 30）+ 相位恢复，只有"合法的 CANNOT_DETERMINE"才走交接。教训：**每加一个 agent 判定点，就多了一类失败，先分类：协议/工具失败 → FAILED；判定内容不可得 → HANDOFF**。
8. **handoff.md 的信息量来自既有结构化产物**：无需新数据通路——issues.json 的 problem/acceptance/evidence、decisions.json 的 ACTIVE 决策、gate 的待答问题（含预算耗尽时未开成门的候选）直接拼装即可；真实 E2E 的 handoff.md 甚至带上了评审员内存复现的证据链。教训：**交接包是"既有真相的重组"，不是新真相的产生**。

### 10.3 衔接提示（给 V0.3）

- 事件流新增 `ISSUE_NEED_HUMAN`、`ISSUE_HUMAN_AUTHORITY_CHECK_STARTED`、`ISSUE_COVERED_BY_DECISION`、`CONVERGENCE_GATE_CREATED`、`CUSTOM_DECISION_CAPTURED`、`HANDOFF_WRITTEN`，可直接聚合：权威判定三态分布、收敛门占比、自定义决策占比、覆盖误判率（同一 issue 反复被覆盖/重提）。
- N102/N104（心跳解耦、attempt/commit 语义）仍是 V0.3 前置；权威判定调用已计入 AGENT_CALL_* 事件族。

---

## 11. V0.2-RC2 实施记录（2026-09-11）

RC1 独立评审发现三个阻断性协议缺口（B201-B203，详见
`docs/V0_2_RC2_FIX_SPEC.md`）。修复未触碰任何 V0/V0.1/V0.2 既有语义。

### 11.1 结果概览

| 项 | 结果 |
| --- | --- |
| 实现 | B201 终审同权威路由（含 `FINAL_REVIEW→WAITING_FOR_HUMAN` 状态机边）、B202 `resume_semantics` 分离收敛溯源与决策语义（Problem 模式 FACT 收敛重新 INVESTIGATE）、B203 候选包身份/溯源加固（精确到批次、语义类别、归一化键唯一、decision_key 唯一，全部在开门前/耗预算前/变更前 fail-closed）、N201 handoff 最小兜底、N202 提示词矛盾修正 |
| 确定性测试 | 255 passed（+26 RC2 回归，全部对应 fix-spec §4 第 1-16 项），0 回归 |
| 真实 smoke | 2 passed（pi 0.85.1 / codex 0.154.0，含全部确定性 257 passed） |
| 真实 RC2 E2E | 多轮真实会话验证 RC2 路由（含真实收敛门 + resume_semantics 审计 + 两次截断→resume 恢复）；终审收敛门与 Problem/FACT 收敛门两条小概率路径在真实模型上的强制成本极高，见 11.2.6 |

### 11.2 新经验（可复用）

1. **同一协议语义必须共享同一条代码路径，不能靠"三处相位各自实现"**（B201 根因）：初审/闭环审有权威路由，终审是旧 V0 代码——三处复制粘贴的漂移不是写错，而是"新能力只接到了两个调用点"。RC2 把 `run_final` 改为调同一个 `try_gate_for_need_human_issues`。教训：**给"每个 X 都要 Y"型规则写实现清单时，先枚举全部 X（这里是三个评审相位 + REVISION/ABLATION 入口重查），并给"新增调用点"配一条回归**。
2. **溯源类别（provenance）和语义类别（semantics）是两个坐标，一个字段只能承载一个**（B202 根因）：`gate.category=CONVERGENCE` 记录"门从哪来"，却抹掉了"确立了哪种人类决策"——Problem 模式 FACT 收敛决策因此被接去 INTAKE，与陈旧根因模型拼接。修复是独立的 `resume_semantics` 字段 + 确定性的保守规则（任一 FACT 即 FACT）。教训：**引入复合枚举前问一句：这个字段回答的是"从哪来"还是"是什么"；两个问题就两个字段**。
3. **静默过滤 = 把无效包洗成有效包**（B203.1 根因）：建门时 `source_id in batch` 的过滤会把非法溯源洗成空列表，进而丢掉收敛语义。修复是先验后用：校验精确到批次、失败先于一切变更。教训：**对不可信输入，"宽容地取交集"和"拒绝"看似殊途同归，实则语义完全不同；凡校验失败必须留下可审计的拒绝痕迹，绝不能静默降级**。
4. **键唯一性必须用"匹配用的同一个归一化函数"来判定**（B203.2）：选项键唯一性若用原始字符串判，`fix`/`FIX ` 会同时通过，而人按序号选 B 时持久化的是 A 的标签——人类权威被错记。修复把归一化函数提到 models 层共享，并在共享模型边界（GateQuestion）强制，普通门/收敛门同时继承。教训：**凡存在"归一化后等价"的匹配逻辑，唯一性校验必须同一把尺子，且放在两套入口共用的那一层**。
5. **修复一个"看星号"问题的同时要给同族入口补齐**：B203 是收敛包校验，但选项键唯一性同样适用于普通 intake 候选——RC2 在模型边界强制 + intake 过滤双入口收口，同族缺陷不留下一处。
6. **小概率路径的真实 E2E 强制成本要提前写进规格的 fallback 条款**："评审期才暴露的语义真空"在真实运行里是被架构设计故意最小化的路径；RC2 六次尝试的失败模式各不相同（intake 门吃掉预算 / 设计直接过审 / agent 截断），但共同点是**评审员的类别裁量与发现器的候选产出都是概率层**。RC2 规格的 fallback 条款（改用终审收敛门真实案例 + 保留确定性覆盖）是正确设计。教训：**真实 E2E 的验收目标应该是"验证修复路径在真实栈上可用且不误触"，而不是"强制小概率事件发生"；后者的成本会吞掉整个修复窗口**。
7. **真实 agent 的诚实与模型校验的严格要对齐口径**：investigate 阶段真实 Pi 会诚实列出生产不可知的 missing_evidence 同时标 SUPPORTED（V0 校验正确拒绝），通用修复提示词不含具体校验错误导致重发同样内容。RC2 通过在请求文本中显式声明根因判定的证据边界解决（合法的用户输入）。教训：**fail-closed + 边界恢复是正确姿态，但会话请求文本是用户侧合法的澄清手段；修复提示词若附带具体校验错误可降低重试浪费（记为 V0.3 候选）**。
8. **已知 agent 侧长输出截断在 revise/ablate 复发（本次 3 次，均 resume 恢复）**：行为与 V0.1 结论一致（不猜测修补、FAILED+resume），但复发频率在长设计链上偏高，V0.3 遥测应统计截断率与恢复成功率。

### 11.3 过程问题记录：真实 E2E 强制耗时约 4 小时仍未命中目标路径

**事实**：为逼出「终审收敛门 / Problem 模式 FACT 收敛门」两条新修复路由跳的真实验证，共发起 9 个真实会话（12 次驱动，含 3 次 FAILED→resume），累计约 4 小时墙钟时间，最终未在真实运行中命中任一目标跳，按规格 fallback 条款收尾（确定性覆盖完整，真实验证部分达标）。

**成本结构（为什么会这么贵）**：
1. 单轮真实会话 15~25 分钟（每阶段真实模型调用 3~7 分钟），且目标链路越长（终审需 初审阻塞→改稿→闭环未过→消融→终审 五连）联合概率越小；
2. 三层概率叠加：评审员类别裁量（REQUIREMENT vs DESIGN）、发现器候选产出（上游 intake 门把真空提前吸收）、agent 侧长输出截断（3 次中断各耗时 resume）；
3. 轮次间的请求改写是试错式的（每次只能改一个变量，验证周期即整轮会话时长）。

**可复用的改进**：
1. 真实 E2E 强制必须**硬性限时入计划**：60~90 分钟未命中即转规格 fallback，而不是事后才发现超时（本次的实际教训）；
2. fallback 触发条件要在验证计划里预先写死，不依赖执行中现场判断；
3. 中期候选（V0.3+）：提供「确定性场景种子 + 真实适配器续跑」的 E2E 模式——用假适配器推进到目标相位，再切换真实 Pi/Codex 续跑后续相位，把强制成本从小时级降到分钟级；但必须在审计文档里如实标注哪些相位是种子、哪些是真实，不得混淆 "real E2E" 的含义。

---

## 12. V0.2-RC3 实施记录（2026-09-11）

RC3 关闭 B301（人类答案别名空间歧义）与 N301（Intake 选项基数 2–4），详见
`docs/V0_2_RC3_FIX_SPEC.md` 与审计文档 §7。

### 12.1 结果概览

| 项 | 结果 |
| --- | --- |
| 实现 | B301：别名空间单一真源（models 层六形式别名 + 协议控制命令集），共享模型边界/Intake 抑制/收敛包校验三点同规 enforcement，运行期匹配 0/1/>1 判定（>1 fail-closed，绝不 first-match-wins）；N301：Intake 严格 2–4（>4 抑制不截断），两处 `[:4]` 移除 |
| 确定性测试 | 293 passed（+38 RC3 回归，对应 fix-spec §4 第 1–23 项），0 回归；修复前探针脚本证伪五个缺陷全部复现 |
| 真实 smoke | 2 passed（pi 0.85.1 / codex 0.154.0，全套 295 passed） |
| 真实 E2E | 1 个自然会话（~14 分钟，DONE）：真实 Pi 3 候选全部通过新校验；数字/全角中文标签/键三种答案形态经共享别名空间正确解析 |
| 验证预算 | 1/2 会话、0/2 强制变体、~14/60 分钟；未做任何概率性分支强制 |

### 12.2 新经验（可复用）

1. **“键唯一”类校验的真正命题是“整个输入命名空间单射”**（B301 根因）：RC2 只证明选项键唯一，但 CLI 协议每题接受六种答案形态（键/标签/键+标签/序号/选项N/option N），外加保留控制命令，全部共享一个 Human 输入命名空间。运行期按序遍历 + first-match-wins 会把“两个合法语义解释”静默录成一个 ACTIVE 决策。教训：**枚举交互协议接受的每一种输入形态，把它们全部归一化后要求“整个命名空间内单射”；校验的语法必须等于运行期匹配的完整语法，不能只挑方便校验的子集**（RC2 的键唯一性是必要不充分条件）。
2. **下界校验 + 静默截断 = 事实上的“部分接受”**（N301 根因）：`len<2` 拒绝、`len>4` 却被 `[:4]` 悄悄修成合法包——Agent 可见包与 Human 可见包从此不一致，推荐还可能指向被截掉的选项。这与 RC2 B203.1 的“静默过滤洗白无效包”同族。教训：**协议存在区间约束时，所有生产者在同一边界按区间强制；绝不能用修剪/裁剪“修复”非法输入——那不是宽容，是把非法洗成合法**。
3. **验证器 fail-closed 之后仍要给运行期留第二道闸**：`match_option` 改为 0/1/>1 判定（>1 返回 None，答案停留未解析，永不落决策）。另外发现 pydantic 的免费福利：**持久化产物重新加载时会再验证嵌套模型**，损坏的 human-gate.json 在 load 边界就被拒绝，腐坏数据进不了工作流。教训：防御纵深的顺序是“入口校验 → 运行期单射解析 → 存储重载再验证”，三道闸各挡一类逃逸（未来回归、内存腐坏、磁盘腐坏）。
4. **硬性验证预算条款真的起作用了**：RC3 规格预先写死“2 会话/2 变体/60 分钟，malformed 包用确定性夹具而不是等概率 Agent 吐出来”。实际执行 1 个自然会话（14 分钟）就拿到了 RC3 真正需要的真实验证——**新边界接受真实 Pi 的良好包（不过度拒绝）+ 三种答案形态真实解析正确**；拒绝方向由 38 个确定性回归覆盖。教训：**真实 E2E 的正确问题不是“能否强制触发缺陷路径”，而是“修复是否破坏了正常路径”——前者用夹具，后者才需要真实运行**。RC2 那 4 小时的教训被本条兑现。
5. **机械边界收紧后，提示词要同步描述它**：Agent 提示词原本只说“键不得撞保留字”；RC3 后标签/别名也受限。同步更新提示词（discover/investigate/authority-check）让真实 Agent 少踩 fail-closed。教训：**提示词是机械边界的文档面；边界变了文档面不变，会增加真实运行中可避免的拒绝**。
