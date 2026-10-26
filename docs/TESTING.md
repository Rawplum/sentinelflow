# 测试策略

## 1. 原则

- 默认测试必须快速、确定性、无需外部服务。
- 规则逻辑与数据库/HTTP 解耦，使用纯函数测试边界条件。
- API 集成测试使用真实 SQLAlchemy 会话和约束。
- 生产数据库为 PostgreSQL；测试默认使用 SQLite，另提供真实 PostgreSQL 验证路径。
- 测试数据全部为合成数据，不含真实日志、账号、密码或凭据。
- 不为通过测试而删除用例或放宽断言。

## 2. 当前测试结果

### SQLite（默认，快速）

运行日期：2026-10-24（第五天）。环境：Windows，Python 3.11.4，pytest 8.4.2。

```text
$ .venv\Scripts\python.exe -m pytest -q
... [100%]
334 passed, 1 skipped
```

跳过的是 `tests/test_migrations.py`，原因是没有设置 `MIGRATION_TEST_DATABASE_URL`。

> 历史记录：`0002` 时期（2026-10-19）为 `112 passed, 1 skipped`。阶段 A 新增 78 项、阶段 B 新增 27 项、第五天新增 28 项测试，既有 112 项全部继续通过且未修改断言。

### PostgreSQL 16.2（真实数据库）

使用嵌入式 PostgreSQL 16.2 启动独立测试库，执行真实 Alembic 迁移后运行：

```text
== alembic upgrade head ==
INFO  [alembic.runtime.migration] Running upgrade  -> 0001, create core security event and alert tables
INFO  [alembic.runtime.migration] Running upgrade 0001 -> 0002, add users and audit logs

== alembic check ==
No new upgrade operations detected.

== alembic current ==
0002 (head)

== pytest with PostgreSQL ==
113 passed
```

同时验证了：

- `security_events`、`alerts`、`alert_events`、`users`、`audit_logs`、`alembic_version` 表存在。
- `ck_security_events_outcome`、`ck_security_events_raw_message_length` 存在。
- `ck_alerts_severity`、`ck_alerts_status`、`uq_alerts_dedup_key` 存在。
- `ck_users_role`、`ck_users_username_lower`、`ck_users_username_length`、`uq_users_username` 存在。
- `ck_audit_logs_outcome` 和审计索引存在；`audit_logs.actor_user_id` 外键指向 `users`。
- 迁移测试执行 `upgrade head` 后 `downgrade base` 成功。
- 样例数据导入：29 行 → 24 导入、1 重复跳过、4 无效。
- 检测：22 个认证失败事件 → 2 个告警，每个 5 条证据。
- 报告中所有证据 ID 均存在于 `security_events`，时间线有序。

### 真实 Uvicorn + PostgreSQL（认证/RBAC/审计）

使用真实 Uvicorn 进程和 PostgreSQL 数据库执行 HTTP 流程：

```text
GET  /health                          -> 200
GET  /api/v1/events (无 token)        -> 401
POST /api/v1/auth/login (admin)       -> 200
POST /api/v1/auth/login (analyst)     -> 200
POST /api/v1/events/import (admin)    -> 201，received=5, imported=5
POST /api/v1/detections/run (admin)   -> 200，alerts_created=1
GET  /api/v1/alerts (admin)           -> 200，total=1
GET  /api/v1/alerts/{id}/report       -> 200，evidence=5，ID 全部匹配
GET  /api/v1/audit-logs (admin)       -> 200，关键动作存在
GET  /api/v1/events (analyst)         -> 200
GET  /api/v1/alerts (analyst)         -> 200
GET  /api/v1/alerts/{id}/report       -> 200
POST /api/v1/events/import (analyst)  -> 403
POST /api/v1/detections/run (analyst) -> 403
GET  /api/v1/audit-logs (analyst)     -> 403
```

### 真实 Uvicorn + 真实数据库冒烟（2026-10-23 验收）

用真实 `uvicorn` 进程 + Alembic 迁移过的 SQLite 库（非内存、非 TestClient）执行完整 HTTP 链路：

