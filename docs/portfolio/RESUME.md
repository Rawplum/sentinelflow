# 简历项目介绍

三个版本，按投递方向选一个。**每一条都能指到代码或测试**，指不到的不要写。

---

## 版本 A：后端 / 平台方向（默认）

> **SentinelFlow — 安全日志研判平台**（个人项目 · 2026）
> Python · FastAPI · PostgreSQL · SQLAlchemy · React/TypeScript · GitHub Actions
>
> 独立设计并实现从日志导入到研判报告的完整链路：规则检测、异步 Agent 调查、
> 带引用校验的报告、版本与定稿、append-only 审计。后端 7.3k 行、前端 5.7k 行、
> 测试 7.4k 行，12 张表、6 个迁移版本。
>
> - **用数据库表实现任务队列**（租约 + 重试上限 + 卡死回收），`POST` 立即返回 202；
>   进程崩溃后任务可被重新领取。不引入 Redis/Celery，因为队列状态要和业务状态在同一个事务里。
> - **发现并修复两处并发一致性缺陷**：并发改告警状态会让状态历史链断裂、并发发起调查
>   会超发（3 个告警 × 6 个并发请求产生了 5 个任务）。用 `SELECT ... FOR UPDATE` 修复，
>   并在 PostgreSQL 上加了回归测试——SQLite 忽略该语法，所以这两项测试显式跳过并注明原因。
> - **性能优化 8.4 倍**：96k 事件生成 6000 个告警从 25.6 s 降到 3.0 s。先用 cProfile 确认
>   扫描只占 2.2 s、瓶颈在每告警 9 次往返，再改成整批 savepoint + 批量关联插入。
>   未引入缓存。
> - **定位到一个"看起来像缺索引"的问题**：批量导入后深分页 P95 515 ms，`ANALYZE` 后
>   16.7 ms。先 `EXPLAIN` 确认 SQL 本身只需 4 ms，再查 `pg_stat_user_tables` 发现统计信息过期。
> - **建立质量门禁**：ruff + mypy（109 文件 0 错误）+ 363 项后端测试 + 48 项前端测试 +
>   GitHub Actions 三个必需 job 全绿；本地与 CI 调用同一个脚本，避免两处命令漂移。

---

## 版本 B：AI Agent 工程方向

> **SentinelFlow — 受控工具调用的安全研判 Agent**（个人项目 · 2026）
> Python · FastAPI · PostgreSQL · LLM tool calling
>
> 独立实现一个受控工具调用的调查 Agent：4 个只读工具、5 轮 / 8 次调用预算、
> 180 秒运行上限、结构化 findings schema、异步任务队列。
>
> - **引用校验是核心设计**：模型结论里每个事件 id 必须属于该告警的证据集，
>   否则整次调查以 `citation_invalid` 失败。用桩模型实测：编造一个不存在的 id，
>   任务立刻失败并给出该 id——**幻觉的代价从"一份错误报告被签发"降为"任务失败"**。
> - **权限在工具层而非提示词**：工具名白名单、角色权限（复用 HTTP 层的 `has_permission`）、
>   参数 schema（`extra="forbid"`，`strict=True`）、数据作用域（`ToolContext` 只持有本告警）。
>   `ToolContext` 里没有 session factory，工具函数拿不到"查全库"的能力。
> - **做了三方对照评测**（规则 / 单次模型 / Agent，同一套 25 个用例，真实模型跑两遍）：
>   期望匹配 72% / 84% / 93%；**Agent 唯一显著优势是拒答 3/3 对 0/3**，
>   准确率差距在两次运行 5 处判定翻转的噪声内；代价是输入 token **10.7 倍**、延迟 2.2 倍。
> - **修过三次评测自身的缺陷**：三个用例依赖故障注入（真实模型不可能通过）、
>   风险等级没有定义就评分、rubric 与用例期望自相矛盾。修完 Agent 从 33% 到 93%——
>   **第一轮的分数错在基准，不在模型**。
> - **失败是结构化的**：`model_timeout` / `citation_invalid` / `budget_exhausted` /
>   `model_invalid_output` 各有错误码；轮次与工具调用逐条落库，可回放到具体哪一轮。
>   实测模型挂起时任务在 3.8 s 内以 `model_timeout` 结束，API 保持 200。

---

## 版本 C：安全研发方向

