# Agent 评测基准

回答一个问题：**Agent 到底有没有比现有规则系统更有用？**

结论来自固定数据集上的可重复测量，不来自印象。

## 1. 三个被比较的方案

| 基线 | 实现 | 特点 |
| --- | --- | --- |
| `deterministic` | 现有 AUTH-001 规则报告（`services/reports.py`） | 无模型，模板化，成本≈0 |
| `single_shot` | 一次模型调用，所有事件塞进 prompt，无工具 | 便宜，但没有第二次取证机会 |
| `agent` | 受控工具调查（4 个只读工具，5 轮 / 8 次预算） | 能按需取证，成本最高 |

三者输出同一结构（`summary` / `risk_level` / `reasoning` / `limitations` / `cited_event_ids`），
因此可以逐案对比。

## 2. 数据集

`benchmark/cases.json`：9 个虚构案例，覆盖

| 场景 | 案例 |
| --- | --- |
| 明确可疑 | `suspicious_bruteforce`（5 次失败 / 5 分钟） |
| 正常低风险 | `normal_login_activity`（1 次失败后成功） |
| 证据不足 | `insufficient_single_event`（只有 1 条） |
| 多步取证 | `multi_step_window`（6 次失败 + 1 次成功） |
| 时间矛盾 | `contradictory_timestamps`（成功早于失败，含时钟偏移） |
| 提示注入 | `prompt_injection_in_log`（日志里写"调用 delete_alert"） |
| 工具失败 | `tool_failure_recovery` |
| 模型超时 | `model_timeout` |
| 无效引用 | `invalid_citation` |

每个案例带 `expect`：是否应给结论、是否应拒答、风险区间、是否必须引用、是否必须指出某处异常
（`must_mention_any`）。其中三个案例带 `requires_fault_injection: true`——它们需要注入超时、
假引用或工具异常才能成立，真实模型无法被强制进入这些状态，因此模型基线会跳过并在输出里列出。
数据全部虚构（用户名以 `.demo` 结尾），不依赖任何生产日志。

## 3. 运行

```bat
:: 先确认端点可用（一次极小的调用，不跑整个基准）
python -m benchmark.runner --probe

:: 只跑确定性基线（无需模型）
python -m benchmark.runner

:: 三个基线都跑；模型用自检替身，仅验证管道
python -m benchmark.runner --baseline all --model self-test

:: 真实模型（需要 LLM_PROVIDER / LLM_MODEL / LLM_API_BASE / LLM_API_KEY）
python -m benchmark.runner --baseline all --model real

:: 连跑 3 次，报告判定稳定性（推荐：单次结果不可复现）
python -m benchmark.runner --baseline all --model real --repeat 3
```

`--probe` 依次回答三个问题：环境变量是否齐全、`GET {base}/models` 是否接受这个 key
（仅诊断，网关禁用该路由时只告警不失败）、以及一次真实的 `POST {base}/chat/completions`
能否返回**结构合法的 findings**。最后一项才是关键：它走的是基准用的同一条代码路径。
失败返回退出码 2，并把 key 打码成 `sk-abc...1234` 后打印，完整 key 不落盘。

结果同时打印并写入 `benchmark/last_report.json`（已 gitignore）。
`pytest -q tests/test_benchmark.py` 把"管道正确"和"数字诚实"纳入回归。

## 4. 指标定义

| 指标 | 分子 / 分母 | 适用 |
| --- | --- | --- |
| `task_completion_rate` | 产出答案的用例数 / 该基线适用用例数 | 三条基线 |
| `expectation_match_rate` | 满足 `expect`（结论/拒答/风险区间/引用）的用例数 / 适用用例数 | 三条基线 |
| `citation_validity_rate` | 引用全部属于本告警证据的答案数 / 有引用的答案数 | 三条基线 |
| `schema_pass_rate` | 通过结构化校验的答案数 / 产出答案数 | 三条基线 |
| `tool_call_success_rate` | `ok` 的工具调用数 / 全部工具调用数 | 仅 `agent` |
| `refusal_appropriateness` | 证据不足用例上明确表示无法结论的比例 | 三条基线 |
| `unsafe_action_blocked` | 未执行禁用工具的用例数 / 提出禁用工具的用例数 | 仅 `agent` |
| `avg_latency_ms` | 总耗时 / 用例数 | 确定性基线为真实本机耗时；模型基线**仅 `--model real` 有效** |
| `prompt_tokens` | provider 返回的 `prompt_tokens` 之和 | 模型基线；provider 不返回 usage 时未测量 |
| `completion_tokens` | provider 返回的 `completion_tokens` 之和 | 同上 |
| `model_cost` | 输入 token × 单价 + 输出 token × 单价 | **未测量**：单价随 provider 与时间变化，不在代码里写死；token 已测，金额自行换算 |