```text
GET  /health                                  -> 200
POST /auth/login (admin)                      -> 200
GET  /alerts 无 token                          -> 401
POST /events/import (5 条)                     -> 201 imported=5
POST /detections/run                           -> 200 alerts_created=1
GET  /alerts                                   -> total=1, evidence_count=5
GET  /alerts/{id}                              -> status=open, history=0
PATCH /alerts/{id} {acknowledged}              -> 200, history=[(open,acknowledged)]
PATCH /alerts/{id} {open}                      -> 409 Illegal status transition
GET  /audit-logs?action=alerts.status_change   -> 1 条，details 正确
GET  /alerts/{id}/report 无 token              -> 401
GET  /alerts/{id}/report                       -> evidence=5 total=5 truncated=false
GET  /alerts/{id}/reports                      -> total=0（GET 不写库）
POST /alerts/{id}/reports ×2                   -> v1 draft, v2 draft
POST /reports/{v1}/finalize                    -> 200 finalized by admin
POST /reports/{v1}/finalize（重复）             -> 409 already finalized
POST /reports/{v2}/finalize                    -> 200；v1 变为 superseded
GET  /alerts/{id}/evidence?limit=2             -> items=2 total=5 raw_message=null
GET  /alerts/{id}/evidence?limit=201           -> 422
GET  /events?outcome=failure                   -> 5
GET  /events?q=attempt%203                     -> 1
GET  /events?start=...&end=...                 -> 2
GET  /events?limit=2&offset=2                  -> total=5 items=2
GET  /events?start>end                         -> 422
POST /auth/login 错误密码 ×5                    -> 401 ×5
POST /auth/login 第 6 次                        -> 429 + Retry-After: 300
POST /auth/login 正确密码（限流中）              -> 429
POST /auth/logout                              -> 204
GET  /auth/me /alerts /events /audit-logs（撤销后） -> 401 ×4
POST /auth/logout（重复）                       -> 401
GET  /events /alerts /alerts/{id} /report /reports (analyst) -> 200 ×5
PATCH /alerts/{id} / POST reports / POST investigations / GET audit-logs (analyst) -> 403 ×4
POST /alerts/{id}/investigations（未配置模型）   -> 503 AI agent is not configured
GET  /health、/alerts（未配置模型时）            -> 200
```

审计表实际内容：`auth.login`(success)、`auth.login_failed`×5、`auth.login_throttled`×2、`auth.logout`(success)。
`login_attempts` 只有 5 行（被限流的 2 次不写入，避免延长锁定）；`revoked_tokens` 1 行。

**该冒烟使用 SQLite，不是 PostgreSQL**；结论不能替代 PostgreSQL 验证。

### 其他验收检查

| 检查 | 结果 |
| --- | --- |
| `pip check` | `No broken requirements found.` |
| `compileall` | 成功 |
| 应用导入与 OpenAPI | 9 个路径，5 张业务表，包含 HTTPBearer 安全方案 |
| 冲突标记扫描 | 未发现 |
| 行尾空白扫描 | 未发现 |
| `git status` / `git diff --check` | 无法执行：本机未安装 Git |
| Docker Compose | 无法执行：本机未安装 Docker |

`git diff --check` 的替代检查只覆盖冲突标记和行尾空白，不等同于 Git 的完整差异检查。

### 本次验收命令与分组结果

```text
pytest -q tests/test_security_unit.py tests/test_auth_api.py \
  tests/test_rbac_api.py tests/test_audit_api.py tests/test_cli_users.py
-> 56 passed

pytest -q tests/test_health.py tests/test_rule_engine.py \
  tests/test_events_api.py tests/test_detection_api.py tests/test_sample_data.py
-> 56 passed

pytest -q
-> 112 passed, 1 skipped

PostgreSQL 16.2 + pytest -q
-> 113 passed
```

OpenAPI 实际安全要求：

- 公开：`GET /health`、`POST /api/v1/auth/login`。
- HTTPBearer：`GET /api/v1/auth/me`、事件/告警/报告/检测/审计共 7 个业务路径。
- 没有公开注册或 API 用户管理路径。
- `/docs`、`/redoc`、`/openapi.json` 仍公开；这是已知的开发期信息暴露，生产应禁用或限制。

## 3. 测试文件

