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

1. **Agent 文本进入持久化元数据前必须过宿主消毒器**（B001）：task_title 是 agent 自由文本，RC1 直接落盘——探针会话存出 317 字符含 `\n`/`\t` 的标题，直接把 `status --list` 行切裂。修复：`sanitize_title()`（单行、空白折叠、控制符剔除、≤80 字符）在两个入口（DISCOVER、`--name`）统一执行，渲染端 `display_title()` 再消毒一次（防御历史/手改数据）。这与 V0 的 issue 生命周期归一（B001/V0）是同一个模式：**收数据的一方拥有数据形态**。
2. **渲染器必须保证“一行一事实”与载荷内容无关**（B002）：`SESSION_FAILED` 的 reason 会内嵌 codex stderr 尾部（含换行），一个事件渲染成三行。修复：`_one_line()` 应用于所有自由文本字段 + verbose 回退 dump。教训：**事件流是结构化的，但字段内容不是**；渲染层的线宽契约不能依赖上游文本干净。
3. **查我清单的路径要把“坏会话”当一等公民**（B003）：一个 state.json 损坏的会话让 `status`/`status --list`/`show`/`resume` 全部裸异常退出，而代码里那行“(corrupt state)”降级分支其实是死代码——**写了降级路径不等于降级路径可达**，必须用探针验证。修复：`load_state` 对缺失/不可读/非法一律返回 None（fail closed），CLI 层接住 AgentError/ValueError 转干净退出码；`recover_phase` 对非法 checkpoint 依旧硬失败（恢复真相不容含糊）。

### 8.5.2 新经验：细节

- **ID 碰撞退路不能破坏格式不变量**（N002）：`-2` 后缀让 id 超出 `YYYYMMDD-HHMMSS-xxxx` 契约；改为重掷随机后缀。任何“格式即契约”的标识符，其异常路径也要过同一正则。
- **`step()` 恢复路径重载失败时保留内存态**：`load_state` 变宽松后，恢复路径若拿到 None 会把 `self.state` 置空——改为“重载成功才覆盖”，与旧行为（异常时不赋值）语义对齐。改宽一个 API 时，逐个检查它的全部调用点方向是否变宽/变窄。
- **自动化真实 E2E 的门答答**：msys 管道对 isatty 撒谎（有时 True），`printf | review resume` 又是真管道（False）→ 门答不可依赖；改用脚本化 UI 驱动 `Orchestrator.resume`（真实适配器 + 真实渲染器，复用 CLI 的 stdio 加固），仅人类按键是常量。这也再次验证了 7.3.3：驱动脚本必须走 CLI 入口/复用其加固。
- **真实 E2E 再次复现 NEED_HUMAN→交接边界**（R001，FACT 类阻塞 + 门预算 2/2 耗尽）：这是正确行为而非缺陷；N007（reviewer 附带决策选项包）继续挂在 V0.5。

### 8.5.3 RC2 验证结论

| 项 | 结果 |
| --- | --- |
| 确定性测试 | 171 passed（+19 RC2 回归），2 smoke skip |
| 真实 smoke | 2 passed（pi 0.85.1 / codex 0.154.0，148.5s） |
| 真实 E2E① | 门(3+2 决策)→task_revision 3→设计→初审 2 blocking→NEED_HUMAN→HUMAN_HANDOFF(10)，全程心跳/重试/任务修订可见 |
| 真实 E2E② | 无 --name：占位符→DISCOVER 语义标题（13 字，非截断）→1 门→DONE(0)，`status --list`/`show events`（RC2 新增）均可辨识会话 |
| Windows 加固 | 两处崩溃修复（rich legacy guard、UTF-8 stdio）在全部新渲染路径下无回归 |

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