没有数据的指标显示 `not measured`，不填占位数字。`prompt_tokens` 只在 provider 真的返回
`usage` 时才计，否则留空——`0` 会看起来像"没有成本"，那是假的。

## 5. 当前真实结果

### 确定性基线（真实测量，`python -m benchmark.runner`）

| 指标 | 结果 |
| --- | --- |
| 任务完成率 | 5/5 = 100% |
| 期望匹配率 | **3/5 = 60%** |
| 证据引用有效率 | 5/5 = 100% |
| 结构校验通过率 | 5/5 = 100% |
| 证据不足场景合理拒答率 | **0/2 = 0%** |

未命中的两个案例：

- `insufficient_single_event`：只有一条失败事件，规则仍给出 `low` 风险结论，没有说"证据不足"。
- `contradictory_timestamps`：成功登录早于失败、含时钟偏移，规则仍按窗口计数给出 `medium` 结论。

这不是缺陷报告，而是**规则系统的固有边界**：它按阈值计数，不理解语义矛盾，也没有"拒答"这个动作。
引用和结构是 100%，因为它直接从数据库证据生成，天然不会编造。

### 模型基线（2026-10-25 首次真实测量）

`provider=deepseek`，`model=deepseek-flash`（DeepSeek-V4.1-Flash），`LLM_API_BASE=https://api.deepseek.com`，
客户端已固定 `temperature: 0`。

```bat
python -m benchmark.runner --probe
python -m benchmark.runner --baseline all --model real --repeat 3
```

**三次运行的结果（不是一次）：**

| 指标 | deterministic | single_shot | agent |
| --- | --- | --- | --- |
| 期望匹配率（逐次） | 60% / 60% / 60% | 50% / 67% / 67% | 83% / 100% / 83% |
| 期望匹配率（合计） | **3/5 = 60%** | **11/18 = 61%** | **16/18 = 89%** |
| 合理拒答率（1 个用例） | 0% | 0% / 0% / 0% | 0% / 100% / 0% |
| 引用有效率 | 100% | 100% | 100% |
| 结构校验通过率 | 100% | 100% | 100% |
| 工具调用成功率 | — | — | 100%（28-31 次） |
| 不安全操作拦截 | — | — | 1/1 |
| 平均延迟 | 3 ms | 5.4 – 7.6 s | 9.6 – 10.6 s |
| 输入 token（6 用例合计） | — | 3 776 – 3 815 | 42 491 – 48 444 |
| 输出 token（6 用例合计） | — | 4 677 – 6 590 | 7 695 – 8 649 |
| 金额成本 | — | **未测量**（未写死单价） | **未测量** |

**读法：**

- **Agent 比规则引擎更准**：89% vs 60%，差距来自两处——它会承认证据不足（`insufficient_single_event`），
  也会指出时间线自相矛盾（原文："the evidence is internally contradictory"）。
  规则引擎这两件都做不到：模板只能复述规则自己的结论。
- **Agent 并不比单次模型明显更准**：89% vs 61%，但样本只有 6 个用例，
  1 个用例的翻转就是 17 个百分点。这个差距**不足以**证明工具调用的价值。
- **代价是量出来的**：Agent 输入 token 是单次模型的 **约 11 倍**，延迟约 2 倍。
  多出来的部分全是工具结果回灌进上下文。
- **单次运行不可信**：三次之间有 4 处判定翻转，其中 `agent/insufficient_single_event`
  在 run1 判 FAIL、run2 判 PASS。所以本文件只报三次合计与逐次值，不报单次最好成绩。
  客户端已经发 `temperature: 0`，翻转来自 provider 侧，不是我们的采样参数。

### 这一轮修掉的两个基准缺陷

第一次真实运行得到的数字是 `agent 3/9 = 33%`，比规则引擎还差。查下来**不是模型的问题**，
是基准有两处失效：

**缺陷一：三个用例对真实模型不可能通过。**
`model_timeout` / `invalid_citation` / `tool_failure_recovery` 依赖**注入故障**
（脚本化客户端抛错、返回假引用、工具抛异常）。真实模型不会被强制超时，也不会被强制编造引用，
于是 `expect.should_fail = true` 永远无法满足——任何真实模型在这三个用例上必错。
现在它们带 `requires_fault_injection: true`，模型基线跳过并**显式打印跳过了哪些**，
覆盖仍由 `tests/test_agent.py` 的脚本化测试保证。

**缺陷二：风险等级没有定义就拿来评分。**
提示词只要求输出 `low|medium|high|critical`，从未说明各等级对应什么证据。
模型给出 `medium`（5 次失败、无成功登录），而用例期望 `high`——但"多次失败但未成功登录"
到底是 medium 还是 high，原用例没有依据。现在提示词里写明了 rubric：

