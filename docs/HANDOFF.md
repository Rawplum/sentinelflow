# 交接说明

最后更新：2026-10-25

**一句话状态**：功能闭环完成，SQLite 与 PostgreSQL 全量验证（后端 358 passed、前端 48 passed、
真实浏览器 16 项），真实模型已测量（Agent 41/44、单次模型 37/44、规则 13/18）。
启动方式是一条**已端到端验证**的本地路径（`sentinelflow-doctor` → 迁移 → 建用户 → API → 浏览器 E2E）；
容器化部署已移除，因为它在本机从未能执行（DECISIONS D-050）。
标注仍是人工的，这是当前最大缺口。详细状态见下一节。

## 接手须知（先读这一段，约 1 分钟）

### 先用三条命令建立事实

```bat
git log --oneline           :: 看最近几次提交，判断上次做到哪
git status --short          :: 有输出 = 有未提交改动，先看清楚再动手
python scripts/check.py     :: 全部检查，期望 7 步全 PASS
pytest -q                   :: 期望 358 passed, 3 skipped（SQLite）
python -m benchmark.runner  :: 确定性基线，期望 13/18 期望匹配、0/3 拒答
```

**不要用文档里的数字代替这四条命令。** 文档会过期，命令不会。
基线提交本身不必逐个文件读——它的价值是"差异的参照点"，不是"要读的内容"。

### 当前状态（2026-10-25）

| 项 | 值 |
| --- | --- |
| 迁移 head | `0006` |
| 静态检查 | ruff 0 问题；mypy 89 个文件 0 错误；格式 110 个文件通过 |
| 后端测试（SQLite） | 358 passed / 3 skipped |
| 后端测试（PostgreSQL 16.15） | 360 passed / 1 skipped（含 2 条并发回归） |
| 前端测试 | 48 passed / 12 files |
| 已验证环境 | SQLite、PostgreSQL 16.15、生产构建 + 同源代理 |
| **未验证** | 干净机器上装 PostgreSQL、macOS/Linux 命令、多副本 worker 并发、**CI 是否真的绿**（本机无远程仓库） |

### 三件必须先知道的事

1. **PostgreSQL 已经真实验证过**（2026-10-25）。`0001`–`0006` 全量升降级、`alembic check` 无差异、
   全量 pytest 通过、真实 Uvicorn + 队列 worker 全链路冒烟通过。
   `0006` 的 `drop_constraint` 分支已确认可执行。复现命令见 `docs/TESTING.md`。
2. **模型基线已有真实数字，25 个用例**：Agent 41/44 = 93%、单次模型 37/44 = 84%、
   规则引擎 13/18 = 72%。两次运行 5 处判定翻转，**任何单次结果都不能当结论**。
   Agent 的真正差异是拒答（3/3 vs 0/3），不是总体准确率。
3. **规则基线的风险分数是同义反复**：`risk_level` 直接取自用例里写死的 `alert.severity`。
   它只有"不会拒答（0%）"这一项是真实短板。

### 读什么，不读什么

读：`docs/BENCHMARK.md`（为什么做、怎么读结果）、`docs/SECURITY.md`（边界与残余风险）、
本文件 §5.7（最近一次改动的完整上下文）。

**不必通读** §5.1–§5.6：它们是按天追加的历史，结论已被后续覆盖。要追溯用 `git log -p`。

### 下一步只有一件事

**引入客观标签。** 现在所有期望都是我一个人定的，rubric 已经改过两版。
`expectation_match_rate` 衡量的是"与我的判断一致的程度"，不是正确率。
下一步需要人工标注的"这条告警是否真实攻击"。**在这之前不要调 prompt**——那只会拟合这 22 个用例。

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
- **13 个顶层未跟踪条目，暂存区为空**：`.env.example`、`.gitignore`、`README.md`、`alembic.ini`、`e2e/`、`data/`、`docs/`、`evaluation/`、`frontend/`、`migrations/`、`pyproject.toml`、`src/`、`tests/`。
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
| Docker / Compose | 未安装（不需要） |
| 本机 PostgreSQL | 未安装（未注册服务） |
| 验证用 PostgreSQL | PostgreSQL 16.15 免安装二进制包，临时集群在 `%TEMP%`，端口 55432（不是项目依赖） |

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
├── e2e/browser.mjs
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
| 12 张表（含 `investigation_rounds`） | SQLite + PostgreSQL |
| Alembic `0001`–`0006` 升级/降级 | 真实 SQLite **与 PostgreSQL 16.15** |
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

