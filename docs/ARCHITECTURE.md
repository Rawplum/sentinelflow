# SentinelFlow 架构

## 1. 架构风格

当前采用**模块化单体**：单个 FastAPI 进程，按职责分层，共享一个 PostgreSQL 数据库。该选择适合本地开发和首期功能验证，避免在需求尚未稳定时引入微服务、消息队列或 Kubernetes。

```text
HTTP 客户端（curl / OpenAPI UI / 后续前端）
        │  JSON over HTTP + Bearer JWT（业务接口）
        ▼
FastAPI 路由层  src/sentinelflow/api/routes/
        │  请求校验、认证依赖、统一权限检查
        ▼
业务服务层      src/sentinelflow/services/
        │  导入、规则、告警、报告、认证、审计
        ▼
数据访问层      src/sentinelflow/models/ + db/
        │  SQLAlchemy 2.x 同步会话
        ▼
PostgreSQL 16
```

## 2. 当前模块职责

| 路径 | 职责 | 状态 |
| --- | --- | --- |
| `src/sentinelflow/main.py` | 创建 FastAPI 应用、注册路由、请求 ID、422/认证配置/数据库错误处理 | 已实现 |
| `src/sentinelflow/core/config.py` | 读取环境变量和 `.env`，JWT 配置 | 已实现 |
| `src/sentinelflow/core/permissions.py` | admin/analyst 角色与权限映射 | 已实现 |
| `src/sentinelflow/core/security.py` | Argon2id、JWT、用户名/密码策略 | 已实现 |
| `src/sentinelflow/core/time.py` | UTC 时间归一化 | 已实现 |
| `src/sentinelflow/api/deps.py` | Bearer 认证、当前用户、统一权限依赖 | 已实现 |
| `src/sentinelflow/api/routes/health.py` | `GET /health`（公开） | 已实现 |
| `src/sentinelflow/api/routes/auth.py` | 登录、当前用户 | 已实现 |
| `src/sentinelflow/api/routes/events.py` | 事件导入与分页查询 | 已实现 |
| `src/sentinelflow/api/routes/detections.py` | 运行 AUTH-001 | 已实现 |
| `src/sentinelflow/api/routes/alerts.py` | 告警列表、详情、状态流转、证据分页、报告生成与版本创建 | 已实现 |
| `src/sentinelflow/api/routes/reports.py` | 持久化报告读取与定稿 | 已实现 |
| `src/sentinelflow/api/routes/audit.py` | 管理审计查询 | 已实现 |
| `src/sentinelflow/schemas/` | Pydantic 请求/响应模型 | 已实现 |
| `src/sentinelflow/models/` | `SecurityEvent`、`Alert`、`User`、`AuditLog`、`InvestigationReport`、`AlertStatusHistory`、`RevokedToken`、`LoginAttempt`、`alert_events` | 已实现 |
| `src/sentinelflow/services/events.py` | 幂等导入、字段过滤与关键词查询 | 已实现 |
| `src/sentinelflow/services/detection.py` | 纯规则函数与数据库检测编排 | 已实现 |
| `src/sentinelflow/services/alerts.py` | 告警查询、详情、状态机与历史 | 已实现 |
| `src/sentinelflow/services/reports.py` | 确定性报告生成与证据分页 | 已实现 |
| `src/sentinelflow/services/investigation_reports.py` | 报告版本、输入快照、定稿与 supersede | 已实现 |
| `src/sentinelflow/services/auth.py` | 登录、登录限流、令牌撤销、用户创建 | 已实现 |
| `src/sentinelflow/services/audit.py` | 审计写入与查询 | 已实现 |
| `src/sentinelflow/cli/import_events.py` | JSONL 本地导入 | 已实现 |
| `src/sentinelflow/cli/create_user.py` | 本地用户创建（交互式密码） | 已实现 |
| `src/sentinelflow/ai/` | 模型客户端、工具白名单、单 Agent 编排 | 已实现（Phase 2 最小版本） |
| `migrations/` | Alembic 环境；`0001_core_tables`、`0002_users_and_audit`、`0003_reports_status_and_security`、`0004_investigations`（当前 head `0004`） | 已实现 |
| `tests/` | 规则、认证、RBAC、审计、API、迁移测试 | 已实现 |