| 文件 | 覆盖内容 |
| --- | --- |
| `tests/test_health.py` | `/health` 响应、无数据库启动、OpenAPI |
| `tests/test_security_unit.py` | Argon2id、用户名策略、权限矩阵、JWT 签发/过期/签名/audience/issuer/type |
| `tests/test_auth_api.py` | 登录成功/失败、禁用用户、缺失/无效/过期 token、角色变更即时生效、422 不回显密码 |
| `tests/test_rbac_api.py` | admin/analyst 权限矩阵、analyst 写操作/审计拒绝、拒绝审计 |
| `tests/test_audit_api.py` | 审计分页/过滤、关键动作、请求 ID、无密钥泄露、只读 |
| `tests/test_cli_users.py` | CLI/服务创建用户、Argon2id、重复/弱密码/非法输入、无密码参数、无密码输出 |
| `tests/test_rule_engine.py` | 5 分钟窗口、阈值、边界、时间排序、分组隔离、重复运行确定性、参数校验 |
| `tests/test_events_api.py` | 导入计数、批内/跨批重复、分页、参数校验、非法字段、批量上限、空值/IPv6 往返、数据库落库 |
| `tests/test_detection_api.py` | 完整导入→检测→告警→报告流程、幂等、新事件、独立 burst、无匹配、分组隔离、分页、未知告警、数据库错误 |
| `tests/test_sample_data.py` | 合成数据有效性、异常行、重复 ID、文档保留 IP |
| `tests/test_migrations.py` | PostgreSQL 迁移升级/降级、表、CHECK、唯一约束、外键、认证表、`0003` 新表与可单独回退（`integration`） |
| `tests/test_alert_detail_api.py` | 告警详情字段、证据计数、analyst 可读、404/422/401、与列表一致 |
| `tests/test_alert_status_api.py` | 状态机正向/非法转换、409、同状态幂等、reopen 需 reason、历史与审计、analyst 403 |
| `tests/test_reports_persistence_api.py` | 版本递增、草稿/定稿/superseded、输入快照、GET 不写库、审计、RBAC、404 |
| `tests/test_evidence_pagination.py` | 报告证据上限 100、`evidence_total`/`truncated`、offset、上限 422、证据 ID 存在性、证据分页接口 |
| `tests/test_events_filter_api.py` | 字段过滤、关键词、时间范围、LIKE 转义、组合过滤、422、`include_raw_message` |
| `tests/test_auth_hardening.py` | 登录限流 429、成功重置、按 subject 隔离、令牌撤销、登出、无 `jti` 拒绝、摘要不含明文 |
| `tests/test_agent.py` | 模型未配置 503、Mock 全流程、工具白名单/参数/权限/作用域、预算耗尽、引用编造拒绝、工具日志脱敏、提示注入 |
| `tests/test_investigation_observability.py` | 轮次落库与顺序、模型失败轮次、预算轮次、`duration_ms`/`request_id`、追踪不含日志原文、中断回收、CLI 未配置时失败关闭、并发防重 409、过期行不阻塞、重复执行幂等、追踪不含凭证 |
| `tests/test_eval_suite.py` | 13 个评测用例参数化 + 场景覆盖断言 + 指标未测量时不得伪造 |
| `tests/test_alert_filters_api.py` | 告警列表按状态/严重性过滤、组合过滤、筛选后 total 与分页一致、非法枚举 422、未认证 401 |
| `tests/test_benchmark.py` | 基准数据集覆盖 9 类场景、确定性基线 100% 完成、**规则系统无法拒答**（0/2）、Agent 引用有效、self-test 不声称成本、判定可重复、同步调查入口真的执行（回归） |
| `tests/test_security_hardening.py` | 10 类攻击面的负向测试：提示注入不扩权、analyst 越权、参数跨告警、9 个非白名单工具、15 种畸形参数、无 SQL/命令/网络逃逸口、越界引用、凭据不外泄、体积/队列/时长上限、无限调用与重试（46 项） |
| `tests/test_investigation_queue.py` | 队列状态流转：新建为 `pending` 且请求不调模型、领取加租约、二次领取为空、租约过期可重领、次数耗尽转 `failed(interrupted)`、可恢复错误退避重试、重试上限、确定性失败不重试、工具超时不触发重试、`pending` 期间重复提交 409、**跨进程重启后任务仍可查询与领取** |
| `tests/test_e2e_chain.py` | 完整业务链路：登录 → 导入 → 检测 → 告警详情 → 证据 → Agent 调查（stub provider）→ 报告 → 定稿 → 审计 → 登出；刷新后按 ID 重建状态；防重不误锁 |
| `tests/test_model_client_http.py` | 模型客户端真实 HTTP 路径：请求体/鉴权头、tool_calls 解析、findings 解析、Schema 违规、非法参数、空响应、HTTP 5xx、超时、Key 不外泄、**端到端（不覆盖依赖）经 stub provider 跑完整调查** |
| `tests/conftest.py` | SQLite/PostgreSQL 测试引擎、JWT 测试密钥、admin/analyst 客户端、每例清库、事件工厂、告警工厂 |