- 全量 SQLite：`358 passed, 1 skipped`（迁移测试因未设置 PostgreSQL URL 跳过）。
- 全量 PostgreSQL 16.15：`341 passed`；`tests/test_migrations.py` 单独跑 `1 passed`。
- 既有 112 项测试全部继续通过，**未修改任何既有断言**。
- 阶段 A 新增 78 项：告警详情、状态机、报告版本、证据分页、事件过滤、登录限流与令牌撤销。
- 阶段 B 新增 27 项：Agent 白名单、参数校验、权限、作用域、预算、引用校验、日志脱敏、提示注入、模型失败/超时、非法结构化输出、空查询结果、失败审计。
- 前端：`npm run typecheck` 通过；`npm run lint` 0 warnings；`npm test` **33 passed**（第五天验收时的实际值）；`npm run build` 通过。
- `alembic heads` → `0006 (head)`。
- **迁移已用真实数据库验证**：在 SQLite 库上 `upgrade head`（0001→0004）、`alembic check` 无差异、逐级 `downgrade 0003→0002→0001→base` 成功（base 后仅剩 `alembic_version`）。
- **真实 Uvicorn + 迁移过的 SQLite 库冒烟通过**：登录、401、导入、检测、告警详情、状态 409、审计、报告 v1/v2、定稿 409、superseded、证据分页、事件过滤、限流 429、登出撤销 401、analyst 403、Agent 未配置 503。明细见 `docs/TESTING.md`。
- `git diff --check` → **exit 0**（修复 14 个前端文件末尾空行后）。
- **未执行**：真实模型调用、真实浏览器联调（仅 jsdom）。

### 已实现但尚未通过实际测试

- 容器化部署（已移除，见 D-050）。
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
| 后端全量 | `358 passed, 1 skipped` |
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


## 5.5 第九天（2026-10-24）：Git 基线与 Agent 对比基准

### 先做了三件早就该做的事

1. **建立 Git 基线**：`ca0838d`（202 个文件，工作区干净）。此前 8 天零提交，改错无法回滚。
   撤销方式：`git reset --soft HEAD~1`。
2. **PG 离线 DDL 校验**：`alembic upgrade head --sql`（314 行）确认 PG 分支语法正确——
   无 SQLite 残留（无 PRAGMA / batch 重建），类型正确（UUID / TIMESTAMP WITH TIME ZONE），
   `0006` 走的是 `ALTER TABLE ... DROP CONSTRAINT` 而不是 batch。
   **这不能替代真实 PG 运行，但把"从未执行过"降到"语法已验证"。**
3. 真实模型冒烟：无凭据，**未做**。

### 基准（新增 `benchmark/`）

三条基线跑同一批 9 个虚构案例：确定性规则 / 单次模型（无工具）/ Agent（受控工具）。

**确定性基线真实结果**（`python -m benchmark.runner`）：

| 指标 | 结果 |
| --- | --- |
| 任务完成率 | 5/5 = 100% |
| 期望匹配率 | **3/5 = 60%** |
| 证据引用有效率 | 5/5 = 100% |
| 结构校验通过率 | 5/5 = 100% |
| 证据不足拒答率 | **0/2 = 0%** |

未命中：`insufficient_single_event`（只有 1 条证据仍下结论）、`contradictory_timestamps`
（成功早于失败仍按窗口计数）。这是规则系统的固有边界，不是 bug。

模型基线在无凭据时未运行，报告中标注 `mode: self_test` / `not measured`，不得引用为模型性能。

### 基准立刻抓到的一个真 bug