设计原则：

- 路由层只做 HTTP 相关转换，不直接写 SQL。
- 业务规则放在服务层，便于脱离 HTTP 测试。
- 数据一致性由服务层事务边界控制。
- 不为当前不需要的能力创建空模块；目录随功能落地而增加。

## 3. 当前请求流

### 3.1 健康检查

```text
GET /health
  → api/routes/health.py
  → core/config.py::get_settings()
  → schemas/health.py::HealthResponse
  → 200 JSON
```

`/health` 是**存活检查**，不访问数据库。数据库不可用时它仍应返回 200。`/ready` 尚未实现。

### 3.2 认证与权限

```text
POST /api/v1/auth/login
  → services/auth.py::authenticate_and_issue_token()
      → 用户名归一化
      → Argon2id 校验（未知用户也执行 dummy hash）
      → 签发 HS256 JWT（sub/role/iat/exp/iss/aud/type）
      → 写 auth.login / auth.login_failed 审计
  → 200 token

受保护请求
  → api/deps.py::get_current_user()
      → HTTPBearer
      → 校验签名、exp、iss、aud、type
      → 从数据库加载用户
      → 用户不存在或禁用 → 401
  → api/deps.py::require_permission(permission)
      → 使用数据库中的当前 role
      → 允许或 403 + authorization.denied 审计
  → 路由
```

`/health` 和 `/login` 公开；其他业务接口默认拒绝匿名访问。JWT 中的 role 仅用于排障，授权以数据库为准。没有公开注册接口，用户通过本地 CLI 创建。

### 3.3 事件导入

```text
POST /api/v1/events/import
  → Pydantic EventImportRequest（1–500 条，字段/时间/IP/长度校验）
  → services/events.py::import_events()
      → 批内按 event_id 去重
      → 一次查询已存在的 event_id
      → 插入新事件并提交
      → 若发生唯一键竞争：回滚后逐条重试，冲突计为 skipped
  → 201 {received, imported, skipped, skipped_event_ids}
```

事件导入**不会自动运行检测**；检测必须显式调用 `/api/v1/detections/run`。

### 3.4 确定性检测

```text
POST /api/v1/detections/run
  → services/detection.py::run_detection()
      → 查询 authentication/login/failure 事件，按时间排序
      → 纯函数 find_suspicious_login_windows()
          → 按 (username, source_ip) 分组
          → 5 分钟闭区间、阈值 5
          → 合并邻近窗口
      → 查询已存在的 dedup_key
      → 嵌套事务创建 Alert + alert_events
      → 唯一约束冲突计为 skipped_existing
  → 200 {events_scanned, windows_detected, alerts_created, ...}
```

关键约束：

- 规则是确定性的，不调用 LLM。
- 事件按时间戳排序，不依赖插入顺序。
- 不同用户名或来源 IP 不合并。
- 重复运行同一批数据不新增告警。
- 当前规则扫描全部认证失败事件，尚未做增量或时间范围优化。

### 3.5 调查报告

```text
GET /api/v1/alerts/{alert_id}/report        （按需生成，只读）
  → services/reports.py::build_report()
      → 统计证据总数（SQL COUNT，不加载全部行）
      → 按 (timestamp, event_id) 取一页证据（上限 100）
      → 校验返回的 evidence event_id 仍存在于数据库
      → 生成 summary / timeline / reasoning / actions / limitations
      → evidence_total + evidence_truncated
  → 200 InvestigationReportResponse

POST /api/v1/alerts/{alert_id}/reports      （持久化草稿）
  → services/investigation_reports.py::create_report_version()
      → build_report() 生成当前内容
      → next_version() 计算下一个版本号
      → input_snapshot 冻结告警字段与证据 ID
      → content 冻结渲染结果
      → 唯一约束 (alert_id, version) 保证并发安全
  → 201 draft

POST /api/v1/reports/{report_id}/finalize
  → 同告警先前 finalized 的版本改为 superseded
  → 当前版本置为 finalized + 定稿人/时间
```