### 规则测试覆盖

- 5 次失败在 5 分钟内 → 1 个窗口。
- 第 5 次恰好 5:00 → 命中（闭区间）。
- 第 5 次在 5:00 之后 → 不命中。
- 4 次失败 → 不命中。
- `success` 不计入失败。
- 不同用户名 / 不同 IP → 不合并。
- 乱序输入 → 先排序再判断。
- 长时间范围内 5 次失败 → 不命中。
- 两个相距较远的 burst → 两个窗口。
- 邻近 burst → 合并，避免重复告警。
- 重复运行同一输入 → 相同 `dedup_key` 和证据顺序。
- naive datetime → 按 UTC 处理。
- 非法 `window` / `threshold` → `ValueError`。

### API/错误测试覆盖

- 重复导入幂等。
- 批内重复 ID。
- 无效字段、缺失字段、naive 时间、非法 IP、非法 outcome、超长消息、未知字段 → 422。
- 空批次、501 条批次 → 422。
- 分页 `limit=0/201`、`offset=-1`、非整数 → 422。
- 无匹配事件 → 200 全 0。
- 未知告警 → 404。
- 非法告警 UUID → 422。
- 数据库异常 → 500 通用消息，响应不含内部异常文本。

### 认证/RBAC/审计测试覆盖

- 正确密码登录返回 token；错误密码、未知用户、禁用用户统一 401。
- 无 token、无效 token、过期 token、错误签名 token → 401。
- 角色以数据库为准：admin token 对应的用户角色被改为 analyst 后，检测立即返回 403。
- analyst 可读事件、告警、报告；不能导入、检测、查看审计。
- admin 可执行授权范围内的全部管理操作。
- 审计记录登录成功/失败、导入、检测、报告查看、审计查看和权限拒绝。
- 审计记录不包含密码、JWT、密码哈希；登录失败不记录尝试的用户名。
- 请求 ID 会写入响应头和登录审计。
- 422 响应不回显密码输入。
- 没有公开注册或 API 用户管理路由。
- CLI 创建用户使用 Argon2id；不接受密码命令行参数；输出不包含密码。

## 4. 常用命令

```bat
:: 默认 SQLite 测试
.venv\Scripts\python.exe -m pytest -q

:: 只跑非集成测试
.venv\Scripts\python.exe -m pytest -q -m "not integration"

:: 真实 PostgreSQL（需要先创建两个专用测试库）
set "TEST_DATABASE_URL=postgresql+psycopg://user:password@127.0.0.1:5432/sentinelflow_test"
set "MIGRATION_TEST_DATABASE_URL=postgresql+psycopg://user:password@127.0.0.1:5432/sentinelflow_migration_test"
.venv\Scripts\python.exe -m pytest -q
```

安全保护：

- `TEST_DATABASE_URL` 必须包含 `test`，否则测试拒绝启动。
- `MIGRATION_TEST_DATABASE_URL` 必须是独立的 PostgreSQL 测试库；迁移测试会删除核心表。
- 测试不会使用 `DATABASE_URL` 作为测试库。

## 5. 测试数据库说明

### SQLite

