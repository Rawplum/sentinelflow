# 交接说明

最后更新：2026-10-23

状态：阶段 A（报告持久化/版本、证据上限、告警详情与状态流转、登录限流与令牌撤销、事件过滤、文档与前端修复）、阶段 B（受控单 Agent 调查）与第五天（Agent 评测集、调查过程追踪、前端调查闭环）均已完成，SQLite 测试 318 passed / 1 skipped，前端 40 passed。**PostgreSQL 上的 `0003`–`0006` 迁移验证待补做；Agent 未做真实模型调用验证。** 仍只建议本地使用。

## 1. 项目目标与技术栈

SentinelFlow 是 AI 辅助的安全事件研判与响应平台。当前确定性基线：

```text
登录 → 导入合成安全日志 → AUTH-001 规则生成告警 → 查询证据 → 生成结构化调查报告 → 审计
```

技术栈：

| 组件 | 版本/约束 |
| --- | --- |
| Python | 3.11.4（要求 ≥3.11） |
| FastAPI | 0.148.0（约束 `>=0.115,<1.0`） |
| Pydantic / pydantic-settings | 2.14.1 / 2.16.0 |
| SQLAlchemy | 2.1.5（同步） |
| psycopg | 3.3.6（binary） |
| Alembic | 1.20.0 |
| PyJWT | 2.15.1 |
| argon2-cffi | 25.1.0 |
| PostgreSQL | 16（验证版本 16.2） |
| pytest / httpx2 | 8.4.2 / 2.14.0 |
| React / TypeScript | 19.3.1 / 6.0.3 |
| Vite / React Router / Axios | 8.3.5 / 7.18.4 / 1.20.0 |
| TanStack Query | 5.104.5 |
| Vitest / RTL / MSW | 5.0.5 / 16.3.3 / 3.0.3 |
| Node.js / npm | 24.20.0 / 11.19.0（文档记录值）；**本机实测 22.22.2 / 10.9.7**，测试仍通过 |
| SQLite | 仅用于快速测试，不是部署目标 |

## 1.1 验收速查（2026-10-23 最终验收）

### 数据模型与迁移

| 迁移 | 内容 |
| --- | --- |
| `0001_core_tables` | `security_events`、`alerts`、`alert_events` |
| `0002_users_and_audit` | `users`、`audit_logs` |
| `0003_reports_status_and_security` | `investigation_reports`、`alert_status_history`、`revoked_tokens`、`login_attempts` |
| `0004_investigations` | `investigations`、`investigation_tool_calls` |

当前 head：`0004`。全部为纯增量迁移，可逐级回退。

### 报告版本与定稿规则

- 同一告警的版本号从 1 递增，`(alert_id, version)` 唯一。
- 状态只有 `draft` / `finalized` / `superseded` 三种。
- **定稿后没有任何接口可以修改其内容**：报告路由只有 `GET` 和 `POST /finalize`，没有 `PUT`/`PATCH`。
- 同一告警最多一个 `finalized`；新版本定稿时，旧版本自动转 `superseded`。
- 已定稿或已取代的版本再次定稿返回 409。
- `GET /alerts/{id}/report` 始终按需生成、不写库；只有 `POST /alerts/{id}/reports` 才创建版本。
- 证据上限 100 条，响应固定带 `evidence_total` / `evidence_truncated`。

### 登录限流与令牌撤销

- 限流维度：`(username, source_ip)` 5 次失败 / 5 分钟；`source_ip` 20 次失败 / 5 分钟。超限 429 + `Retry-After`。
- 计数存 `login_attempts` 表，按 HMAC 摘要存储，不保存明文用户名或 IP；成功登录清除该 subject 的失败计数。
- 限流检查发生在密码校验**之前**，避免被用作 Argon2 算力放大器。
- 被限流的请求不会延长锁定时间（避免持续请求永久锁死账户）。
- **局限**：不能防护能直接写数据库的攻击者；不能替代反向代理层全局限流；数据库不可用时登录 fail-closed；多 worker 一致性只有设计说明，没有实测。
- 令牌带 `jti`；登出写入 `revoked_tokens`（只存 `jti`/`user_id`/`expires_at`/`reason`），每请求校验一次。
- **一次性影响**：不带 `jti` 的旧 token 会被拒绝，最长 30 分钟（默认过期时间）。

### Agent 工具与限制

| 工具 | 参数上限 | 权限 | 说明 |
| --- | --- | --- | --- |
| `get_alert_details` | 无参数 | `alerts:read` | 告警字段、证据总数、状态历史 |
| `get_related_events` | `limit` 1–50、`offset` ≥0 | `alerts:read` | 分页读本告警证据 |
| `search_events` | `keyword` ≤100、`outcome`、`action`、`limit` 1–50 | `alerts:read` | 仅在本告警证据内检索 |
| `search_runbooks` | `query` 1–100、`limit` 1–5 | `reports:read` | 本地离线语料 `data/runbooks.json` |

- 预算：最多 5 轮、8 次工具调用、单工具 5 秒超时（均可通过 `AGENT_*` 调整）。
- 安全边界：白名单查找在读取参数前完成；Pydantic `extra="forbid"`；权限用 `has_permission` 按数据库角色判断；查询作用域锁死在本告警；工具全部只读；Agent 不能改状态、不能定稿、不能执行处置。
- 结论必须匹配固定 Schema，`cited_event_ids` 必须全部属于该告警真实证据，否则整次 `failed` 且不产出报告。
- 工具调用日志只存参数、状态、耗时和结果摘要，不存 `raw_message`、提示词或模型原文。

### 模型配置（不含密钥）