> **SentinelFlow — 检测与研判链路**（个人项目 · 2026）
> Python · FastAPI · PostgreSQL · JWT/Argon2id · RBAC
>
> 独立实现安全日志的检测、研判与审计链路，并把安全边界做成负向测试。
>
> - **检测规则与幂等**：`AUTH-001`（同一账号 + 同一来源，任意 5 分钟窗口内 ≥5 次失败），
>   滑窗 O(n)、纯函数与数据库解耦。重复导入与重复检测均幂等——
>   幂等性由 `dedup_key` 唯一约束保证，不靠应用层判断。
> - **Agent 的四层边界**：工具白名单、角色权限、参数 schema、数据作用域。
>   模型无法执行删除、SQL、文件或网络操作；请求禁用工具时在触碰参数前就被拒绝。
>   86 项安全测试覆盖注入、越权、预算、超时、引用校验。
> - **认证与审计**：JWT 含 `jti`（登出即撤销）+ Argon2id；admin/analyst 两级 RBAC，
>   analyst 只读（改状态返回 403）；登录限流按用户名 5 次 / 按 IP 20 次，第 6 次 429；
>   审计 append-only，记录动作、资源、结果、`request_id`，无 API 可修改或删除。
> - **审计报告里查得到的东西**：报告分 `draft`/`finalized`/`superseded`，定稿不可改、
>   修订建新版本、版本号在告警内唯一；证据上限 100 条并标记截断；
>   `input_snapshot` 保存报告生成时的告警与证据 id，规则或代码演进不会改写历史结论。
> - **负向实测**：6 MiB 请求体 → 413；`' OR 1=1 --`、`'; DROP TABLE ...` → 参数化查询下无效；
>   未认证访问业务接口 → 401；422 响应不含 traceback/SQL/路径；全历史扫描无硬编码密钥。

---

## 英文版（投外企或英文简历用）

> **SentinelFlow — Security log triage with a citation-checked agent** (personal project)
> Python · FastAPI · PostgreSQL · React/TypeScript
>
> End-to-end pipeline from log ingestion to an auditable finding: deterministic detection,
> an asynchronous tool-using agent, versioned reports, append-only audit. ~7.3k lines of
> backend, ~5.7k of frontend, ~7.4k of tests.
>
> - **Citation validation as the core safety property**: every event id in the model's
>   conclusion must belong to that alert's evidence set, or the whole investigation fails
>   with `citation_invalid`. Verified with a stub that fabricates an id — the task fails
>   instead of shipping a plausible-looking wrong report.
> - **Enforced boundaries, not prompted ones**: tool whitelist, role check reusing the HTTP
>   layer's permission enum, `extra="forbid"` schemas, and a `ToolContext` that holds one
>   alert and no session factory. 86 negative security tests.
> - **Database-backed job queue** (lease, retry cap, reaping) so `POST` returns 202
>   immediately and a crashed worker's task is reclaimed; queue state commits in the same
>   transaction as the report.
> - **Two concurrency bugs found by measurement, not review**: concurrent status updates
>   broke the history chain, and six simultaneous POSTs created five investigations for one
>   alert. Fixed with `SELECT ... FOR UPDATE`; regression tests run on PostgreSQL only
>   because SQLite ignores the clause.
> - **8.4× on detection** (25.6 s → 3.0 s for 6000 alerts over 96k events) by batching writes,
>   after profiling showed the scan itself was 2.2 s. No cache added.
> - **Three-way evaluation** (rules / single-shot / agent, 25 synthetic cases, real model run
>   twice): 72% / 84% / 93% expectation match, but the agent's only significant edge is
>   refusing when evidence is insufficient (3/3 vs 0/3), at 10.7× the input tokens. Reported
>   as ranges, because 5 of 44 verdicts flipped between identical runs.

---

## 怎么选

| 投什么 | 用哪个版本 | 强调什么 | 别强调什么 |
| --- | --- | --- | --- |
| 后端 / 平台 | A | 队列、并发、性能、门禁 | 评测准确率（会被追问标注质量） |
| AI Agent | B | 引用校验、边界、三方对照 | 性能数字（与岗位无关） |
| 安全研发 | C | 检测、RBAC、审计、负向测试 | Agent 准确率（会显得像 AI 项目） |
| 通用后端（大厂） | A + B 各取 2 条 | 并发缺陷 + 引用校验 | 前端细节 |

---

## 三条不要写

1. **不要写"准确率 93%"**。要写"93%，但 22 个用例、一个人标注、两次运行 5 处翻转"。
   前者经不起一次追问，后者本身就是加分项。
2. **不要写"高并发"**。这个项目单进程单 worker，多副本没验证过。
   写"并发一致性缺陷"可以（那是真的修了），写"支撑高并发"不行。
3. **不要写"生产级"**。没有 TLS、没有 MFA、没有审计归档、没有容量验证。
   写"可演示、可交接的 V1.0 发布候选"。

---

## 一句话版本（自我介绍时用）

> 我做过一个安全日志研判系统：规则先标出可疑登录，然后一个受控的 Agent 去查日志、
> 写结论，但它引用的每个事件 id 都必须真实存在，编造一个整次调查就失败。
> 我还给它做了三方对照评测——结论是 Agent 比单次调用模型贵 10 倍 token，
> 准确率分不出高下，唯一赢的地方是它敢说"证据不足"。