关键约束：

- `GET /alerts/{id}/report` **永不写入**（只产生 `reports.view` 审计），因此刷新页面不会创建版本。
- 报告证据数组有硬上限（100），并始终返回 `evidence_total` 与 `evidence_truncated`。
- 定稿后不可原地修改；修订必须创建新版本，旧版本自动 `superseded`。
- `input_snapshot` 是**创建时的快照**，之后数据库中的事件行可能变化，二者不保证一致。

### 3.7 告警状态流转

```text
PATCH /api/v1/alerts/{alert_id}   (admin, alerts:write)
  → services/alerts.py::change_status()
      → 同状态 → 幂等 no-op（不写历史）
      → 查 ALLOWED_TRANSITIONS，非法 → InvalidStatusTransitionError → 409
      → closed → open 必须带 reason，否则 → 422
      → 更新 alerts.status + 追加 alert_status_history
  → record_audit("alerts.status_change")
  → db.commit()   # 状态、历史、审计同一事务
```

合法转换：`open → acknowledged | investigating | closed`；`acknowledged → investigating | closed`；`investigating → closed`；`closed → open`（需 reason）。

### 3.8 登录限流与令牌撤销

```text
POST /api/v1/auth/login
  → check_login_throttle()        # 先于 Argon2 校验，避免被用于算力放大
      → 维度 1：(username, source_ip) 5 次失败 / 5 分钟
      → 维度 2：source_ip 20 次失败 / 5 分钟
      → 超限 → 429 + Retry-After，写 auth.login_throttled 审计
  → 校验密码
  → 失败：写 login_attempts（HMAC 摘要）+ auth.login_failed
  → 成功：清除该 subject 的失败计数，签发带 jti 的 token

受保护请求
  → decode_access_token()（要求 jti）
  → is_token_revoked(jti)         # 每请求一次数据库查询
  → 已撤销 → 401

POST /api/v1/auth/logout
  → 写入 revoked_tokens(jti, expires_at)，不保存 token 本身
```

**限流器部署限制**：计数器存放在 `login_attempts` 表，而不是进程内存。因此同一数据库下的多 worker / 多实例共享计数，不会因进程重启丢失。代价是每次登录多一次读 + 一次写；如果数据库不可用，登录会失败（fail-closed）。该实现**不防护**能直接写数据库的攻击者，也不能替代反向代理层的全局限流。

### 3.6 审计

```text
登录 / CLI 用户创建 / 权限拒绝
  → 写审计并在同一事务提交

事件导入 / 检测执行
  → service(commit=False) 完成业务写入
  → 写审计
  → 路由统一 commit

报告查看 / 审计查看
  → 完成读取
  → 写审计并提交
```

审计只记录非敏感上下文，不保存密码、JWT、密码哈希或完整 raw_message。登录失败不记录尝试的用户名。

## 4. 跨模块约束

- 路由层不直接写 SQL。
- 认证和权限检查只通过 `api/deps.py` 的统一依赖。
- 业务 service 不依赖 HTTP；认证/审计通过显式参数或独立 service 组合。
- 审计表应用层 append-only，没有更新/删除 API。
- 现有事件导入、规则判断和报告内容不因认证/审计改变。

## 5. Agent 模块（Phase 2 最小版本）

> 权限边界、威胁模型与残余风险见 `docs/SECURITY.md`。本节只描述数据流。