```text
LLM_PROVIDER          提供方标识
LLM_MODEL             模型名
LLM_API_BASE          OpenAI 兼容 base URL
LLM_API_KEY           API Key（SecretStr，不入库、不写日志）
LLM_TIMEOUT_SECONDS   默认 30
AGENT_MAX_ROUNDS      默认 5
AGENT_MAX_TOOL_CALLS  默认 8
AGENT_TOOL_TIMEOUT_SECONDS 默认 5
```

未配置时 `POST /alerts/{id}/investigations` 返回 503，其余接口不受影响。

## 2. Git 状态

- **仓库已初始化**：2026-10-23 执行 `git init`，当前分支 `main`。
- Git 版本：`2.55.0.windows.3`。
- **没有任何提交**：`git log` 为空（`your current branch 'main' does not have any commits yet`）。
- **13 个顶层未跟踪条目，暂存区为空**：`.env.example`、`.gitignore`、`README.md`、`alembic.ini`、`compose.yaml`、`data/`、`docs/`、`evaluation/`、`frontend/`、`migrations/`、`pyproject.toml`、`src/`、`tests/`。
- **未 stage、未 commit**：验收过程只做过一次 `git add -N` + `git reset` 以运行 `git diff --check`，索引已恢复为空。
- `git diff --check`：**通过（exit 0）**。修复了 14 个前端文件末尾多余空行后重跑通过。
- `.gitignore` 覆盖：`.env`、`.env.*`（保留 `.env.example`）、`.venv/`、`__pycache__/`、`.pytest_cache/`、`.workbuddy-ai/`；`frontend/.gitignore` 覆盖 `node_modules`、`dist`。
- 已扫描：项目内不存在 `.env`、`.pem`、`.key` 等真实凭据文件，只有 `.env.example` 占位符。
- 建议：`git add -A && git commit` 建立基线后再继续开发。

## 3. 当前环境

| 项目 | 状态 |
| --- | --- |
| 操作系统 | Windows（win32 10.0.22631 x64） |
| Python | 3.11.4 |
| 虚拟环境 | `.venv/`，已安装依赖和两个 CLI 命令 |
| Node.js / npm | 便携版 24.20.0 / 11.19.0（位于用户目录，用于前端） |
| 前端依赖 | `frontend/node_modules/` 已安装 |
| Git | 已安装 2.55.0.windows.3（§2 为真实状态） |
| Docker / Compose | 未安装 |
| 本机 PostgreSQL | 未安装 |
| 验证用 PostgreSQL | 临时嵌入式 PostgreSQL 16.2（`pgserver`，不是项目依赖） |

## 4. 目录结构与主要模块

```text
G:\软件开发\
├── src/sentinelflow/
│   ├── main.py                     # 应用工厂、路由、请求 ID、422/503/500 处理
│   ├── core/
│   │   ├── config.py               # Settings、DATABASE_URL、JWT 配置
│   │   ├── permissions.py          # admin/analyst 角色与权限映射
│   │   ├── security.py             # Argon2id、JWT、用户名/密码策略
│   │   └── time.py                 # UTC 归一化
│   ├── api/
│   │   ├── deps.py                 # Bearer 认证、当前用户、统一权限依赖
│   │   └── routes/
│   │       ├── health.py           # 公开
│   │       ├── auth.py             # login / me
│   │       ├── events.py           # 导入、分页
│   │       ├── detections.py       # 运行 AUTH-001
│   │       ├── alerts.py           # 告警、报告
│   │       └── audit.py            # 审计查询（admin）
│   ├── schemas/                    # events/alerts/auth/audit 等
│   ├── models/
│   │   ├── security_event.py
│   │   ├── alert.py                # alerts + alert_events
│   │   ├── user.py                 # users
│   │   └── audit_log.py            # audit_logs
│   ├── services/
│   │   ├── events.py               # 幂等导入（可选 commit）
│   │   ├── detection.py            # 规则 + 检测编排（可选 commit）
│   │   ├── alerts.py
│   │   ├── reports.py
│   │   ├── auth.py                 # 登录、用户创建
│   │   └── audit.py                # 审计写入/查询
│   ├── db/session.py
│   └── cli/
│       ├── import_events.py        # sentinelflow-import
│       └── create_user.py          # sentinelflow-create-user
├── migrations/versions/
│   ├── 0001_core_tables.py
│   ├── 0002_users_and_audit.py
│   ├── 0003_reports_status_and_security.py
│   ├── 0004_investigations.py
│   ├── 0005_investigation_rounds.py
│   └── 0006_investigation_queue.py
├── tests/                          # 规则/认证/RBAC/审计/API/迁移
├── frontend/
│   ├── src/api/                    # Axios client、类型、错误处理
│   ├── src/auth/                   # 会话、AuthContext、路由守卫
│   ├── src/components/             # layout / ui / domain
│   ├── src/pages/                  # 登录、仪表盘、事件、告警、报告、审计
│   ├── src/__tests__/              # Vitest + RTL + MSW
│   ├── package.json
│   ├── vite.config.ts              # /api 与 /health 代理
│   └── README.md                   # 前端使用说明
├── data/sample_events.jsonl
├── docs/
├── compose.yaml
├── alembic.ini
├── pyproject.toml
├── .env.example
└── .gitignore
```

## 5. 已完成功能与测试状态

### 已实现且已通过实际测试

