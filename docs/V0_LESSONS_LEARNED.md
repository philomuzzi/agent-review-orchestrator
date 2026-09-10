# V0 实施经验总结（Lessons Learned）

**范围**：V0 从空仓库到可用（M0–M6）、真实 agent 联调、Windows 环境攻坚、以及第一个真实业务会话（shopify_api）的复盘。
**用途**：给后续 V0.1/V0.2 的实施者和维护者留一份可复用的经验清单。

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

## 7. 对 V0.1 / V0.2 的衔接建议

1. **遥测（V0.1）优先回答这些问题**：gate 预算 2 次是否合理？NEED_HUMAN 交接占比多少？哪类请求消耗预算在"歧义澄清"上？——这些直接决定 V0.2 的方向。
2. 候选小改进（未实现，仅记录）：
   - reviewer 打 NEED_HUMAN 时附带决策选项包（把交接变可续跑的门）；
   - 阶段级控制台进度输出（曾实现后按需求回退，事件流 `events.jsonl` 可 tail 达成同样目的）；
   - `review --version` 与 `review show events` 便利命令。
3. Windows 崩溃修复（`cfcdbda`）与 UTF-8 加固（`cea4c83`）是环境层基线，V0.1 的遥测采集跑在长会话上时会再次受益于"EOF≠FAILED"这类路径区分。

---

## 8. 快速备忘

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
