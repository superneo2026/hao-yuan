# 上下文预算、防护与交付门禁（v0.0.2 升级说明）

本文记录一次真实的失败复盘与对应的内核改动。触发场景：16G 单卡上的 neo-tts v2
预训练方案任务，要求"参考一个 68KB 的 HTML 页面，产出一份 12 节的同风格方案页"。
同型号模型在另一个 harness 上 27 分钟一次成稿；在豪源上三次尝试全部失败：

| 会话 | 结果 | 关键数据 |
|---|---|---|
| 第 1 次 | 用户手动取消 | 1041 次模型调用 / 38 分钟 / 6760 万 prompt tokens / **0 次写交付物** |
| 第 2 次 | 报错 `no progress: repeated identical tool calls` | 72 步 |
| 第 3 次 | 状态 `done`，但只写了计划的 1/12 节，11 个导航锚点全部悬空 | 64 步内压缩 7 次 |

根因与修复如下。

## 1. 上下文预算随模型窗口伸缩

**问题**：压缩阈值固定为 `MID_COMPACT_TOKENS=14000`、`CONTEXT_COMPACT_TOKENS=20000`，
而系统提示本身约 14k–16k real tokens，净工作窗口只剩 6–10k。模型在 64 步里压缩 7 次，
每次压缩后都要重新读文件，于是"压缩 → 重读 → 再压缩"。同一模型在别处跑到 210k 上下文零压缩。

**修复**（`core/context.py`、`configs/configs.py`）：
- 预算 = `模型上下文窗口 × 比例`，固定常量只作为小窗口模型的下限。
- `midturn_compact` 只统计 **body**（不含系统提示），并在压缩后 6 步内加滞回：
  只有 body 超过触发线 1.3 倍才会再次压缩。
- `estimate_tokens()` 对中文偏低，按 `TOKEN_ESTIMATE_FACTOR=1.8` 校准；
  同时优先使用 provider 上一轮返回的真实 `prompt_tokens`。
- 工具结果老化（aging）只在 body 达到触发线 60% 后启用，不再把 6 步前的参考材料压掉。
- 压缩后注入 **交付账本**（见第 6 节），模型不需要重读自己的输出。

已知窗口表（`configs/models.py`）：`glm-5*`=200k、`glm-4.6`=200k、`glm-4.5/4.7`=128k，
其余回退 `HAOYUAN_CONTEXT_WINDOW`（默认 128k）。可在设置里给渠道写
`ZHIPU_CONTEXT_WINDOW` 覆盖。

## 2. 工具输出上限

**问题**：`TOOL_RESULT_CONTEXT_CHARS=2000`。读一个 CSS 行宽 300–500 字符的页面，
每次只能看到 3–5 行，于是模型用 611 次 `read_range` 在文件里滑动；1383 条工具结果
**100% 被截断**。`reference_digest` 设计输出 9000 字符，运行时却截到 2000。

**修复**：上限提升到 16000 字符（`TOOL_RESULT_MAX_BYTES` 同步到 64KB）。
`read_file`/`read_range` 自己按预算渲染，超出时返回**实际覆盖的行区间**并提示
`call read_range(start=last+1, end=end)`；读账本只记录真正返回过的行，避免"声称读过"。

## 3. 大文件写入自动续写（salvage）

**问题**：一次 `write_file` 写整页 HTML，`max_tokens` 未指定 → provider 默认 8192 →
JSON 被截断 → 整次生成作废。模型随后写的"骨架"带了 `</body>` 就再没续写。

**修复**：
- 未指定时统一请求 `HAOYUAN_MAX_OUTPUT`（默认 32768）输出上限；provider 若因该字段
  返回 400，会自动去掉它重试（只去掉出错字段，不连带禁用 thinking/tools）。
- `finish_reason=length` 且工具参数被截断时，从 `_raw` 中**抢救出 path + 完整行前缀**，
  落盘并返回 `[auto-continued] ... 已保存 N 行，请用 apply_patch/edit_file 续写，
  不要从头重写`。一次被截断的生成因此变成真实进度。

## 4. 模糊循环检测

**问题**：原有去重按 `(tool, args)` 精确匹配，模型把 `start/end` 挪几行就绕过；
一条 run 跑 1040 步、烧 6760 万 token 也没有触发。

**修复**：
- 读类工具按 **(tool, 归一化路径)** 计数。同一路径读超过 8 次 → 直接返回权威摘要
  （参考页给设计摘要；自己的交付物给交付账本），不再返回字节。
- 助手文本前缀重复 ≥3 次（如 "I'll start by checking..." 30 连）视为无进展。
- 探索预算：`write_required` 且交付物缺失时，30 分钟或 2000 万 prompt tokens 后
  自动进入 write-only（禁用只读工具）；单 run 硬上限 6000 万 prompt tokens。

## 5. 交付完整性门禁（先校验，再 done）

**问题**：`output_target_ready()` 只要目录里有任意新文件就返回就绪；".tmp_calc.py"
也算。于是模型写了个骨架 + 临时脚本后，宽容路径直接把会话标成 `done`。

**修复**（`harness/deliverable.py`）：
- 目录目标只认非临时、非隐藏的交付文件（优先 index.html，其次最新文档）；
  临时/隐藏/`.pyc/.log/.bak` 一律不计。
- HTML 校验：闭合 `</html>`、导航锚点全部有目标、标签配平、id 不重复、
  可见文字量 ≥ max(2000, 参考页可见字数 × 0.5)。