| 功能 | 测试证据 |
| --- | --- |
| `/health`、配置、应用导入、OpenAPI | pytest + 真实 Uvicorn |
| 12 张表（含 `investigation_rounds`） | SQLite |
| Alembic `0001`–`0006` 升级/降级 | 真实 SQLite（PostgreSQL 待补） |
| `alembic check` 无模型/迁移差异 | `No new upgrade operations detected` |
| 本地 CLI 创建 admin/analyst | Argon2id、无密码参数、无密码输出 |
| 登录、JWT 过期/签名/issuer/audience/type 校验 | pytest |
| 无 token/无效 token/过期 token → 401 | pytest |
| admin/analyst 权限矩阵 | pytest |
| analyst 导入/检测/审计 → 403 | pytest + 真实 HTTP |
| 角色变更/禁用用户即时生效 | pytest |
| 登录、导入、检测、报告查看、审计查看、权限拒绝审计 | pytest + 真实 HTTP |
| 审计不保存密码/JWT/哈希，登录失败不保存用户名 | pytest |
| 请求 ID 写入响应头和审计 | pytest |
| 422 不回显输入 | pytest |
| 原有事件导入/规则/报告业务回归 | pytest |
| React 登录、仪表盘、事件、告警、报告、审计 | Vitest + RTL + MSW；真实浏览器联调 |
| 前端 admin 导入/检测、analyst 只读 | 浏览器联调 + 后端 403 fetch 验证 |
| 前端分页、错误/空状态、刷新后登录跳转 | 浏览器联调 + Vitest |

实际测试结果（累计，最新数字见 5.1 第五天验收结果）：

- 全量 SQLite：`318 passed, 1 skipped`（迁移测试因未设置 PostgreSQL URL 跳过）。
- 既有 112 项测试全部继续通过，**未修改任何既有断言**。
- 阶段 A 新增 78 项：告警详情、状态机、报告版本、证据分页、事件过滤、登录限流与令牌撤销。
- 阶段 B 新增 27 项：Agent 白名单、参数校验、权限、作用域、预算、引用校验、日志脱敏、提示注入、模型失败/超时、非法结构化输出、空查询结果、失败审计。
- 前端：`npm run typecheck` 通过；`npm run lint` 0 warnings；`npm test` **33 passed**（第五天验收时的实际值）；`npm run build` 通过。
- `alembic heads` → `0006 (head)`。
- **迁移已用真实数据库验证**：在 SQLite 库上 `upgrade head`（0001→0004）、`alembic check` 无差异、逐级 `downgrade 0003→0002→0001→base` 成功（base 后仅剩 `alembic_version`）。
- **真实 Uvicorn + 迁移过的 SQLite 库冒烟通过**：登录、401、导入、检测、告警详情、状态 409、审计、报告 v1/v2、定稿 409、superseded、证据分页、事件过滤、限流 429、登出撤销 401、analyst 403、Agent 未配置 503。明细见 `docs/TESTING.md`。
- `git diff --check` → **exit 0**（修复 14 个前端文件末尾空行后）。
- **未执行**：PostgreSQL 迁移与全量测试、真实模型调用。

### 已实现但尚未通过实际测试

- Docker Compose 启动（本机无 Docker）。
- Linux/macOS 命令（本机为 Windows）。
- 使用本机已有 PostgreSQL 的部署路径（本次使用嵌入式 PostgreSQL）。
- 并发检测、唯一约束并发路径。
- 大样本性能、超大报告响应。
- MFA、刷新令牌、TLS、审计保留（尚未实现）。

### 尚未实现

- 刷新令牌、MFA、TLS、密钥轮换。
- 请求体大小中间件、反向代理层全局限流。
- `/ready` 就绪检查。
- 游标分页。
- 审计保留/归档、日志脱敏。
- `/docs`、`/redoc`、`/openapi.json` 的生产访问控制。
- 前端已提供 AI 调查闭环，但**仍不提供**告警状态操作、报告创建/定稿、搜索与字段过滤 UI。
- 前端令牌保存在 sessionStorage，仅为演示；生产应使用 HttpOnly Cookie 等方案。
- 更多检测规则。
- Agent 评测集与准确率回归、真实模型调用验证、多 Agent、自动响应。

### 阶段 B（2026-10-23）新增与修改

新增：

```text
src/sentinelflow/ai/__init__.py
src/sentinelflow/ai/model_client.py        # 唯一模型出口，标准库 urllib
src/sentinelflow/ai/tools.py               # 4 个只读白名单工具 + 超时 + 权限
src/sentinelflow/ai/agent.py               # 单 Agent 循环、预算、引用校验
src/sentinelflow/models/investigation.py
src/sentinelflow/schemas/investigations.py
src/sentinelflow/services/investigations.py
src/sentinelflow/api/routes/investigations.py
migrations/versions/0004_investigations.py
data/runbooks.json                         # 本地离线 runbook 语料
tests/test_agent.py                        # 27 项，全部 Mock 模型
```

修改：

```text
src/sentinelflow/core/config.py            # LLM_* / AGENT_* 配置
src/sentinelflow/models/__init__.py
src/sentinelflow/main.py                   # 注册路由 + ModelNotConfiguredError → 503
src/sentinelflow/services/reports.py       # evidence_query 公开供工具复用
tests/test_migrations.py                   # 0004 断言与逐级回退
.env.example                               # LLM_* 与 AGENT_* 占位
README.md、docs/API_SPEC.md、docs/ARCHITECTURE.md、docs/DATA_MODEL.md、
docs/DECISIONS.md、docs/PLAN.md、docs/TESTING.md、docs/HANDOFF.md
```

### 阶段 A 已修复的历史遗留问题

- `services/reports.py` 中过期的 `limitations` 文案（原称“认证和访问控制尚未实现”）已改为当前事实。
- `ReportPage.tsx` 不再依赖 `location.state`：改为通过 `GET /alerts/{id}` 获取标题、状态与历史，刷新和分享链接都能正确渲染。
- `ARCHITECTURE.md` 中“当前没有浏览器前端/不提供 CORS”的矛盾描述已更正。
- `PROJECT_SPEC.md` 中“未实现 RBAC”“React 应用属于非目标”的过时表述已更正。
- `AlertsPage.tsx` 不再向报告页传递 `state`，页脚不再声称“后端未提供状态修改接口”。