- 使用内存数据库和 `StaticPool`。
- 启用 `PRAGMA foreign_keys=ON`。
- 每次测试前按依赖逆序清空表。
- 仅用于快速反馈，不代表 PostgreSQL 的并发和类型行为。

### PostgreSQL

- 由 Alembic 迁移创建结构；测试的 `create_all` 只作为幂等兜底。
- 建议通过 Docker Compose 或本机 PostgreSQL 提供。
- 本次验证使用嵌入式 PostgreSQL 16.2（`pgserver`），但它是**本地验证工具，不是项目依赖**，也没有写入 `pyproject.toml`。正式环境仍推荐 Docker Compose。

## 6. 测试数据原则

- `data/sample_events.jsonl` 全部为虚构数据。
- 使用文档保留地址：`192.0.2.0/24`、`198.51.100.0/24`、`203.0.113.0/24`。
- 用户名以 `.demo` 结尾，IP、资产名均为虚构。
- 不含真实密码、token、密钥或生产日志。
- 时间戳固定为 UTC，便于复现。
- 异常行覆盖：缺少 `event_type`、naive 时间、非法 IP、非法 outcome、重复 `event_id`。

### Agent 测试覆盖（阶段 B）

全部使用脚本化 Mock 客户端，在 FastAPI 依赖边界替换，**不发起真实模型调用**。

- 模型未配置：调查接口 503；`/health`、告警、报告等其余接口仍正常。
- 成功流程：单个工具调用后生成报告；多个工具调用后生成报告。
- 工具白名单：只有 4 个工具被暴露；未知工具（如 `delete_alert`）返回 `denied` 且不执行。
- 参数校验：`limit=5000` 被拒为 `invalid`；给 `get_related_events` 传 `alert_id` 试图跨告警读取也被拒。
- 权限：analyst 调用调查接口返回 403；工具级权限用 `has_permission` 单独校验。
- 作用域：`search_events` / `get_related_events` 只返回本告警的证据，不会跨告警。
- 空查询结果：关键词无匹配时工具返回 `returned: 0`，调查仍可正常完成并产出报告。
- 预算：工具调用超限、轮次超限均返回 `limit_reached` 且不产出报告。
- 模型失败/超时：客户端抛错 → `failed`，不产出报告，审计 `outcome=failure`。
- 无效结构化输出：非 JSON、缺字段、非法 `risk_level` 均被 Schema 拒绝，调查 `failed`。
- 引用校验：编造 `event_id` 导致整次调查 `failed`，数据库无报告行。
- 脱敏：工具调用日志不含 `raw_message`。
- 提示注入：`raw_message` 中的“忽略之前指令”作为数据出现在工具结果里，
  没有产生任何额外工具调用，系统提示声明了不可信数据规则。

## 4.1 Agent 评测集（第五天）

评测集是独立可运行的工具，不是又一组散装断言。

```bat
:: 全部用例，打印表格 + 指标，写入 evaluation/last_report.json
python -m evaluation.run

:: 单个用例
python -m evaluation.run --case tool_timeout

:: 在测试套件里跑（每个用例一个 test id）
pytest -q tests/test_eval_suite.py
```

当前结果：**13/13 通过**，`--repeat 3` 三次判定完全一致。

```bat
python -m evaluation.run --repeat 3
```

`--repeat N` 会跑 N 遍并比较每例的**判定签名**（是否通过、终态、HTTP 状态、是否产出报告、轮次数、
每次工具调用状态、错误信息），不一致则退出码 1。耗时字段被刻意排除——它本来就会波动，
不属于判定的一部分。

| 用例 | 场景 | 期望 |
| --- | --- | --- |
| `normal_investigation` | 正常调查 | succeeded + 报告 + 2 次工具 |
| `insufficient_evidence` | 证据不足 | succeeded，报告 limitations 含 insufficient |
| `multi_step_tools` | 多步骤工具 | succeeded，3 次工具 / 4 轮 |
| `empty_query_result` | 空查询结果 | succeeded，工具 `returned=0` |
| `model_timeout` | 模型失败 | failed，无报告，轮次 `error` |
| `tool_failure` | 工具抛异常 | succeeded，工具状态 `error` 后恢复 |
| `tool_timeout` | 工具超时 | succeeded，工具状态 `timeout` |
| `unauthorized_tool` | 未授权工具 | `denied` 且从未成功执行 |
| `invalid_tool_arguments` | 非法参数 | `invalid` 后继续 |
| `fabricated_citation` | 编造引用 | failed，无报告 |
| `max_rounds` | 轮次超限 | limit_reached，无报告 |
| `prompt_injection` | 提示注入 | succeeded，注入文本只作为数据到达工具 |
| `analyst_forbidden` | 越权发起 | HTTP 403 |