```text
POST /api/v1/alerts/{alert_id}/investigations   (admin, reports:write)
  → 写入 investigations(status=pending) 并提交
  → 202 Accepted（请求不调用模型，慢 provider 不会拖垮 HTTP）
  → 审计 investigations.run（queued=true）

investigation worker（进程内单线程，随 lifespan 启停）
  → claim_next(): 条件 UPDATE 领取一条
       条件：status=pending 且 (next_attempt_at 为空或已到)
             或 status=running 且租约过期且 attempt_count < max_attempts
       效果：status=running, attempt_count+1, lease_expires_at=now+LEASE
  → execute_investigation()
      → ai/tools.py::build_context()          # 只读上下文 + 证据 ID 集合
      → ai/agent.py::run_agent()
          → ai/model_client.py::complete()    # 唯一的模型出口
          → 每个 tool_call:
              → TOOL_SPECS 白名单查找         # 未注册 → denied，不碰参数
              → Pydantic 严格校验             # 失败 → invalid
              → has_permission(角色, 工具权限) # 失败 → denied
              → ThreadPoolExecutor + timeout  # 超时 → timeout
              → 只读查询（复用 services 层）
          → 结论必须通过 AgentFindings Schema
          → 引用校验：cited_event_ids ⊆ 本告警证据，否则整次失败
      → create_report_version(generator='agent')  # 只产出 draft（已有 report_id 则跳过）
      → 记录 investigation_rounds / investigation_tool_calls（含 attempt_index）
      → 终止：succeeded / failed / limit_reached，或回 pending（仅可恢复错误且还有次数）
      → 审计 investigations.complete

GET /api/v1/investigations/{id}   (admin/analyst, reports:read)
  → 安全网：running 且租约过期 → 回收为 failed(interrupted)
  → 返回 status + attempt_count + error_code + rounds + tool_calls + duration_ms
  → 人工审核 → POST /reports/{id}/finalize
```

### 5.1 为什么是"数据库 + 租约"，而不是 Redis / Celery

项目是单节点部署，数据库本来就在。用一张表当队列，成本最低且没有新增运维面：

| 方案 | 结论 |
| --- | --- |
| FastAPI `BackgroundTasks` | **不可靠**：任务只活在进程内存里，进程一死就丢；也无法在重启后恢复 |
| 数据库 + 租约（当前实现） | 任务落库、领取原子、崩溃可恢复；无需额外组件 |
| Redis / Celery | 能解决，但要新增一个必须运维、必须备份、必须做高可用的组件，对单节点是净负担 |

具体机制：

- **领取**：条件 `UPDATE ... WHERE id=? AND <claimable>`，用 `rowcount==1` 判定成功。
  不依赖 `SELECT ... FOR UPDATE SKIP LOCKED`，因此 PostgreSQL 与 SQLite 同一套代码。
- **租约**：领取时写 `lease_expires_at`。worker 死了租约自然过期，任务重新可领。
- **重试**：只对可恢复错误（传输/超时/5xx/429）回 `pending` 并退避；`attempt_count >= max_attempts` 后转 `failed`。
  确定性失败（Schema 违规、引用无效、预算耗尽）不重试，避免烧 token 换同一个结果。
- **幂等**：`execute_investigation` 只处理 `status=running` 的任务；报告创建前检查 `report_id is None`，
  所以重复投递不会产出第二个报告版本。
- **不会永久 running**：租约过期 + 次数耗尽 → `failed(interrupted)`；GET 也有一层同样的安全网。

已知局限（有意接受）：

- worker 随进程启停，**不是**独立部署的消费者；多副本部署时每个进程都会起一个 worker，
  条件 UPDATE 保证不会重复领取，但吞吐不会随副本线性增长。
- 没有优先级、延迟队列、死信队列；失败任务靠 `error_code` 与审计排查。
- 任务执行期间进程被强杀，最多浪费一次 `attempt`。

### 5.2 评测