## 本次认证/RBAC/审计新增与修改

### 新增

```text
src/sentinelflow/core/permissions.py
src/sentinelflow/core/security.py
src/sentinelflow/models/user.py
src/sentinelflow/models/audit_log.py
src/sentinelflow/schemas/auth.py
src/sentinelflow/schemas/audit.py
src/sentinelflow/services/auth.py
src/sentinelflow/services/audit.py
src/sentinelflow/api/deps.py
src/sentinelflow/api/routes/auth.py
src/sentinelflow/api/routes/audit.py
src/sentinelflow/cli/create_user.py
migrations/versions/0002_users_and_audit.py
tests/test_security_unit.py
tests/test_auth_api.py
tests/test_rbac_api.py
tests/test_audit_api.py
tests/test_cli_users.py
```

### 修改

```text
pyproject.toml
.env.example
src/sentinelflow/core/config.py
src/sentinelflow/models/__init__.py
src/sentinelflow/main.py
src/sentinelflow/api/routes/events.py
src/sentinelflow/api/routes/detections.py
src/sentinelflow/api/routes/alerts.py
src/sentinelflow/services/events.py
src/sentinelflow/services/detection.py
tests/conftest.py
tests/test_events_api.py
tests/test_detection_api.py
tests/test_migrations.py
README.md
docs/API_SPEC.md
docs/ARCHITECTURE.md
docs/DATA_MODEL.md
docs/DECISIONS.md
docs/PLAN.md
docs/PROJECT_SPEC.md
docs/TESTING.md
docs/HANDOFF.md
```

Git 未安装，无法提供真实 diff 或提交记录；上述清单是人工核对的工作区变更。

## 本次前端新增与修改

### 新增

```text
frontend/package.json
frontend/package-lock.json
frontend/vite.config.ts
frontend/tsconfig*.json
frontend/index.html
frontend/.env.example
frontend/README.md
frontend/src/main.tsx
frontend/src/App.tsx
frontend/src/api/{client,types,errors,auth,events,detections,alerts,audit}.ts
frontend/src/auth/{authState,useAuth,AuthContext,RequireAuth,RequireAdmin,tokenStorage}
frontend/src/components/layout/{AppShell,Sidebar,Topbar,PageHeader}.tsx
frontend/src/components/ui/{Button,Card,Badge,DataTable,Drawer,Modal,Pagination,Spinner,EmptyState,ErrorState,FormField}.tsx
frontend/src/components/domain/{Badges,EventDetail,EvidenceTable,Timeline,AuditDetails,ImportEventsModal,RunDetectionButton}.tsx
frontend/src/pages/{LoginPage,DashboardPage,EventsPage,AlertsPage,ReportPage,AuditPage,ForbiddenPage,NotFoundPage}.tsx
frontend/src/hooks/usePagination.ts
frontend/src/lib/{constants,format,parseEvents}.ts
frontend/src/styles/{tokens,global}.css
frontend/src/__tests__/*.test.ts(x)
frontend/src/test/{setup.ts,msw/*,utils.tsx}
frontend/public/favicon.svg
```

### 修改

```text
README.md
docs/HANDOFF.md
```

## 阶段 A（2026-10-23）新增与修改

### 新增

```text
src/sentinelflow/models/investigation_report.py
src/sentinelflow/models/alert_status_history.py
src/sentinelflow/models/revoked_token.py
src/sentinelflow/models/login_attempt.py
src/sentinelflow/services/investigation_reports.py
src/sentinelflow/api/routes/reports.py
migrations/versions/0003_reports_status_and_security.py
tests/test_alert_detail_api.py
tests/test_alert_status_api.py
tests/test_reports_persistence_api.py
tests/test_evidence_pagination.py
tests/test_events_filter_api.py
tests/test_auth_hardening.py
```

### 修改

```text
src/sentinelflow/core/config.py            # 限流参数
src/sentinelflow/core/permissions.py       # alerts:write / reports:write / reports:finalize
src/sentinelflow/core/security.py          # jti、token_expires_at
src/sentinelflow/models/__init__.py        # 注册新模型
src/sentinelflow/schemas/alerts.py         # 详情/状态/证据分页/报告版本
src/sentinelflow/schemas/events.py         # raw_message 可空
src/sentinelflow/services/alerts.py        # 详情、SQL 计数、状态机
src/sentinelflow/services/reports.py       # 证据上限、truncated、过期文案
src/sentinelflow/services/events.py        # 字段过滤与关键词
src/sentinelflow/services/auth.py          # 限流、撤销、登出
src/sentinelflow/api/deps.py               # 每请求撤销校验
src/sentinelflow/api/routes/alerts.py      # 详情/状态/证据/报告版本
src/sentinelflow/api/routes/auth.py        # 429、logout
src/sentinelflow/api/routes/events.py      # 过滤参数
src/sentinelflow/main.py                   # 注册 reports 路由
tests/conftest.py                          # alert_factory、密码 fixture
tests/test_migrations.py                   # 0003 断言与单独回退
frontend/src/api/types.ts
frontend/src/api/alerts.ts
frontend/src/pages/ReportPage.tsx          # 改为真实 API，移除 location.state
frontend/src/pages/AlertsPage.tsx          # 移除 state 传递、修正页脚
frontend/src/components/domain/EvidenceTable.tsx
frontend/src/test/msw/handlers.ts
frontend/src/__tests__/ReportPage.test.tsx
README.md
docs/API_SPEC.md
docs/ARCHITECTURE.md
docs/DATA_MODEL.md
docs/DECISIONS.md
docs/PLAN.md
docs/PROJECT_SPEC.md
docs/TESTING.md
docs/HANDOFF.md
```