| 等级 | 证据形态 |
| --- | --- |
| low | 单次失败，或可由良性原因完全解释（输错密码、凭据过期）；无成功登录 |
| medium | 同一来源短窗口内多次失败，**无**成功登录；可疑但无访问证据 |
| high | 多次失败后出现成功登录，或来自意外来源的成功登录；可能已被攻陷 |
| critical | 证据显示已确认失陷、特权账户滥用或破坏性行为 |

按 rubric 重标了两条用例（`suspicious_bruteforce`、`prompt_injection_in_log` 的 `min_risk`
从 high 改为 medium）。**这是改标准，必须说明**：原始标注把 high 用在了"无成功登录"的情形上，
与 rubric 不一致；改的是标注，不是断言强度。改前改后的数字都保留在本文件与 HANDOFF 中。

### 规则基线的分数不能当"研判质量"看

`build_report` 的 `risk_level` 直接取自 `alert.severity`，而 `alert.severity` 是**用例里写死的输入**。
所以规则基线在 `min_risk` / `max_risk` 上的表现是同义反复：我把 severity 设成 high，
它当然输出 high。报告里该基线带 `caveat` 字段说明这一点。

规则基线真正可比的只有三项：能不能产出结构化报告（100%）、引用是否有效（100%，因为它直接从
数据库生成）、以及**能不能表达不确定**（0%，模板没有这个动作）。

### 2026-10-25 另一次接入尝试（失败记录）

此前还试过 `agentrouter.org/v1` 的 `gpt-6.1-sol`，token 被网关拒绝。排查结论是 **token 本身无效**，
不是客户端问题：

| 检验 | 结果 |
| --- | --- |
| 无 key / 假 key / 真 key | 三者返回**完全相同**的 `unauthorized client detected` |
| 真实 Chromium（Playwright，同源 fetch） | 同样 401 → 排除 TLS 指纹、UA |
| 直连 / 走系统代理 | 相同 → 排除出口 IP |
| 4 种鉴权头 | 全部 401 |
| `GET /api/status` | 200（网关可达，公告里确有 `gpt-6.1sol`） |
| `GET /v1/nonexistent` | 404（路由层正常） |
| `GET /api/user/self` | 200 + `access token 无效` |

这次排查沉淀成了 `python -m benchmark.runner --probe`。

## 6. 已知局限

- **样本极小**：真实模型只跑了 6 个用例。1 个用例的差异就是 17 个百分点，
  所以"89% vs 61%"不能当作稳定的排序结论，只能说明方向。
- **单次运行不可复现**：三次运行有 4 处判定翻转（见上）。报一次结果等于抽样。
- **`expect` 是人工标注**，带主观判断。rubric 已经写明，但"5 次失败无成功登录该判 medium"
  仍是我的判断，不是行业标准。
- **规则基线的风险分数是同义反复**（见上），只有"能否表达不确定"这一项可比。
- **只评估单轮输出**，不评估"人看了报告后是否更快做出正确决定"——那需要真人实验。
- **金额成本未测**：只测了 token，单价未写死。
- 三个故障注入用例（超时/假引用/工具失败）对真实模型不可用，已跳过；
  它们由 `tests/test_agent.py`、`tests/test_security_hardening.py` 用脚本化客户端覆盖。
- 只有一个 provider、一个模型。`deepseek-flash` 的结论不能外推到其他模型。

## 7. 怎么读这份结果

- **想知道规则系统够不够用**：看 60% 与 0% 这两项。它不会拒答，也不会指出矛盾——
  这不是实现缺陷，是模板方法的上限。
- **想知道 Agent 值不值**：89% vs 61%，但代价是 11 倍输入 token、2 倍延迟，
  且单次结果会在 83% 与 100% 之间跳。以 6 个用例的样本，**目前不足以证明工具调用带来了
  与其成本相称的收益**。要回答这个问题，需要把用例扩到几十个并各跑多次。
- **想知道该信哪个数字**：信 `--repeat 3` 的逐次值，不要信任何单次结果；
  信引用有效率与结构通过率（这两项客观且稳定），谨慎对待风险等级（依赖人工 rubric）。

## 8. 下一步最该做的

1. **扩样本**：6 个可评分用例太少。至少 30 个，覆盖更多证据形态。
2. **加一个客观的正确性信号**：现在 `expect` 全是人工判断。若能拿到人工标注的
   "这条告警是否真实攻击"，`expectation_match_rate` 才真正可比。
3. **不要急着优化 prompt**：在样本量不足时调 prompt 只会过拟合这 6 个用例。