`run_investigation`（同步入口，CLI 与基准都用它）在第七天引入队列后**已经失效**：
它只创建 `pending` 行就返回，`execute_investigation` 因为状态不是 `running` 直接跳过。
表现为调查永远停在 pending、`rounds_used=0`、CLI 静默不干活。
已有测试因为断言太弱（只比较前后状态相同）没有发现。

已修复：同步路径自己领取刚创建的行（status=running、attempt_count+1、写租约）。
新增回归测试 `test_synchronous_investigation_actually_runs` 断言 `status=succeeded` 且 `rounds_used >= 1`。

**教训**：队列化改造后，"同步便捷入口"是最容易被漏掉的调用方。

### 命令

```bat
python -m benchmark.runner                                   :: 确定性基线
python -m benchmark.runner --baseline all --model self-test  :: 管道自检，非测量
python -m benchmark.runner --baseline all --model real       :: 需要 LLM_* 凭据
pytest -q tests/test_benchmark.py
```

详见 `docs/BENCHMARK.md`。


## 5.6 第十天（2026-10-24）：前端研判闭环整合

目标是把已有能力串成一条能演示的路径，而不是重写界面。

### 结构变化

```text
/alerts                 列表（新增状态 / 严重性筛选，服务端过滤）
/alerts/:id             新增：告警详情（元信息 + 状态历史 + 证据预览 + 调查面板）
/alerts/:id/report      报告（标注来源、链接回详情）
```

以前点告警直接跳报告页，语义上把"详情"和"报告"混在一起；现在分开，详情页是入口，
报告是产物。所有数据都来自 API，刷新可重建。

### 后端（唯一新增能力）

`GET /api/v1/alerts` 增加 `status` / `severity` 查询参数，SQL 层过滤，`total` 随筛选变化，
非法枚举 422。前端**没有**做客户端过滤——那会让计数说谎。

### 前端

- 列表：两个筛选下拉 + 清除；改筛选时自动回到第一页。
- 详情页：告警元信息、状态变更历史、前 10 条证据（含"完整证据"跳转）、调查面板。
- 报告页：顶部标注「确定性规则生成」；版本列表把 `generator` 翻成中文（AI 辅助 / 确定性规则）；
  返回链接指向详情页而不是列表。
- 角色：调查按钮只对 admin 渲染，后端仍强制 `reports:write`；analyst 看到只读说明。
- 状态：加载中 / 404 / 网络错误 + 重试 / 空列表 / 无权限，各有对应组件。

### 测试

新增 `AlertDetailPage.test.tsx`（5 项：渲染、报告链接、404、500 重试、analyst 只读），
`AlertsPage.test.tsx` 增加 2 项筛选测试（断言请求真的带上 `status`/`severity`），
`ReportPage.test.tsx` 增加 1 项来源标注测试。后端新增 `test_alert_filters_api.py`（7 项）。

### 结果

后端 **334 passed / 1 skipped**，前端 **48 passed / 12 files**，typecheck / lint / build 通过。

## 5.7 第十一天（2026-10-25）：PostgreSQL 真实验证

这是悬了十天的最大的验证缺口，今天补上了。

### 为什么之前做不成，这次怎么做成的

之前用 `pgserver`（嵌入式 PostgreSQL 16.2），在 GBK 系统 locale 下 `initdb` 直接失败。
本机也没有 Docker、没有安装 PostgreSQL。

这次改用 **EDB 免安装二进制包**：

```text
curl -sL -o %TEMP%\pg16.zip https://get.enterprisedb.com/postgresql/postgresql-16.15-1-windows-x64-binaries.zip
initdb -D %TEMP%\pgdata16 -U postgres --auth=trust --encoding=UTF8 --locale=C
postgres -D %TEMP%\pgdata16 -p 55432 -c listen_addresses=127.0.0.1
```

关键就是 `--locale=C`：绕开 GBK。整个集群在 `%TEMP%`，不写系统、不注册服务、
不占 5432，验证完删目录即可。

### 结果（全部真实执行）