## 5.1 第五天（2026-10-24）：评测、可观测性与前端闭环

### 新增

```text
evaluation/__init__.py
evaluation/cases.json                      # 13 个用例
evaluation/harness.py                      # 播种 + 脚本化模型 + 期望校验
evaluation/metrics.py                      # 10 项指标（含 not measured 语义）
evaluation/run.py                          # CLI：表格 + JSON 报告 + 退出码
migrations/versions/0005_investigation_rounds.py
src/sentinelflow/cli/investigate.py        # 打印单次调查的轮次/工具追踪
tests/support/__init__.py                  # 共享脚本化模型客户端
tests/test_investigation_observability.py
tests/test_eval_suite.py
frontend/src/api/investigations.ts
frontend/src/components/domain/InvestigationPanel.tsx
frontend/src/__tests__/InvestigationFlow.test.tsx
```

### 修改

```text
src/sentinelflow/ai/agent.py               # RoundRecord + 每轮耗时 + 总耗时
src/sentinelflow/services/investigations.py# 拆分 create/execute、中断回收、轮次落库
src/sentinelflow/api/routes/investigations.py # 202 + 后台任务 + 完成审计 + 中断回收
src/sentinelflow/models/investigation.py   # InvestigationRound + request_id/duration_ms
src/sentinelflow/schemas/investigations.py # rounds / duration_ms / request_id
src/sentinelflow/core/config.py            # AGENT_STALE_AFTER_SECONDS
pyproject.toml                             # sentinelflow-investigate
tests/test_agent.py                        # 适配 202 + 轮询；审计改为 run + complete
tests/test_migrations.py                   # 0005 断言与单独回退
frontend/src/api/{types,alerts}.ts、src/pages/ReportPage.tsx、src/styles/global.css
frontend/src/test/msw/handlers.ts
README.md、docs/API_SPEC.md、docs/ARCHITECTURE.md、docs/DATA_MODEL.md、
docs/DECISIONS.md、docs/PLAN.md、docs/TESTING.md、docs/HANDOFF.md
```

### 关键行为变化

- 调查改为**异步**：`POST` 返回 `202` + `running`，前端轮询 `GET`。（第七天已升级为持久化队列，见 5.3 / D-045）
- 新增 `investigation_rounds`，记录每轮 `latency_ms` / `outcome` / 工具数；`investigations` 增加 `request_id`、`duration_ms`。
- `running` 超过 `AGENT_STALE_AFTER_SECONDS`（默认 600）在读取时回收为 `failed`（见 D-041）。
- 审计拆为 `investigations.run`（入队）与 `investigations.complete`（终态）。
- 前端在报告页内启动调查，调查 ID 写入 URL（`?investigation=`），刷新可恢复轮询。
- **服务端防重**：同一告警已有未过期 `running` 调查时 `POST` 返回 `409`（D-043），双击/重放不会产生第二个调查或第二个报告版本。


### 第五天验收结果（2026-10-24）

| 检查 | 结果 |
| --- | --- |
| 后端全量 | `318 passed, 1 skipped` |
| Agent / 可观测性 / 评测 / 认证 RBAC 分组 | `97 passed` |
| 评测集 | `13/13 passed`；`--repeat 3` 判定一致 |
| 前端 | `33 passed / 9 files`；typecheck 通过；lint 0 warnings；build 通过 |
| 迁移 | 真实 SQLite：6 级 upgrade、`alembic check` 无差异、6 级 downgrade 至 base，head `0006` |
| `git diff --check` | exit 0 |

评测指标（Mock 模型，**不代表真实模型性能**）：

| 指标 | 实测 |
| --- | --- |
| `case_pass_rate` | 13/13 = 100% |
| `task_completion_rate` | 9/9 = 100% |
| `tool_call_success_rate` | 11/15 = 73.3%（分母含故意失败的调用） |
| `citation_validity_rate` | 9/9 = 100% |
| `report_schema_pass_rate` | 9/9 = 100% |
| `unauthorized_tool_block_rate` | 1/1 = 100% |
| `forbidden_action_containment_rate` | 1/1 = 100% |
| `unsafe_output_count` | 0 |
| `avg_investigation_duration_ms` | 6.3（Mock，不可作为性能结论） |
| `model_cost` | **not measured** |

本轮验收发现并修复的问题：**同一告警可并发创建多个调查**（双击/重放会产生第二个调查与第二个报告版本）。
已加服务端 409 防重（D-043），过期 `running` 行不阻塞新调查，并补 4 项测试覆盖防重、幂等与凭证卫生。

### 可重复性

```bat
python -m evaluation.run --repeat 3
```

比较每例的判定签名（通过与否、终态、HTTP 状态、是否产报告、轮次数、每次工具调用状态、错误信息），
不一致则退出码 1。实测 `3/3 runs identical verdicts`。耗时被排除，因为它本来就波动。

### 模型客户端的真实 HTTP 路径

`tests/test_model_client_http.py` 用**本地 stub provider**（不是真实模型）覆盖此前完全没测过的代码：
请求体与鉴权头、`tool_calls`/`findings` 解析、Schema 违规、非法参数、空响应、HTTP 5xx、超时、
错误信息不泄露 API Key，以及**不覆盖依赖的端到端调查**（生产客户端 → HTTP → stub → 报告落库）。

这证明客户端能正确收发 OpenAI 兼容协议，**不能**证明任何真实模型的输出质量、延迟或成本。

### 命令

```bat
pytest -q tests/test_security_hardening.py
python -m evaluation.run
python -m evaluation.run --repeat 3
pytest -q tests/test_eval_suite.py
pytest -q tests/test_model_client_http.py
pytest -q tests/test_e2e_chain.py
sentinelflow-investigate --alert-id <uuid>
```