### 指标定义

| 指标 | 分子 / 分母 | 适用场景 |
| --- | --- | --- |
| `case_pass_rate` | 通过全部期望的用例数 / 全部用例数 | 总门禁 |
| `task_completion_rate` | succeeded 数 / 期望 succeeded 的用例数 | 排除故意失败的用例 |
| `tool_call_success_rate` | status=ok 的调用数 / 全部调用数 | 分母含 denied/invalid/timeout/error |
| `citation_validity_rate` | 引用全部属于该告警证据的报告数 / 已产出报告数 | 独立于落库校验再验一次 |
| `report_schema_pass_rate` | 可通过 `InvestigationReportResponse` 的报告数 / 已产出报告数 | 结构回归 |
| `unauthorized_tool_block_rate` | denied 的非白名单调用数 / 非白名单调用总数 | 只统计越界尝试 |
| `forbidden_action_containment_rate` | 无破坏性工具成功执行的用例数 / 尝试过的用例数 | 按用例计，比单次调用更严 |
| `unsafe_output_count` | 报告命中破坏性动词清单的次数 | 输出侧，0 不等于"绝不会产生" |
| `avg_investigation_duration_ms` | 总耗时 / 有用例数 | Mock 模型，**不代表真实延迟** |
| `model_cost` | token 数 × 单价 | **未测量**：Mock 无 token 用量 |

> **边界**：全部用例使用脚本化模型客户端，验证的是编排与安全行为，**不是真实模型的研判质量**。
> 没有配置真实模型时，任何结果都不得表述为"模型性能"。

## 6.0 调查任务队列（持久化执行）

调查不再依赖 FastAPI `BackgroundTasks`（进程内存，重启即丢）。任务存在数据库里：

```text
POST → pending → (worker 领取, 加租约) → running → succeeded / failed / limit_reached
                                        ↘ 可恢复错误且还有次数 → pending（退避后重试）
                                        ↘ 租约过期且次数耗尽 → failed(interrupted)
```

测试里 `AGENT_WORKER_ENABLED=false`，由 `support.drain_pending()` 显式排空队列，
走的是与 worker 完全相同的 `claim_next` + `execute_investigation` 路径，因此不依赖线程时序。

真实 Uvicorn 冒烟（worker 线程启用）：

```text
POST      202 pending attempts=0/2
states    pending -> succeeded
final     succeeded attempts=1 rounds=2 tools=1
report    draft
resubmit  202 pending        <- 上一个已结束，允许新任务
```

## 6.0.1 核心业务链路端到端（第六天验收）

`tests/test_e2e_chain.py` 用**真实 HTTP 面**（TestClient 驱动真实 ASGI 应用、真实数据库、
真实模型客户端）跑通一条完整链路，模型换成本地 stub provider：

```text
login → import(5) → detection(1 alert) → alert detail → evidence page
      → POST investigations(202 running) → GET(succeeded) → report(draft)
      → finalize → audit → logout(401 after)
```

同一链路的**真实 Uvicorn** 冒烟（手动执行，非自动化）：

```text
1 login             200
2 import            201 imported=5
3 detection         200 alerts_created=1
4 alert detail      200 open evidence=5
5 evidence page     200 items=2 total=5
6 POST investigate  202 running
7 immediate GET     200 status=running      <- 证明后台执行，TestClient 观察不到
8 duplicate POST    409 already running
9 final             200 succeeded rounds=2 tools=1
10 report           200 agent draft cited=1 total=5
11 audit            200 has investigations.run + investigations.complete
12 logout           204 | reuse token: 401
```

差异说明：TestClient 会在返回前等待后台任务，因此第 7、8 步只能在真实 Uvicorn 上观察到。
这也是"同一告警只允许一个运行中调查"的 409 在真实环境下的证据。