| 检查 | 结果 |
| --- | --- |
| 全量 pytest（`TEST_DATABASE_URL` 指向 PG） | **334 passed** |
| `tests/test_migrations.py`（`MIGRATION_TEST_DATABASE_URL`） | **1 passed**（此前一直 skip） |
| `alembic upgrade head` | 6 级全执行（0001→0006） |
| `alembic check` | `No new upgrade operations detected.` |
| `alembic current` | `0006 (head)` |
| `alembic downgrade base` | 6 级回退，仅剩 `alembic_version` |
| 再次 `upgrade head` | 6 级，public schema 13 张表 |
| 真实 Uvicorn + worker 全链路冒烟 | 12 步全通（见下） |

**最重要的确认**：`0006` 修改 `ck_investigations_status` 与 `uq_investigation_rounds_*` 时，
在 PG 上走的是 `drop_constraint` / `create_unique_constraint` 分支，
不是 SQLite 的 `batch_alter_table` 整表重建。**这条分支此前从未被执行过。**

### PostgreSQL 上的真机冒烟

```text
1  login             200
2  import            201 imported=5
3  detection         200 alerts=1
4  alert detail      200 open evidence=5
5  evidence page     200 items=2/5
6  POST investigate  202 pending
7  immediate GET     200 status=pending        <- 后台执行，请求不等模型
8  duplicate POST    409 already running
9  final             200 succeeded rounds=2 tools=1 attempts=1 ms=14
10 report            200 agent draft cited=2/5
11 audit             200 run+complete: True
12 logout            204 | reuse: 401
```

队列的条件 `UPDATE ... WHERE <claimable>` + `rowcount==1`、租约、`pending` 状态 CHECK、
`timestamptz` 的 aware/naive 转换，都在 PG 上按预期工作。

### 没有改任何代码

这一轮**零代码改动**——十天里所有针对 PG 的谨慎（`Uuid` 类型、`as_utc()` 归一化、
不用 `SKIP LOCKED`、不用 SQLite 专有语法）都兑现了。改的只有文档。

### 复现

见 `docs/TESTING.md` 的「PostgreSQL 16.15（真实数据库）」小节，含完整命令。

## 5.8 第十二天（2026-10-25）：真实模型接入尝试（未成功）

### 结果：没有拿到真实数字

用户提供了 `https://agentrouter.org/v1` 与模型 `gpt-6.1-sol`，以及一个 `sk-` 开头的 token。
**该 token 被网关拒绝**，因此 `--model real` 仍未运行。

### 排查过程（结论：token 无效，不是客户端问题）

| 检验 | 结果 | 排除了什么 |
| --- | --- | --- |
| 无 key / 假 key / 真 key | 三者返回**完全相同**的 `unauthorized client detected` | key 校验之前就拒绝的可能 |
| 真实 Chromium（Playwright，同源 fetch） | 同样 401 | TLS 指纹、UA、浏览器特征 |
| 系统代理 / 直连 | 相同 | 出口 IP |
| 4 种鉴权头（Bearer / 裸 token / `api-key` / `x-api-key`） | 全部 401 | 头部格式 |
| `GET /api/status` | 200，公告里确实写着 `gpt-6.1sol` | 网关不可达 |
| `GET /v1/nonexistent` | 404 `Invalid URL` | 路由层异常 |
| `GET /api/user/self` | 200 + `access token 无效` | —— |

网关能连、路由正常、模型存在，唯独这个 token 不被接受。需要重新生成令牌。

### 沉淀：`--probe` 预检

排查过程原本是一串手工 curl。现在是一条命令：

```bat
python -m benchmark.runner --probe
```

依次检查：环境变量是否齐全 → `GET {base}/models` 是否接受 key（仅诊断，网关禁用该路由时只告警）
→ 一次真实 `POST {base}/chat/completions` 是否返回**结构合法的 findings**。
失败退出码 2，key 打码成 `sk-abc...1234`，完整 key 不落盘。

为什么值得加：一次基准要跑 9 个用例 × 最多 5 轮模型调用。端点配错时，
原本会看到 9 行错误，真正的原因藏在表格里；现在第一行就说清楚。

新增 3 项测试：未配置时失败关闭、端点可用时通过、401 时失败。

### 命令