## 5.2 第六天（2026-10-24）：核心链路连通性验收

目标不是加功能，而是确认模块之间真的接上了。

### 新增

```text
tests/test_e2e_chain.py            # 一条测试跑完整业务链路
tests/support/stub_provider.py     # 可复用的本地 OpenAI 兼容 stub
frontend/src/__tests__/auditActions.test.ts
```

### 修复的不一致

- **前端审计动作清单是旧的**：后端早已发出 `alerts.status_change`、`reports.create/read/finalize`、
  `investigations.run/complete`、`auth.login_throttled`、`auth.logout`，但前端的筛选下拉和中文标签
  只覆盖 9 个旧动作。后果是管理员在审计页**无法按新动作筛选**，且新动作显示英文原始名。
  已补全 `AUDIT_ACTIONS` / `AUDIT_ACTION_LABELS`，并加测试锁住后端动作集合与前端目录的一致性。

### 真实 Uvicorn 链路冒烟（手动，非自动化）

```text
login 200 → import 201(5) → detection 200(1 alert) → detail 200(open,5)
→ evidence 200(2/5) → POST investigations 202(running)
→ 立即 GET 200(running)  ← 后台执行证据，TestClient 观察不到
→ 重复 POST 409 → 终态 succeeded(rounds=2, tools=1)
→ report 200(agent/draft, cited=1/5) → audit 含 run+complete
→ logout 204 → 复用 token 401
```

### 说明

`tests/test_e2e_chain.py` 覆盖同一链路，但 TestClient 会等待后台任务，因此**"running 可观测"和
"409 防重"只能在真实 Uvicorn 上验证**。两者互补，不可互相替代。


## 5.3 第七天（2026-10-24）：调查任务持久化队列

### 问题

此前调查跑在 FastAPI `BackgroundTasks` 里。它把任务放在**进程内存**：进程一死任务就没了，
既不持久化也不能恢复，**不能算任务队列**。同时 `POST` 会在请求内跑完整个调查，
provider 一慢就顶到 HTTP 超时。

### 方案（不引入 Redis/Celery）

`investigations` 表本身即队列：

```text
POST → pending → worker 条件 UPDATE 领取（attempt_count+1, lease_expires_at=now+LEASE）
     → running → succeeded / failed / limit_reached
              ↘ 可恢复错误且 attempt_count < max_attempts → pending（next_attempt_at 退避）
              ↘ 租约过期且次数耗尽 → failed(error_code=interrupted)
```

- **领取原子性**：`UPDATE ... WHERE id=? AND <claimable>`，`rowcount==1` 才算领到。
  不用 `FOR UPDATE SKIP LOCKED`，PostgreSQL / SQLite 同一套代码。
- **崩溃恢复**：租约过期即重新可领；次数用完转 `failed(interrupted)`。GET 还有一层同样的安全网。
- **重试边界**：只有传输错误 / 超时 / 5xx / 429 重试（`ModelClientError.retryable`）；
  Schema 违规、引用无效、预算耗尽属于确定性失败，重试只会烧 token。
- **幂等**：`execute_investigation` 只处理 `running`；报告创建前检查 `report_id is None`，
  重复投递不会产出第二个报告版本。
- **worker**：进程内单线程，随 lifespan 启停；`AGENT_WORKER_ENABLED=false` 可关闭（测试即如此）。

### 新增/修改

```text
新增  src/sentinelflow/services/investigation_worker.py   # claim_next / reap_expired / process_one / run_worker
新增  migrations/versions/0006_investigation_queue.py
新增  tests/test_investigation_queue.py                   # 11 项
修改  src/sentinelflow/models/investigation.py            # pending + 队列字段 + attempt_index
修改  src/sentinelflow/ai/model_client.py                 # ModelClientError.retryable
修改  src/sentinelflow/ai/agent.py                        # error_code / retryable
修改  src/sentinelflow/services/investigations.py         # pending 入队、重试、报告去重、完成审计
修改  src/sentinelflow/api/routes/investigations.py       # 去掉 BackgroundTasks
修改  src/sentinelflow/main.py                            # lifespan 启停 worker
修改  src/sentinelflow/core/config.py                     # AGENT_WORKER_* / LEASE / MAX_ATTEMPTS / BACKOFF
修改  frontend  InvestigationPanel / types                 # pending 状态与重试次数展示
```

### 实现过程中真实踩到的 bug

重试第二次时 `investigation_rounds` 插入失败：唯一约束是 `(investigation_id, round_index)`，
而重试又从第 1 轮开始。已加 `attempt_index`，约束改为三列（D-046）。
`alembic check` 还抓出索引列没跟着改的漂移，一并修正。

### 状态机与接口

| 状态 | 含义 | 终态 |
| --- | --- | --- |
| `pending` | 已入队，等待领取（或退避等待重试） | 否 |
| `running` | 已被领取并持有租约 | 否 |
| `succeeded` | 有结论且引用全部有效 | 是 |
| `failed` | 模型/校验失败、被中断、上下文缺失 | 是 |
| `limit_reached` | 轮次或工具调用预算耗尽 | 是 |

`GET /investigations/{id}` 额外返回 `attempt_count`、`max_attempts`、`error_code`、`started_at`。

### 验证

```text
后端  pytest -q                     → 272 passed, 1 skipped
队列  pytest -q tests/test_investigation_queue.py → 12 passed
前端  npm test                     → 40 passed / 11 files
迁移  upgrade 6 级 → check 无差异 → downgrade 6 级 → 仅剩 alembic_version
真机  POST 202 pending → states: pending -> succeeded（worker 线程领取）
      final succeeded attempts=1 rounds=2 tools=1；resubmit 202（上一个已结束）
```