- 未通过时先回退要求修复（`DELIVERY_AUDIT_NUDGE=2` 次），仍不通过则以
  `deliverable incomplete: ...` 结束——不再伪报成功。

## 6. 交付账本（压缩后可恢复的任务状态）

LLM 写的摘要只有 400 词，装不下"12 节写了 1 节、11 个锚点悬空"这类精确状态。
每次压缩后由 harness 追加一段权威账本：每个目标的文件、字节/行数/可见字数、
已解析锚点数、缺失章节列表、本轮写过的文件、参考文件（勿重读）、当前步数。

## 7. 文档类任务的工作流与提示瘦身

`wants_document_workflow()` 识别"计划/报告/审计/按参考页出页面"类任务（而非改代码）：
- 注入 `DOCUMENT_RULES`：参考页只 digest 一次 → baseline_audit 一次 → 先在推理里
  定方案 → 一次脚本算预算 → 写骨架（含全部 nav，但不写 `</body>`）→ 逐节追加
  → web_audit/doc_consistency → 收尾。
- 跳过 Coding protocol / Two-phase discipline，去掉 dev-loop/debug-loop 技能，
  把上下文留给参考材料与计划本身。

## 8. thinking 与模型参数

`THINKING_OFF_PROVIDERS` 清空（原先含 `zhipu`）。观察到的结果是 glm 在复杂 plan/audit
任务上每步只有约 1.5 个 reasoning token；另一侧同一模型花了 9.4 万 reasoning tokens
才把架构选型和预算定下来。现在复杂任务默认 `high`，其余 `low`，QA/闲谈关闭；
provider 若拒绝 thinking/reasoning_effort 会自动逐项降级重试。

## 9. web_fetch（外部事实核验）

新增只读工具 `web_fetch`：抓取公开 http(s) 页面并转为纯文本（HTML 去脚本/样式），
用于核验许可证、模型规格、数据集规模等；**拒绝本地/私网/回环地址**（含重定向每一跳）。
失败时要求模型标注"未核验"，而不是猜。

## 10. 子代理

`SUBAGENT_MAX_STEPS` 14→40、超时 480→900 秒，工具结果按 16k 预算，
允许 `web_fetch`；仍失败时必须返回"部分发现"，不能再交给父代理一个空结果
（那是主代理重复侦察的一个已知原因）。

## 环境变量一览（新增/调整）

| 变量 | 默认 | 说明 |
|---|---|---|
| `HAOYUAN_CONTEXT_WINDOW` | 131072 | 未知模型的上下文窗口 |
| `HAOYUAN_CONTEXT_COMPACT_RATIO` | 0.55 | 轮间压缩阈值 = 窗口 × 比例 |
| `HAOYUAN_CONTEXT_HARD_RATIO` | 0.80 | 硬截断阈值 = 窗口 × 比例 |
| `HAOYUAN_TOKEN_ESTIMATE_FACTOR` | 1.8 | 启发式 token 估计校准系数 |
| `HAOYUAN_COMPACT_HYSTERESIS_STEPS` | 6 | 压缩后多少步内不再压缩 |
| `HAOYUAN_COMPACT_HYSTERESIS_RATIO` | 1.3 | 滞回允许的 body 增长倍数 |
| `HAOYUAN_TOOL_RESULT_CONTEXT_CHARS` | 16000 | 单条工具结果进入上下文的字符上限 |
| `HAOYUAN_TOOL_RESULT_MAX_BYTES` | 65536 | 工具结果原始字节上限 |
| `HAOYUAN_MAX_OUTPUT` | 32768 | 未指定时请求的输出 token 上限 |
| `HAOYUAN_LOOP_PATH_SUPPRESS_LIMIT` | 8 | 同一路径读多少次后改为返回摘要 |
| `HAOYUAN_TEXT_PREFIX_REPEAT_LIMIT` | 3 | 同样的开场白重复多少次视为无进展 |
| `HAOYUAN_EXPLORATION_MAX_SEC` | 1800 | 无交付物时的探索墙钟预算 |
| `HAOYUAN_EXPLORATION_MAX_PROMPT_TOKENS` | 20000000 | 无交付物时的探索 token 预算 |
| `HAOYUAN_RUN_MAX_PROMPT_TOKENS` | 60000000 | 单 run prompt token 硬上限 |
| `HAOYUAN_DELIVERY_AUDIT_NUDGE` | 2 | 交付物不完整的回退修复次数 |
| `HAOYUAN_DELIVERY_MIN_VISIBLE_CHARS` | 2000 | HTML/MD 交付物最小可见字数 |
| `HAOYUAN_DELIVERY_MIN_REFERENCE_RATIO` | 0.5 | 相对参考页的可见字数下限比例 |
| `HAOYUAN_SUBAGENT_MAX_STEPS` | 40 | 子代理步数 |
| `HAOYUAN_SUBAGENT_TIMEOUT` | 900 | 子代理秒数 |
| `HAOYUAN_WEB_FETCH` | 1 | 是否启用 web_fetch |
| `HAOYUAN_WEB_FETCH_MAX_CHARS` | 12000 | web_fetch 输出上限 |

渠道级：`<ENV>_CONTEXT_WINDOW`、`<ENV>_MAX_OUTPUT`（如 `ZHIPU_CONTEXT_WINDOW=200000`）。

## 行为变化提示

- 交付物"存在但不完整"现在会失败并给出原因，而不是标 `done`。
- 目录型输出目标不再把临时脚本当作交付物。
- `web_fetch` 需要外网；内网/本机地址会被拒绝。
- thinking 默认开启（复杂任务 high），token 消耗会上升，但推理与规划质量明显更好。