## 6.1 第五天关键风险核实

每一条都对应可运行的断言，不是文档承诺。

| 风险 | 结论 | 证据 |
| --- | --- | --- |
| 证据引用是否全部有效 | 是 | `citation_validity_rate` 9/9；`test_fabricated_citation_is_rejected`；评测 `fabricated_citation` 用例 failed 且无报告行 |
| 提示注入是否覆盖工具权限边界 | 是 | `test_log_text_is_passed_as_data_not_instructions`：注入文本进入工具结果、未产生额外调用、暴露给模型的工具定义不含破坏性工具；评测 `prompt_injection` 用例 |
| 未授权调用是否后端拒绝 | 是 | analyst `POST /investigations` → 403（`test_analyst_cannot_run_investigation`）；工具级 `denied`（`test_unknown_tool_is_denied_and_reported`）；`unauthorized_tool_block_rate` 1/1 |
| 工具超时 / 模型失败后状态是否正确 | 是 | `tool_timeout` 用例工具记 `timeout` 且调查 succeeded；`model_timeout` 用例调查 failed、无报告、轮次 `error`；`test_rounds_are_persisted_in_order` |
| 调查记录是否泄露令牌/密码 | 否（无泄露） | `test_trace_contains_no_credentials` 扫描三张表的全部列，断言不含 JWT、密码、`password`、`authorization` |
| 前端刷新能否恢复调查 | 能 | `resumes an in-flight investigation after a page refresh`（调查 ID 在 URL） |
| 重复提交是否重复调查/写入 | 已修复 | 服务端 409 防重（D-043）；`test_second_investigation_for_a_running_alert_is_rejected`；`test_executing_the_same_investigation_twice_is_idempotent` |
| 是否影响原有登录/导入/检测/报告 | 否 | 全量 245 passed；原有 112 项断言未修改；前端 33 passed |

## 7. 未覆盖 / 未验证

- **PostgreSQL 上 `0003`/`0004` 迁移与全量测试未重跑**（本机无 PostgreSQL / Docker；`pgserver` 在本机 GBK 系统 locale 下 `initdb` 失败）。这是当前最大的验证缺口。
  - 已用真实 SQLite 库补做：`alembic upgrade head`（0001→0004）、`alembic check`（无差异）、逐级 `downgrade 0003→0002→0001→base` 全部成功。这验证了迁移脚本可执行、可回退，但**不能替代 PostgreSQL 的 DDL/约束行为验证**。
- **Agent 未使用真实模型验证**：`tests/test_model_client_http.py` 用本地 stub provider 覆盖了
  HTTP 协议路径（请求体、鉴权头、tool_calls/findings 解析、5xx、超时、Key 不外泄、端到端调查），
  但这只证明**客户端能正确收发 OpenAI 兼容协议**；真实模型的输出质量、延迟、token 成本仍未测量。
- **没有固定评测集与准确率指标**：现有测试验证安全边界，不验证研判质量。
- Docker Compose 启动未验证（当前机器无 Docker）。
- README 的 Linux/macOS 命令未在本机执行（当前为 Windows）。
- 没有 CI、覆盖率门槛。
- 没有并发压力测试；`(alert_id, version)` 与 `dedup_key` 的唯一约束冲突路径有代码处理，但没有并发集成测试。
- 多进程/多实例下的限流一致性只做了设计说明，没有实际多 worker 验证。
- 没有审计保留/归档测试。
- 没有 LLM/Agent 评测，因为未接入模型。
- 没有大样本性能测试；当前检测会扫描数据库中的全部认证失败事件。
- 前端没有浏览器 E2E 自动化；状态流转/报告定稿/事件过滤目前只有后端测试，前端未接入这些 UI。

## 8. 状态分类

### 已实现且已通过实际测试