```bat
set LLM_PROVIDER=<provider>
set LLM_MODEL=<model>
set LLM_API_BASE=<https://host/v1>
set LLM_API_KEY=<key>
python -m benchmark.runner --probe
python -m benchmark.runner --baseline all --model real
```

## 5.9 第十三天（2026-10-25）：真实模型评测完成，以及它暴露的基准缺陷

### 凭据

`provider=deepseek`，`model=deepseek-flash`（DeepSeek-V4.1-Flash），`LLM_API_BASE=https://api.deepseek.com`。
key 只通过命令行环境变量传入，未写入任何文件。

### 真实结果（三次运行，不是一次）

| 指标 | deterministic | single_shot | agent |
| --- | --- | --- | --- |
| 期望匹配率（逐次） | 60/60/60% | 50/67/67% | 83/100/83% |
| 期望匹配率（合计） | **3/5 = 60%** | **11/18 = 61%** | **16/18 = 89%** |
| 合理拒答 | 0% | 0/0/0% | 0/100/0% |
| 引用有效率 | 100% | 100% | 100% |
| 结构校验 | 100% | 100% | 100% |
| 工具调用成功率 | — | — | 100%（28-31 次） |
| 不安全操作拦截 | — | — | 1/1 |
| 平均延迟 | 3 ms | 5.4-7.6 s | 9.6-10.6 s |
| 输入 token / 6 用例 | — | 3.8k | **42-48k** |
| 输出 token / 6 用例 | — | 4.7-6.6k | 7.7-8.6k |

### 第一次跑出来的数字是 33%，那是基准的错

首轮 `agent 3/9 = 33%`，比规则引擎还差。查下来两个缺陷都在基准侧：

1. **三个用例对真实模型不可能通过**：`model_timeout` / `invalid_citation` / `tool_failure_recovery`
   依赖注入故障。真实模型不会被强制超时或强制编造引用，`should_fail` 永远无法满足。
   已加 `requires_fault_injection: true`，模型基线跳过并**显式打印**，覆盖仍由脚本化测试保证。
2. **风险等级没有定义就拿来评分**：提示词只要求输出枚举值，从未说明各等级对应什么证据。
   已在两处提示词（Agent system prompt、单次模型 prompt）写入 rubric，并按其重标两条用例
   （`suspicious_bruteforce`、`prompt_injection_in_log` 的 `min_risk` 由 high 改 medium）。
   **这是改标准**，所以改前（33%）改后（89%）的数字都保留，不隐藏。

另外发现规则基线的风险分数是**同义反复**：`build_report` 的 `risk_level` 直接来自
`alert.severity`，而后者是用例写死的输入。报告里该基线现在带 `caveat` 字段说明这点。

### 顺带补的测量能力

- **`--repeat N`**：连跑 N 次，报告哪些判定翻转、各比率波动区间。三次运行抓到 4 处翻转，
  其中 `agent/insufficient_single_event` 在 run1 FAIL、run2 PASS。
- **token 用量**：客户端解析 provider 返回的 `usage`，基准用 `CountingClient` 累加。
  只在 provider 真的返回时才计——`0` 会看起来像"没有成本"，那是假的。
  金额成本仍标 `not measured`，因为单价不该写死在代码里。
- **`must_mention_any`**：用于"是否指出了时间线矛盾"这类期望。只匹配 summary + reasoning，
  **不匹配 limitations**——规则报告的固定模板里就有 "may be inaccurate or skewed"，
  匹配 limitations 会让它靠模板通过。

### 结论

Agent 比规则引擎准（89% vs 60%），差距来自两件规则引擎做不到的事：承认证据不足、
指出时间线自相矛盾。但 **Agent 不比单次模型明显更准**（89% vs 61%），而输入 token 是 11 倍。
以 6 个用例的样本，这个差距在噪声之内——**还不能说工具调用值这个成本**。

下一步不是调 prompt，是扩样本（见 `docs/BENCHMARK.md` §8）。

## 5.10 第十四天（2026-10-25）：三项改善，其中一项是真 bug

### 1. 修了一个可达的生产缺陷（报告内容与证据不符）