## 5.4 第八天（2026-10-24）：Agent 权限边界安全加固

威胁模型、控制清单与残余风险见 **`docs/SECURITY.md`**（新增）。这里只记改动与结论。

### 审计发现的三处真实缺口（已修复）

| 缺口 | 后果 | 修复 |
| --- | --- | --- |
| **租约 120s < 最坏运行 190s** | 健康但慢的一次运行会丢失租约，被判定 interrupted 或被第二个 worker 重复执行 | 新增 `AGENT_MAX_RUNTIME_SECONDS=180` 在循环内强制；租约改 240s；配置层校验 `lease > runtime`，不满足则启动失败 |
| **请求体无大小上限** | 超大 JSON 在 Schema 校验前就被解析，可打满内存 | 中间件按 `Content-Length` 拒绝，返回 413；上限 5 MiB |
| **工具数值参数非 strict** | `{"limit": "5"}` / `{"limit": true}` 会被强制转成 5 / 1（类型混淆） | `Field(strict=True)`，直接判 `invalid` |

另加：队列深度上限 `AGENT_MAX_PENDING=50`，超出返回 **429** + `Retry-After`。

### 负向测试

`tests/test_security_hardening.py`（46 项），逐条对应 `SECURITY.md` 的 12 类控制：

- 提示注入：注入文本确实进入模型上下文，但工具集合不变、无额外调用；`DROP TABLE` 字符串不生效。
- 越权：analyst 发起调查 / 改状态 / 建报告 / 读审计 全部 403。
- 作用域：给工具传 `alert_id`（含其他告警）→ `invalid`；结果永远只含本告警事件。
- 白名单：9 个非注册工具名（含 `execute_sql`、`run_shell`、`../etc/passwd`）全部 `denied`。
- 参数：15 种畸形输入（字符串/布尔/浮点/越界/超长/错误类型/非对象）全部 `invalid`。
- 逃逸口：静态断言 `tools.py` 不含 `subprocess`/`eval`/`exec`/`import text`/HTTP 客户端。
- 引用：引用**别的告警**的真实 event_id 同样失败。
- 泄露：调查/轨迹/审计三张表全列扫描，无 token、无密码、无 `sk-`。
- 限制：413、429、运行时上限、工具调用上限、重试上限。

### 明确声明

提示词不是控制手段。即使模型被日志完全说服，它能做的仍然只有 4 个只读工具，
参数必须通过 Schema、权限与作用域检查。这一点由测试而非文档保证。

## 6. 环境准备、数据库、用户、启动和测试

### 安装

```bat
cd /d G:\软件开发
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
```

### 配置

```bat
copy .env.example .env
notepad .env
```

必须配置：

- `DATABASE_URL`
- `JWT_SECRET`（至少 32 字符，无默认值）

生成密钥：

```bat
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 迁移

```bat
docker compose up -d db
alembic upgrade head
alembic current
alembic check
```

当前 head：`0005`。

回滚到认证前：`alembic downgrade 0001`，会删除 `audit_logs` 和 `users`，不影响事件和告警数据。
只回滚阶段 A：`alembic downgrade 0002`，会删除 `investigation_reports`、`alert_status_history`、`revoked_tokens`、`login_attempts`，不影响既有业务表。

回滚认证/审计迁移（会删除 `users` 和 `audit_logs`，不影响事件/告警数据）：

```bat
alembic downgrade 0001
```

回滚阶段 A 新增（只删 4 张新表，不动 `users` / `audit_logs` / 业务表）：

```bat
alembic downgrade 0002
```

### 创建用户

```bat
sentinelflow-create-user --username admin --role admin
sentinelflow-create-user --username analyst1 --role analyst
```

密码通过交互式输入，不接受命令行密码参数。没有公开注册接口。

### 启动与登录

```bat
uvicorn sentinelflow.main:app --reload --host 127.0.0.1 --port 8000
```

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<your-password>"}'
```

业务请求使用：

```bash
-H "Authorization: Bearer <access_token>"
```

### 前端启动

需要 Node.js LTS（当前验证 Node 24.20.0）：

```bat
cd /d G:\软件开发\frontend
npm install
copy .env.example .env
npm run dev
```

打开 `http://127.0.0.1:5173`。Vite 将 `/api` 和 `/health` 代理到 `127.0.0.1:8000`。前端详细说明见 `frontend/README.md`。

### 测试

```bat
:: 后端 SQLite
pytest -q

:: 后端 PostgreSQL
set "TEST_DATABASE_URL=postgresql+psycopg://user:password@127.0.0.1:5432/sentinelflow_test"
set "MIGRATION_TEST_DATABASE_URL=postgresql+psycopg://user:password@127.0.0.1:5432/sentinelflow_migration_test"
pytest -q

:: 前端
cd frontend
npm run typecheck
npm run lint
npm test
npm run build
```

测试 conftest 会设置测试用 JWT 密钥；不要复用生产密钥。测试库名称必须包含 `test`。

## 7. 已知问题、安全风险和阻塞事项

### 阻塞

1. **PostgreSQL 验证缺口**：本机无 PostgreSQL 也无 Docker，`pgserver` 在 GBK 系统 locale 下 `initdb` 失败。`0003`/`0004` 已在真实 SQLite 库验证升级/降级，但 PostgreSQL 的 DDL、CHECK/唯一约束和类型行为仍未验证。
2. **Git 无提交**：仓库已初始化，但没有任何 commit，改动无法用 `git diff` 追溯。
3. **生产加固未完成**：TLS、MFA、刷新令牌、密钥轮换、审计保留均未实现。

### 安全风险（按优先级）