```text
python -m evaluation.run
  → evaluation/harness.py
      → 播种告警 + 脚本化模型客户端（tests/support）
      → POST 调查 → 轮询 GET → 校验终态/工具/引用/安全行为
  → evaluation/metrics.py 计算 10 项指标（分母、适用场景见 docs/TESTING.md）
  → 写 evaluation/last_report.json，失败时退出码 1
```

评测用例通过真实 HTTP 接口执行，与生产路径一致；模型在依赖边界被替换，因此**不产生真实模型调用，也不衡量模型质量**。

### 5.3 模型配置

| 变量 | 说明 |
| --- | --- |
| `LLM_PROVIDER` | 提供方标识，写入 `investigations.model_provider` |
| `LLM_MODEL` | 模型名 |
| `LLM_API_BASE` | OpenAI 兼容 base URL（代码只访问这个地址） |
| `LLM_API_KEY` | API Key，`SecretStr`，不写日志、不入库 |
| `LLM_TIMEOUT_SECONDS` | 单次模型调用超时 |
| `AGENT_MAX_ROUNDS` / `AGENT_MAX_TOOL_CALLS` / `AGENT_TOOL_TIMEOUT_SECONDS` | 预算 |
| `AGENT_WORKER_ENABLED` | 是否启动队列 worker（测试里设为 false，手动排空） |
| `AGENT_WORKER_POLL_SECONDS` | 队列轮询间隔 |
| `AGENT_LEASE_SECONDS` | 领取租约时长，需大于单次运行的最坏耗时 |
| `AGENT_MAX_ATTEMPTS` | 领取次数上限，超过即失败 |
| `AGENT_RETRY_BACKOFF_SECONDS` | 重试退避 |

模型客户端使用标准库 `urllib`，不引入额外运行时依赖。错误信息只包含异常类型，不包含请求内容或 Key。

## 6. 配置与运行

- 配置来自环境变量，可通过 `.env` 提供本地值。
- `DATABASE_URL` 可选：应用启动和 `/health` 不依赖数据库。
- `JWT_SECRET` 必须至少 32 字符；缺失或过短时认证接口返回 503，业务接口失败关闭。
- `ACCESS_TOKEN_EXPIRE_MINUTES` 默认 30，范围 5–1440。
- 数据库使用 `postgresql+psycopg://` URL 和同步 psycopg 3 驱动。
- 本地 Uvicorn 监听 `127.0.0.1:8000`，Compose 中的 PostgreSQL 监听 `127.0.0.1:5432`。
- 后端**没有配置 CORS 中间件**。前端在开发期通过 Vite 代理（`/api`、`/health` → `127.0.0.1:8000`）访问，因此不需要 CORS；生产部署必须使用同源反向代理，或显式配置受信来源（不能使用 `*` 搭配凭据）。

## 7. 错误处理

- 输入错误由 Pydantic/FastAPI 返回 422；自定义处理器移除 `input`/`ctx`，避免回显敏感输入。
- 缺少/无效/过期 token 返回 401，带 `WWW-Authenticate: Bearer`。
- 已认证但权限不足返回 403。
- `JWT_SECRET` 缺失或过短返回 503。
- 资源不存在返回 404。
- 非法的告警状态转换返回 409；对已定稿报告重复定稿返回 409。
- 登录失败次数超限返回 429，并带 `Retry-After` 头。
- 数据库异常由全局 `SQLAlchemyError` 处理器返回 500 和通用消息，不泄露 SQL、堆栈或驱动细节。
- 当前使用 FastAPI 默认错误结构 `{"detail": ...}`。
- `409 Conflict` 用于告警状态转换和报告版本冲突。
- 生产模式必须关闭 `DEBUG`，避免泄露内部信息。

## 8. 安全边界