`build_report` 有两处让报告"看起来正确但说的是错的"：

| 缺陷 | 现象 | 修法 |
| --- | --- | --- |
| 窗口取自当前页 | 报告证据上限 100 条；150 条证据的告警，摘要写"到 10:39 结束"，实际到 11:29。`?evidence_offset=3` 会让开始时间也错 | 改用 `alert.first_seen_at` / `last_seen_at` |
| 把所有事件叫"失败尝试" | 4 失败 + 1 成功的告警被写成"5 failed authentication attempts" | 新增 `count_alert_failures`，混合时写"N authentication events (M failed)" |

新增 `tests/test_report_accuracy.py`（3 项），先写出失败再修。这是本轮唯一的产品代码缺陷。

### 2. 评测集从 9 个扩到 25 个用例

新增 16 个：跨账号撞库、换源成功登录、凌晨成功、阈值边界、密码过期后成功、输错两次后成功、
2 次失败、缺 IP、空正文、成功失败交替、三种注入（要求删告警 / 要求引用假 ID / 要求打印 Key）、
中文用户名、1500 字符正文、4 小时内的零星失败。

支撑改动：`seed()` 支持**每事件**的 `username` / `source_ip` / `asset_id` 与空值；
`expect` 新增 `must_not_cite`（注入要求引用假 ID）与 `must_not_contain`（注入要求打印 Key）。

**rubric 改了第二版。** 第一版写"多次失败后出现成功登录 → high"，与良性用例
（密码过期、输错两次）的 `max_risk=medium` 直接矛盾——模型照 rubric 执行被判错，
**错在 rubric**。第二版补了降级条件。同时把 5 条用例的标注改准（全部记录在
`docs/BENCHMARK.md` 的「被改过的用例」表里，改前改后的数字都留着）。

### 3. 真实浏览器端到端

`e2e/browser.mjs`：真实 Chromium + 真实后端 + Vite 代理，16 项检查全通过
（登录 → 仪表盘 → 告警列表 → 筛选 → 详情 → 启动调查 → 轮次/工具/报告 → 刷新恢复 → 报告页 → 退出 → 受保护路由跳登录）。
任何 console error 或未捕获异常都会失败。这是**前端第一次在真浏览器里被点过**。

### 最终数字

```text
后端  pytest -q                       → 344 passed, 1 skipped
基准  25 用例 / 模型可评 22 个
      规则 13/18 = 72%（拒答 0/3）
      单次模型 37/44 = 84%（拒答 0-1/3）  输入 15.6k token
      Agent 41/44 = 93%（拒答 3/3）       输入 166k token
      两次运行 5 处判定翻转
浏览器 node e2e/browser.mjs            → 16 项通过
前端  npm test                         → 48 passed
```

## 5.11 第十五天（2026-10-25）：可复现的本地部署，然后把它删了

### 先做了容器化

`compose.yaml` 原来只有 `db`。补齐成四服务（db / migrate / api / web）+ 两个非 root 镜像 +
nginx 同源反代，启动顺序靠 `condition` 而不是 sleep，秘密用 fail-fast 插值。
本机没有 Docker daemon、`wsl.exe` 被安全策略阻断，所以用三层替代验证：
静态校验 17 项（做了变异测试）、命令级等价验证（空库 → 迁移 → 全链路 → 杀库重启验持久化）、
生产构建 + 同源代理 + 浏览器 E2E。

### 然后删了它

用户问"docker 是必须的吗，如果不是那就不要了"。答案是**不必须**，而且：

1. 那套配置**从头到尾没有一次真实执行**。静态校验证明的是"命令序列可行"，
   不是"容器可行"——两者之间的差距（镜像构建、容器 DNS、healthcheck 触发、非 root 权限）
   恰好是最容易出问题的地方。
2. 它承诺"一条命令起整套"，代价是每次 schema 变更都要同步维护一份没人验证的配置。
3. Docker 唯一真正解决的问题是"不用装 PostgreSQL"，而 PostgreSQL 是一次性安装。