1. **检测全表扫描认证失败事件**（中）：数据增长后性能下降。
2. **请求体大小无中间件限制**（中低）：超大 JSON 在 Schema 拒绝前被解析。
3. **审计无保留策略、日志可能含敏感参数**（中低）。
4. **无 TLS/MFA/刷新令牌/密钥轮换**（中）：生产部署前必须补齐。
5. **限流为应用层数据库实现**（中低）：不能防护能写库的攻击者，建议反向代理再加一层。
6. **`/docs`、`/redoc`、`/openapi.json` 默认公开**：暴露 API 结构；生产应禁用或限制。

### 已确认的安全事实

- 密码使用 Argon2id，数据库中没有明文密码。
- JWT 密钥只来自 `JWT_SECRET`，代码中没有默认密钥；token 携带唯一 `jti`。
- 授权使用数据库当前角色；禁用用户和角色变更立即生效。
- 没有公开注册或 API 用户管理接口。
- 审计不保存密码、JWT、哈希或完整 raw_message；登录失败与被限流均不记录用户名。
- 登录限流表只保存 HMAC 摘要，不保存明文用户名或 IP。
- 令牌撤销表只保存 `jti` 与过期时间，不保存 token。
- 422 不回显输入。
- SQL 通过 SQLAlchemy 参数化；关键词搜索转义 LIKE 通配符；没有 `eval`/`exec` 或系统命令调用。
- Agent 只能调用 4 个只读白名单工具，日志文本不会被执行；提示词防护只是辅助，边界由工具与权限实现。

## 8. 下一阶段唯一最推荐的任务

**在真实 PostgreSQL 16 上完成迁移与全量测试验收。**

这是当前唯一"做了就等于消除了最大未知"的任务。其余候选（Agent 评测集、前端接入新能力、TLS/MFA）
都是在未经验证的数据库地基上继续加东西。

为什么是它：整个项目声明 PostgreSQL 为唯一部署目标，但 `0003`/`0004` 从未在 PostgreSQL 上执行过。
SQLite 验证只能证明迁移脚本语法正确，不能证明：

- `sa.Uuid()`、`JSON`、`DateTime(timezone=True)` 在 PG 上的实际类型与默认值；
- `ck_investigation_reports_finalized_at` 这类 CHECK 在 PG 上的行为；
- `uq_investigation_reports_alert_version` 唯一约束在并发下的表现；
- `ON DELETE SET NULL` / `RESTRICT` 外键在 PG 上的实际动作；
- 全量 217 项测试在 PG 方言下是否仍然全绿（SQLite 与 PG 在 UUID 排序、时间类型、`ilike` 大小写上存在差异）。

### 验收标准

1. 创建两个专用测试库（名称必须含 `test`）：

```bat
set "TEST_DATABASE_URL=postgresql+psycopg://user:pass@127.0.0.1:5432/sentinelflow_test"
set "MIGRATION_TEST_DATABASE_URL=postgresql+psycopg://user:pass@127.0.0.1:5432/sentinelflow_migration_test"
```

2. `alembic upgrade head` 成功，`alembic current` 为 `0004`，`alembic check` 输出
   `No new upgrade operations detected`。
3. `alembic downgrade 0003` → `0002` → `0001` → `base` 逐级成功，`base` 后只剩 `alembic_version`。
4. `pytest -q` 全绿：**260 passed, 0 skipped**（迁移测试不再跳过）。
5. 迁移测试断言全部通过：11 张表、CHECK 约束名、唯一约束名、外键目标表、索引名。
6. 若发现 PG 与 SQLite 行为差异导致测试失败，**修测试或修代码，不得放宽断言、不得跳过用例**。
7. 完成后更新 `README.md`、`docs/TESTING.md`、`docs/HANDOFF.md` 中的"未验证"表述。

### 完成后的下一项（不在本轮范围）

Agent 评测集与真实模型冒烟测试。当前 Agent 只有安全边界证据，没有研判质量证据。


## 9. 新对话首先阅读的文件

1. `README.md`
2. `docs/PROJECT_SPEC.md`
3. `docs/ARCHITECTURE.md`
4. `docs/DATA_MODEL.md`
5. `docs/API_SPEC.md`
6. `docs/PLAN.md`
7. `docs/DECISIONS.md`
8. `docs/TESTING.md`
9. `docs/SECURITY.md`（威胁模型与残余风险）
10. `docs/HANDOFF.md`（本文件）
10. `src/sentinelflow/main.py`
11. `src/sentinelflow/api/deps.py`
12. `src/sentinelflow/core/security.py`
13. `src/sentinelflow/services/auth.py`
14. `frontend/README.md`
15. `frontend/src/App.tsx`
16. `frontend/src/api/client.ts`
17. `frontend/src/auth/AuthContext.tsx`
18. `frontend/src/__tests__/`
19. `tests/conftest.py`
20. `tests/test_agent.py`

## 10. 给下一位开发者的注意事项

- 不要删除或覆盖现有文件；当前目录没有 Git 历史可恢复。
- 不要用 `create_all` 代替 Alembic 迁移。
- 不要提交 `.env`、JWT 密钥、密码或测试用真实凭据。
- 不要把 `JWT_SECRET` 设成默认值；缺失时认证接口应失败关闭。
- 授权不要信任 JWT 中的 role 声明；始终使用数据库当前角色。
- 不要添加公开注册或 API 用户管理接口；用户只能通过本地 CLI 创建。
- 不要删除 `data/sample_events.jsonl` 中的异常行；它们用于 CLI 容错验证。
- 不要将服务绑定到 `0.0.0.0`；在限流、TLS、MFA 和审计保留完成前只应本机使用。
- 报告建议不得改成自动封禁、删除、扫描或主机控制。
- 提交 Git 前先让用户检查最终差异；本次没有执行任何提交。