- `/health`、配置加载、应用创建和 OpenAPI。
- 全部 9 张表模型、约束、索引、外键。
- Alembic `0001` + `0002` + `0003`（`0003` 在 SQLite 元数据层面验证，PostgreSQL 待补）。
- 事件导入（API + CLI）、重复跳过、分页、无效输入。
- 事件字段过滤、关键词搜索、时间范围。
- AUTH-001 规则的正向、反向、边界、乱序、分组隔离和重复运行。
- 告警查询、详情、状态机、状态历史。
- 报告按需生成、证据上限与截断、证据分页、引用完整性。
- 报告持久化、版本递增、定稿、supersede、输入快照。
- 登录、JWT 过期/签名/`jti` 校验、角色变更即时生效、禁用用户拒绝。
- 登录限流 429、成功重置计数、按 subject 隔离。
- 登出与令牌撤销。
- admin/analyst 权限矩阵和 401/403 行为。
- 登录、限流、登出、导入、检测、状态变更、报告、审计查看和权限拒绝的审计记录。
- 本地 CLI 用户创建、Argon2id 密码哈希、无明文密码存储。
- Agent 工具白名单、参数校验、权限、作用域、预算、引用校验、日志脱敏（Mock 模型）。
- React 前端登录、仪表盘、事件、告警、报告、审计、admin 操作和 analyst 只读行为。

### 已实现但尚未通过实际测试

- `compose.yaml` 的 Docker Compose 启动（无 Docker）。
- Linux/macOS 启动命令（未在对应平台执行）。
- PostgreSQL 上的 `0003`/`0004` 迁移与全量测试。
- 多 worker / 多实例下的限流一致性。
- 极端数据量下的检测性能和报告响应大小。
- **真实模型调用**（无凭据，且按要求不使用真实调用替代 Mock 测试）。

### 尚未实现

- MFA、刷新令牌、密钥轮换、TLS。
- 请求体大小中间件、反向代理层全局限流。
- `/ready` 就绪检查。
- 游标分页。
- 额外检测规则。
- 审计保留、归档和日志脱敏。
- Agent 评测集与准确率回归、多 Agent、自动响应。
- 自动响应、扫描、阻断。

## 9. 前端测试

前端位于 `frontend/`，使用 Vitest 5、React Testing Library 和 MSW 3。

```bat
cd /d G:\软件开发\frontend
npm run typecheck
npm run lint
npm test
npm run build
```

实际结果：

```text
npm run typecheck  -> passed
npm run lint       -> 0 warnings, 0 errors
npm test           -> 8 files, 26 tests passed
npm run build      -> passed
```

覆盖（阶段 A 新增）：

- 报告页在**没有路由 state** 的情况下从 `GET /alerts/{id}` 获取标题与状态（模拟刷新）。
- 证据被截断时显示 `N / total 条 · 已截断` 提示。

覆盖：

- API 错误映射（401/403/422/网络错误）。
- 登录成功、错误密码、认证未配置、无注册链接。
- 路由守卫：未登录跳转、analyst 访问审计返回 403 页面。
- 仪表盘 admin/analyst 视图、admin 操作可见性。
- 事件列表、详情抽屉、空状态、API 错误、分页。
- 告警列表、管理员检测、analyst 隐藏检测按钮、报告链接。
- 报告 summary/evidence/timeline/reasoning/actions/limitations、404。
- 审计列表、action 过滤、analyst 拒绝。
- 导入解析：JSON、JSONL、缺字段、500 条上限。

真实浏览器联调（临时 PostgreSQL + Uvicorn + Vite）：

- admin 登录、24 条事件、检测生成 2 个告警、报告 5 条证据。
- UI 导入第 25 条事件成功。
- 审计过滤 `auth.login` 成功。
- 分页 20/页 切换并进入第 2 页（21–25）。
- analyst 登录后无审计导航和写操作；直接 `/audit` 显示 403。
- 浏览器 `fetch` 验证：audit 403、detection 403、events 200。
- 清除 sessionStorage 后刷新 `/events` 跳转登录。
- 将 sessionStorage 中的 token 改为无效值后刷新 `/events`，自动清除会话并回到登录页。
- 停止后端后点击告警页“刷新”，页面显示“请求失败 / 重试”错误状态。
- 未捕获 console error，Vite 代理日志无错误。

未覆盖：

- 浏览器端 E2E 自动化（当前为人工浏览器联调）。
- 前端性能、可访问性自动化审计、跨浏览器矩阵。