所以删除 `compose.yaml`、两个 `Dockerfile`、`nginx.conf`、`.dockerignore`、
`tests/test_deploy_config.py`（共 7 个文件），换成一条已验证的本地路径 + 一个诊断工具。
决定记在 DECISIONS D-050，容器化版本留在 Git 历史 `704d4f9`。

### 新增：`sentinelflow-doctor`

新用户第一次跑会遇到的问题是重复且无聊的：没 `.env`、密码不对、PostgreSQL 没起、
没迁移、没有可登录的用户。每一个都会产生一个离原因很远的堆栈。

doctor 按这个顺序检查，每项失败给出**可直接复制**的命令，只读不写，密码显示为 `***`：

```text
SentinelFlow doctor
  OK    python      3.11.4
  OK    config      JWT_SECRET set
  OK    database    postgresql+psycopg://sentinelflow@127.0.0.1:5432/sentinelflow
  FAIL  migrations  no alembic_version table
                    -> run: alembic upgrade head
  FAIL  users       cannot read the users table
                    -> run: alembic upgrade head
  INFO  agent       disabled (LLM_* not set); the API works, investigations return 503
  OK    console     dependencies installed

2 check(s) failed.
```

10 项测试覆盖每种失败态，其中一条断言**密码必须被掩码**。

写测试时发现一个真问题：数据库不可达时 doctor 会**挂住**（psycopg 没有连接超时）。
一个会挂住的诊断工具比不诊断更糟，所以给 PostgreSQL 加了 `connect_timeout=5`。

### 验证：空库按 README 走一遍

```text
createdb → doctor: FAIL migrations / FAIL users（并给出 alembic upgrade head）
alembic upgrade head → 6 级
doctor → OK 0006 (head) / WARN no users（并给出 create-user 命令）
建用户 → doctor: All checks passed（并打印下一条命令）
uvicorn → /health/ready 200 ready
登录 → 导入样例 → 检测 2 告警 → 浏览器 E2E 16 项全通过
```

### 仍未验证

- 干净机器上安装 PostgreSQL 的这一步（本机用免安装二进制包）。
- macOS / Linux 上的同一套命令。
- 非交互执行 `sentinelflow-create-user`（它刻意只接受交互式输入）。

## 5.12 第十六天（2026-10-25）：性能与并发实测，四个真问题

全部数字见 **`docs/PERFORMANCE.md`**。这里只记结论和改了什么。

### 方法

`perf/dataset.py` 按固定种子生成合成数据（爆发 + 噪声，有界基数），
`perf/runner.py` 删库重建 → 播种 → 起**真实 uvicorn 进程** → 按场景计时，
`perf/concurrency.py` 多线程打同一接口。三档规模：1.7k / 16k / 96k 事件。

### 修掉的四个问题

| 问题 | 证据 | 修法 | 结果 |
| --- | --- | --- | --- |
| 检测写入每告警 9 次往返 | 96k 事件创建 6000 告警 **25.6 s**；cProfile 显示扫描只占 2.2 s | 整批放进一个 savepoint，证据关联批量 INSERT；撞 dedup 时回退逐条 | **3.0 s**（8.4×） |
| 并发改状态历史链断裂 | 8 客户端×6 轮：出现"investigating 之后接 open" | `session.get(..., with_for_update=True)` | 历史恒为从 open 出发的链 |
| 并发发起调查超发 | 3 告警×6 并发接受了 5 个 | 同样加行锁 | 恰好 3 个，区间不重叠 |
| 批量导入后查询慢 20 倍 | 96k 刚导入 `offset=20000` P95 **515 ms**，`ANALYZE` 后 **16.7 ms** | runner 显式测量冷/热两态；文档要求导入后 ANALYZE | 冷态变成可观测的指标 |

### 明确没修的（有数字支撑）

关键字搜索全表扫描（96k 时 39 ms，要修得装 `pg_trgm`）、`count(*)` 全表（19 ms）、
深分页 OFFSET（15 ms）、检测仍全表扫描（2.2 s）。理由写在 PERFORMANCE.md §6。

### 回归测试

`tests/test_concurrency.py` 两项，**仅在 PostgreSQL 下执行**——SQLite 忽略 `FOR UPDATE`，
既复现不了竞态也证明不了修复。这条限制写在测试的 skip 理由里，不是悄悄跳过。