- 已实现 JWT 认证（含 `jti`）、admin/analyst RBAC、append-only 审计、登录限流和令牌撤销。
- 服务仍应绑定回环地址：TLS、MFA、刷新令牌和审计保留尚未实现。
- `.env` 不入库；`.env.example` 只含占位符；JWT 密钥只来自环境变量。
- 数据库只监听 `127.0.0.1`（Compose 配置）。
- 所有 SQL 通过 SQLAlchemy 参数化，禁止字符串拼接 SQL；关键词搜索转义 `%` 和 `_`。
- 已实现的上限：单批 500 条、`raw_message` 8192 字符、分页 `limit` 1–200、报告证据 100 条、证据分页 200 条。
- 事件列表与证据分页支持 `include_raw_message=false` 以避免返回不必要的原始消息；报告接口仍包含 `raw_message`（保持兼容）。
- 尚未实现请求体大小中间件和反向代理层限流。
- 审计记录已实现，但没有保留/归档策略；部署前需要补齐。
- `/docs`、`/redoc`、`/openapi.json` 默认公开，生产环境应禁用或限制。
- 依赖版本需要定期审查已知漏洞。

## 9. 部署拓扑（当前）

```text
本机
├── uvicorn (127.0.0.1:8000)
└── PostgreSQL 16
    └── Docker Compose（推荐）或本机实例，绑定 127.0.0.1:5432
```

本次验证使用临时嵌入式 PostgreSQL 16.2，因为当前机器没有 Docker。Compose 文件已提供但尚未运行验证。

不引入反向代理、Kubernetes、消息队列或独立缓存。需要这些组件时，必须先有可量化的性能或可靠性依据。

测试环境：

```text
pytest
├── 默认：SQLite 内存库（快速反馈）
└── 可选：TEST_DATABASE_URL → PostgreSQL
    └── MIGRATION_TEST_DATABASE_URL → 独立迁移测试库
```

## 10. 架构演进触发条件

- 事件吞吐超过单进程同步处理能力 → 先做批量写入和索引优化，再考虑异步任务。
- 规则评估耗时影响接入延迟 → 拆分为后台任务，但仍可保持单体部署。
- Agent 调用需要长耗时 → 引入任务队列和任务状态表。
- 需要多租户 → 在数据模型和授权层统一加入 tenant 边界，而不是事后补丁。

## 11. 前端控制台（当前）

前端是独立 `frontend/` 单页应用，不进入 FastAPI 进程：

```text
React 19 + TypeScript
  ├── React Router 7             # /login、/dashboard、/events、/alerts、/report、/audit
  ├── AuthContext                # token、用户、角色、过期计时、401 登出
  ├── Axios client               # Bearer header、错误归一化
  ├── TanStack Query             # 列表分页、缓存、导入/检测后失效
  └── CSS Modules/global tokens  # 统一布局、表格、徽章、时间线
        │
        ▼
Vite dev proxy (/api, /health) → FastAPI 127.0.0.1:8000 → PostgreSQL
```

边界：

- 前端只调用现有 REST API，不直接访问数据库。
- 前端路由守卫和按钮隐藏只改善体验；后端 `require_permission` 是授权边界。
- Token 在浏览器 `sessionStorage` 中保存，仅适用于本地演示；生产应使用 HttpOnly Cookie、CSP 和令牌撤销。
- 后端未配置 CORS，开发通过 Vite 代理；生产需要同源反向代理或显式 CORS。
- 前端不模拟后端未实现的能力：告警状态更新、报告定稿、搜索/字段过滤、独立告警详情均不提供假操作。

页面数据来源：

| 页面 | 数据/操作 |
| --- | --- |
| 仪表盘 | `GET /events`、`GET /alerts`、`GET /audit-logs`（admin） |
| 事件 | `GET /events`、`POST /events/import`（admin） |
| 告警 | `GET /alerts`、`POST /detections/run`（admin） |
| 报告 | `GET /alerts/{id}/report` |
| 审计 | `GET /audit-logs`（admin） |