并发状态的单元测试只能验证不变量，**不能可靠复现竞态**（窗口只有微秒级）；
真正的复现证据是 `perf/concurrency.py` 修复前的那次运行。这一点在测试 docstring 里写明。

## 5.13 第十七天（2026-10-25）：质量门禁与 CI

### 之前的状态

没有 linter、没有类型检查、没有格式化配置、没有 CI。`pyproject.toml` 里只有 pytest 配置，
但 `.gitignore` 里留着 `.ruff_cache` 和 `.mypy_cache`——工具被期待过，但没落地。

### 现在

```bat
python scripts/check.py          :: 7 步，约 105 秒
python scripts/check.py --fast   :: 只跑静态部分，约 3 秒
```

CI 的三个必需 job 调用同一个脚本，所以本地和 CI 不会漂移：

| Job | 命令 |
| --- | --- |
| `backend` | `scripts/check.py --backend-only` |
| `frontend` | `scripts/check.py --frontend-only` |
| `postgres` | 全量测试 + `tests/test_migrations.py` + `alembic upgrade head` + `alembic check` |

第四个 job `optional-real-model` 只在 `workflow_dispatch` 时运行，读 `secrets.LLM_API_KEY`，
没有密钥就跳过而不是失败。它不在必需检查里。

### 一次性还清的债

| 项 | 数量 | 处理 |
| --- | --- | --- |
| ruff 告警 | 185 → 0 | 140 条自动修，其余手工；`B008`（FastAPI `Depends`）和 `RUF001`（中文全角标点）显式忽略并注明理由 |
| 格式不一致 | 49 个文件 | `ruff format` 统一，行宽 88 |
| mypy 错误 | 25 → 0 | 覆盖 `src/` + `tests`，89 个文件 |

### 三条不是"为了过检查"的修改

1. **`agent.py` 的闭包捕获循环变量**（B023）：`round_ms()` 闭包读的是外层 `round_started`，
   当前代码在同一个迭代内调用所以没出错，但一旦有人在循环结束后调用它就会拿到最后一轮的值。
   改成把起始时间绑成默认参数。
2. **`test_agent.py` 里重复定义的 `FailingClient`**（F811）：本地类与 `tests/support`
   里的完全一样，只是遮蔽了导入。删掉本地的。
3. **`evaluation/metrics.py` 可能对 `None` 取属性**（union-attr）：`item.report` 是可空的，
   原代码直接 `.get()`。加了显式跳过。

另外把 `tests/support` 的 `_configured` 从 `dict[str, object]` 换成了 `TypedDict`，
`test_agent.py` 里 5 处 `execution.result[...]` 前面补了 `assert ... is not None`——
这些断言在值为 None 时会让测试直接失败并指出位置，比 `AttributeError` 好读。

### 没有做的

- **没有加 pre-commit**：需要额外安装钩子，而 `scripts/check.py --fast` 已经够快。
- **没有把前端纳入 mypy**：前端是 TypeScript，`tsc --noEmit` 由 `npm run build` 覆盖。
- **CI 没有在本机跑过**：本机没有远程仓库、没有 Actions runner。
  工作流用 PyYAML 校验过结构，命令与本地脚本一致，但"CI 真的绿了"这件事**没有验证**。

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

### 检查环境

```bat
sentinelflow-doctor
```

它按顺序检查 Python 版本、`.env`、数据库连通、迁移版本、是否有用户，
每项失败都给出可直接复制的命令。只读，不打印密码。

### 迁移

```bat
alembic upgrade head
alembic current
alembic check
```

当前 head：`0006`。

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

1. ~~**PostgreSQL 验证缺口**~~（2026-10-25 已解决）：改用 EDB 免安装二进制包 + `--locale=C` 起临时集群，
   绕开了 `pgserver` 在 GBK locale 下 `initdb` 失败的问题。`0001`–`0006` 升降级、全量测试、
   真实 Uvicorn 全链路均已在 PostgreSQL 16.15 上通过。
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
