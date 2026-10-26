# SentinelFlow

SentinelFlow 是一个 AI 辅助的安全事件研判与响应平台。当前版本完成了第一条**确定性端到端闭环**：

```text
导入合成安全日志 → 规则生成告警 → 查询证据 → 生成结构化调查报告
```

整条链路不调用大模型，可作为后续 Agent 版本的对照基线。

> **安全说明**：已实现 JWT 认证（含 `jti`）、基于角色的访问控制、append-only 操作审计、登录限流和令牌撤销。当前仍是本地开发版本：没有 TLS、MFA、刷新令牌、密钥轮换和审计保留策略，默认只应绑定 `127.0.0.1`。生产部署前仍需安全评审和额外加固。

## 当前状态

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| FastAPI 应用与 `GET /health` | 已实现，测试通过 | 公开，不依赖数据库 |
| 环境配置 | 已实现，测试通过 | `pydantic-settings`，读取 `.env` |
| `SecurityEvent` / `Alert` / `alert_events` 模型 | 已实现，测试通过 | SQLAlchemy 2.x，含 CHECK、唯一约束、外键 |
| `User` / `AuditLog` 模型 | 已实现，测试通过 | 用户、角色、密码哈希、审计表 |
| Alembic 迁移 `0001` + `0002` | 已实现，PostgreSQL 16.2 验证通过 | 可升级、可降级 |
| JSONL 导入 CLI | 已实现，SQLite 与 PostgreSQL 验证通过 | 逐行报告无效数据，重复事件跳过 |
| 本地用户创建 CLI | 已实现，测试通过 | 交互式密码输入，无默认密码 |
| JWT 登录 `/api/v1/auth/login` | 已实现，测试通过 | Argon2id + 有过期时间的 Bearer token |
| RBAC（admin / analyst） | 已实现，测试通过 | 统一权限依赖，后端强制检查 |
| 操作审计 | 已实现，测试通过 | 登录、导入、检测、报告查看、权限拒绝等 |
| `POST /api/v1/events/import` | 已实现，测试通过 | admin；单批最多 500 条 |
| `GET /api/v1/events` | 已实现，测试通过 | admin/analyst；`limit` 1–200；字段过滤、关键词搜索、时间范围 |
| AUTH-001 确定性规则 | 已实现，测试通过 | 5 分钟内 ≥5 次认证失败 |
| `POST /api/v1/detections/run` | 已实现，测试通过 | admin；重复运行不产生重复告警 |
| `GET /api/v1/alerts` | 已实现，测试通过 | admin/analyst；分页、证据计数（SQL 统计） |
| `GET /api/v1/alerts/{id}` | 已实现，测试通过 | admin/analyst；告警详情 + 状态历史 |
| `PATCH /api/v1/alerts/{id}` | 已实现，测试通过 | admin；状态机流转，非法转换 409 |
| `GET /api/v1/alerts/{id}/report` | 已实现，测试通过 | admin/analyst；确定性生成、不写库、证据上限 100 |
| `GET /api/v1/alerts/{id}/evidence` | 已实现，测试通过 | admin/analyst；证据分页，默认不含 raw_message |
| 报告持久化与版本 | 已实现，测试通过 | 草稿/定稿/superseded、输入快照、版本号 |
| `POST /api/v1/reports/{id}/finalize` | 已实现，测试通过 | admin；定稿后不可改，修订建新版本 |
| 登录限流 | 已实现，测试通过 | 数据库计数，(username, IP) 5 次 / IP 20 次每 5 分钟，超限 429 |
| JWT 令牌撤销 | 已实现，测试通过 | `jti` + `revoked_tokens`；`POST /api/v1/auth/logout` |
| `GET /api/v1/audit-logs` | 已实现，测试通过 | admin only；分页、只读 |
| React 安全运营前端 | 已实现，浏览器联调通过 | 独立 `frontend/`；登录、仪表盘、事件、告警、报告、审计 |
| 前端自动化测试 | 已实现，33 passed | Vitest + React Testing Library + MSW |
| Agent 评测集 | 已实现，13/13 通过 | `evaluation/`，10 项指标，Mock 模型 |
| 安全加固与负向测试 | 已实现，46 项 | 见 `docs/SECURITY.md`：威胁模型、12 类控制、残余风险 |
| 调查过程追踪 | 已实现，测试通过 | `investigation_rounds` + 轮次/工具耗时 + `duration_ms` + `request_id` |
| 前端调查闭环 | 已实现，测试通过 | 报告页内启动调查、轮询状态、查看步骤/工具/报告、失败重试 |
| AI Agent 调查 | 已实现（Mock 模型验证） | 单 Agent、4 个只读白名单工具、5 轮/8 次预算、引用校验、产出草稿 |
| Agent 真实模型调用 | 未验证 | 需要配置 `LLM_*` 环境变量；本机无凭据，未做真实调用 |
| `/ready` 就绪检查 | 未实现 | 当前只有 `/health` |
| Docker Compose PostgreSQL | 已提供，未运行验证 | 当前机器未安装 Docker |
| Git 仓库 | 已初始化（未提交） | 2026-10-23 `git init`，尚无 commit |

状态含义：**已实现，测试通过** 表示有代码且有实际自动化测试证据；**验证通过** 表示在真实 PostgreSQL 16.2 上执行过；**未实现** 表示只有文档计划。

## 技术栈

| 组件 | 版本约束 | 用途 |
| --- | --- | --- |
| Python | `>=3.11` | 运行时，当前验证版本 3.11.4 |
| FastAPI | `>=0.115,<1.0` | REST API |
| Uvicorn | `>=0.30,<1.0` | ASGI 服务器 |
| Pydantic | `>=2.8,<3.0` | 请求/响应校验 |
| pydantic-settings | `>=2.4,<3.0` | 环境变量配置 |
| SQLAlchemy | `>=2.0.30,<3.0`，同步模式 | ORM |
| psycopg | `>=3.2,<4.0`，binary 版 | PostgreSQL 驱动 |
| Alembic | `>=1.13,<2.0` | 数据库迁移 |
| PyJWT | `>=2.10,<3.0` | JWT 签发与校验 |
| argon2-cffi | `>=23.1,<26.0` | Argon2id 密码哈希 |
| PostgreSQL | 16 | 运行时数据库 |
| React / TypeScript | 19.3 / 6.0 | 前端 UI |
| Vite | 8.3 | 前端构建与开发服务器 |
| React Router / Axios | 7.18 / 1.20 | 路由与 HTTP |
| TanStack Query | 5.104 | 服务端状态、分页与缓存 |
| Vitest / RTL / MSW | 5.0 / 16.3 / 3.0 | 前端测试 |
| pytest | `>=8.2,<9.0` | 测试 |
| httpx2 | `>=2.14,<3.0` | Starlette 1.9 `TestClient`（仅开发依赖） |

测试默认使用 SQLite 以获得快速、无外部依赖的反馈；生产代码和迁移按 PostgreSQL 编写。SQLite 不是受支持的部署目标。

## 环境要求

- Windows 10/11、Linux 或 macOS。
- Python 3.11+。
- PostgreSQL 16，推荐使用 Docker Compose；也可使用本机 PostgreSQL。
- Git（推荐，当前开发机未安装）。
- Docker + Docker Compose（可选，当前开发机未安装）。

`GET /health` 在数据库未配置时仍可用；业务接口需要 `DATABASE_URL`。

## 快速开始（Windows）

```bat
cd /d G:\软件开发
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"

copy .env.example .env
notepad .env
```

在 `.env` 中替换所有 `CHANGE_ME`，并保证 `DATABASE_URL` 中的密码与 `POSTGRES_PASSWORD` 一致。`.env` 已被 `.gitignore` 忽略。

启动数据库并执行迁移：

```bat
docker compose up -d db
alembic upgrade head
```

如果使用已有 PostgreSQL，只需设置正确的 `DATABASE_URL`，然后执行 `alembic upgrade head`。**不要**用 `create_all` 代替生产迁移。

生成 JWT 密钥并写入 `.env`：

```bat
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

把输出填入 `.env` 的 `JWT_SECRET`，至少 32 字符。不要提交真实密钥。

创建本地管理员（密码通过交互式输入，不接受命令行密码参数）：

```bat
sentinelflow-create-user --username admin --role admin
```

创建分析员：

```bat
sentinelflow-create-user --username analyst1 --role analyst
```

启动 API：

```bat
uvicorn sentinelflow.main:app --reload --host 127.0.0.1 --port 8000
```

### Linux / macOS

```bash
cd /path/to/软件开发
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
# 编辑 .env：DATABASE_URL 和 JWT_SECRET
docker compose up -d db
alembic upgrade head
sentinelflow-create-user --username admin --role admin
uvicorn sentinelflow.main:app --reload --host 127.0.0.1 --port 8000
```

## 前端控制台（`frontend/`）

前端使用 React 19 + TypeScript + Vite 8，独立于后端目录，不修改后端 API。

前置条件：

- Node.js LTS（Vite 8 建议 20.19+ 或 22.12+；当前验证版本 24.20.0）。
- 后端已在 `http://127.0.0.1:8000` 运行。
- 已通过本地 CLI 创建 admin/analyst 账户。

启动：

```bat
cd /d G:\软件开发\frontend
npm install
copy .env.example .env
npm run dev
```

打开 `http://127.0.0.1:5173`。Vite 将 `/api` 和 `/health` 代理到 `127.0.0.1:8000`，本地开发无需后端 CORS。

角色：

- admin：仪表盘、事件、告警、报告、导入、检测、审计。
- analyst：仪表盘、事件、告警、报告只读；审计和写操作由后端返回 403。

前端测试与构建：

```bat
npm run typecheck
npm run lint
npm test
npm run build
```

当前结果：TypeScript 通过，oxlint 0 warnings，**26 tests passed**，生产构建通过。详细页面说明、环境变量和安全说明见 [`frontend/README.md`](frontend/README.md)。

## AI Agent 调查（可选）

Agent 是**可选能力**：未配置模型时，其余接口全部正常工作，只有
`POST /api/v1/alerts/{id}/investigations` 返回 `503 AI agent is not configured`。

配置（写入 `.env`）：

```bat
set "LLM_PROVIDER=openai"
set "LLM_MODEL=<model-name>"
set "LLM_API_BASE=https://api.openai.com/v1"
set "LLM_API_KEY=<your-key>"
```

可选预算配置：`AGENT_MAX_ROUNDS`（默认 5）、`AGENT_MAX_TOOL_CALLS`（默认 8）、
`AGENT_TOOL_TIMEOUT_SECONDS`（默认 5）、`LLM_TIMEOUT_SECONDS`（默认 30）。

运行一次调查：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/alerts/<alert-uuid>/investigations \
  -H "Authorization: Bearer %TOKEN%"
```

安全边界（由代码强制，不依赖提示词）：

- 模型只能调用 4 个**只读**白名单工具：`get_alert_details`、`get_related_events`、
  `search_events`、`search_runbooks`。未注册的工具在参数被读取前就拒绝。
- 工具参数经 Pydantic 严格校验（`extra="forbid"`），有长度/数量上限和单工具超时。
- 工具只作用于**当前告警的证据**，无法跨告警查询。
- 模型输出必须匹配固定 JSON Schema；`cited_event_ids` 中每个 ID 都必须是该告警的真实证据，
  否则整次调查失败且不产出报告。
- Agent 不能修改告警状态、不能定稿报告、不能执行封禁/删除/扫描。
- 日志文本被视为不可信数据；提示词中的防注入说明只是辅助手段。
- 调查记录与工具调用日志不保存模型提示词、模型原始响应或 `raw_message`。

> **未验证**：本项目未使用真实模型凭据运行过 Agent。所有自动化测试都使用脚本化的 Mock 模型客户端，
> 在 FastAPI 依赖边界替换，不会发起真实模型调用。

## 端到端演示

### 0. 登录并获取访问令牌

先调用登录接口：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<your-password>"}'
```

响应：

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "expires_in": 1800,
  "username": "admin",
  "role": "admin"
}
```

在 Windows cmd 中保存令牌：

```bat
set "TOKEN=<access_token from the response>"
```

后续管理请求使用 `-H "Authorization: Bearer %TOKEN%"`；bash 中使用 `$TOKEN`。analyst 只能访问查询和报告接口。

### 1. 导入合成日志

CLI（逐行校验，允许部分导入）：

```bat
sentinelflow-import data\sample_events.jsonl
```

实际输出摘要（SQLite/PostgreSQL 验证一致）：

```json
{
  "records_seen": 29,
  "valid_records": 25,
  "invalid_records": 4,
  "received": 25,
  "imported": 24,
  "skipped": 1,
  "skipped_event_ids": [
    "00000000-0000-4000-8000-000000000001"
  ]
}
```

也可以通过 API 导入（admin，整批校验，任一事件无效则整批返回 422）：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/events/import \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer %TOKEN%" \
  -d '{"events":[{"event_id":"11111111-1111-4111-8111-111111111111","timestamp":"2026-10-19T09:00:00Z","event_type":"authentication","username":"alice.demo","source_ip":"198.51.100.10","asset_id":"workstation-01","action":"login","outcome":"failure","raw_message":"synthetic auth failure","source":"synthetic-auth"}]}'
```

响应 `201 Created`：

```json
{
  "received": 1,
  "imported": 1,
  "skipped": 0,
  "skipped_event_ids": []
}
```

### 2. 运行确定性检测

```bash
curl -X POST http://127.0.0.1:8000/api/v1/detections/run \
  -H "Authorization: Bearer %TOKEN%"
```

对样例数据（24 条唯一事件）的实际响应结构：

```json
{
  "rule_id": "AUTH-001",
  "rule_version": "1.0.0",
  "events_scanned": 22,
  "windows_detected": 2,
  "alerts_created": 2,
  "alerts_skipped_existing": 0,
  "created_alert_ids": [
    "<alert-uuid-1>",
    "<alert-uuid-2>"
  ]
}
```

再次运行会得到 `alerts_created: 0`，并通过 `alerts_skipped_existing` 报告已存在的告警。

### 3. 查询告警

```bash
curl "http://127.0.0.1:8000/api/v1/alerts?limit=50&offset=0" \
  -H "Authorization: Bearer %TOKEN%"
```

响应结构：

```json
{
  "items": [
    {
      "id": "<alert-uuid>",
      "rule_id": "AUTH-001",
      "rule_version": "1.0.0",
      "title": "Suspicious login activity",
      "description": "5 failed authentication attempts for user 'alice.demo' from 198.51.100.10 matched rule AUTH-001 (at least 5 failures in any 5-minute window).",
      "severity": "high",
      "status": "open",
      "first_seen_at": "2026-10-19T09:00:00Z",
      "last_seen_at": "2026-10-19T09:04:00Z",
      "event_count": 5,
      "created_at": "2026-10-19T14:20:00Z",
      "evidence_count": 5
    }
  ],
  "total": 2,
  "limit": 50,
  "offset": 0
}
```

### 4. 生成调查报告

```bash
curl "http://127.0.0.1:8000/api/v1/alerts/<alert-uuid>/report" \
  -H "Authorization: Bearer %TOKEN%"
```

响应包含 `alert_id`、`summary`、`risk_level`、`evidence`、`timeline`、`reasoning`、`recommended_actions`、`limitations`。`evidence` 中的每个 `event_id` 都来自数据库实际事件，`timeline` 按事件时间升序排列。

### 5. 查询操作审计（admin）

```bash
curl "http://127.0.0.1:8000/api/v1/audit-logs?limit=50&offset=0" \
  -H "Authorization: Bearer %TOKEN%"
```

审计记录包含登录成功/失败、事件导入、检测执行、报告查看、权限拒绝和本地用户创建。analyst 访问该接口返回 403。

## 规则说明

规则 `AUTH-001`：

- 仅考虑 `event_type = "authentication"`、`action = "login"`、`outcome = "failure"` 的事件。
- `username` 和 `source_ip` 必须非空。
- 按 `(username, source_ip)` 分组，绝不合并不同用户或不同来源 IP。
- 事件按 `timestamp` 升序处理，时间窗口为闭区间 `[start, start + 5 分钟]`。
- 同一组在窗口内出现至少 5 次失败时触发。
- 邻近/重叠的合格窗口会合并为一个告警，避免同一波活动产生重复告警。
- `dedup_key = AUTH-001 + SHA-256(rule|username|source_ip|first_event_id)`，数据库唯一约束保证重复运行不新增告警。

该规则只能发现“可疑登录模式”，**不能证明系统已遭入侵**。报告中的 `limitations` 会明确说明这一点。

## API 概览

| 方法 | 路径 | 角色 | 说明 |
| --- | --- | --- | --- |
| `GET` | `/health` | 公开 | 存活检查 |
| `POST` | `/api/v1/auth/login` | 公开 | 用户名/密码换取 Bearer token；超限 429 |
| `GET` | `/api/v1/auth/me` | 已登录 | 返回当前用户 |
| `POST` | `/api/v1/auth/logout` | 已登录 | 撤销当前 token |
| `POST` | `/api/v1/events/import` | admin | 导入 1–500 条已校验事件 |
| `GET` | `/api/v1/events` | admin / analyst | 分页查询 + 字段过滤 + 关键词 + 时间范围 |
| `POST` | `/api/v1/detections/run` | admin | 运行 AUTH-001 |
| `GET` | `/api/v1/alerts` | admin / analyst | 分页查询告警 |
| `GET` | `/api/v1/alerts/{id}` | admin / analyst | 告警详情 + 状态历史 |
| `PATCH` | `/api/v1/alerts/{id}` | admin | 状态流转（非法 409） |
| `GET` | `/api/v1/alerts/{id}/evidence` | admin / analyst | 证据分页 |
| `GET` | `/api/v1/alerts/{id}/report` | admin / analyst | 按需生成确定性报告（证据上限 100） |
| `GET` | `/api/v1/alerts/{id}/reports` | admin / analyst | 报告版本列表 |
| `POST` | `/api/v1/alerts/{id}/reports` | admin | 创建报告草稿版本 |
| `GET` | `/api/v1/reports/{id}` | admin / analyst | 读取持久化报告 |
| `POST` | `/api/v1/reports/{id}/finalize` | admin | 定稿 |
| `POST` | `/api/v1/alerts/{id}/investigations` | admin | 入队，返回 202 + `pending`；未配置模型 503；同告警已有排队/运行中调查 409 |
| `GET` | `/api/v1/investigations/{id}` | admin / analyst | 调查状态、轮次耗时、脱敏工具调用日志 |
| `GET` | `/api/v1/audit-logs` | admin | 分页查询操作审计 |

完整请求/响应、错误码和未实现接口见 `docs/API_SPEC.md`。

## 测试

默认（SQLite，快速、无需外部服务）：

```bat
pytest -q
```

实际结果：`318 passed, 1 skipped`。跳过的是需要真实 PostgreSQL 的迁移测试。

使用真实 PostgreSQL：

```bat
set "TEST_DATABASE_URL=postgresql+psycopg://user:password@127.0.0.1:5432/sentinelflow_test"
set "MIGRATION_TEST_DATABASE_URL=postgresql+psycopg://user:password@127.0.0.1:5432/sentinelflow_migration_test"
pytest -q
```

实际结果：`113 passed`（包含迁移升级/降级测试）。该数字来自 `0002` 时期的历史验证；`0003` 迁移的 PostgreSQL 验证尚未在本机重跑。

说明：

- `TEST_DATABASE_URL` 必须指向名称包含 `test` 的专用数据库。
- `MIGRATION_TEST_DATABASE_URL` 必须指向独立的空测试数据库；迁移测试会删除并重建其中的核心表。
- 当前机器没有 Docker，PostgreSQL 验证使用嵌入式 PostgreSQL 16.2 完成；该工具不是项目运行时依赖。
- 测试不会连接开发数据库。

### 前端测试

```bat
cd /d G:\软件开发\frontend
npm run typecheck
npm run lint
npm test
npm run build
```

实际结果：TypeScript 通过、oxlint 0 warnings、**26 tests passed**、生产构建通过。

### 最新验证记录（2026-10-24，第五天）

| 检查 | 结果 |
| --- | --- |
| `pytest -q`（SQLite） | `318 passed, 1 skipped` |
| 新增测试 | 206 项（告警详情/状态机/报告版本/证据分页/事件过滤/限流撤销/Agent/可观测性/评测/防重与凭证卫生/模型客户端 HTTP） |
| 既有测试 | 原 112 项全部继续通过，未修改任何既有断言 |
| 前端 `npm test` | `40 passed / 11 files` |
| 前端 `typecheck` / `lint` | 通过 / 0 warnings |
| `alembic heads` | `0006 (head)` |
| `alembic check` | **通过**：在真实 SQLite 库上 `upgrade head` 后 `No new upgrade operations detected` |
| 迁移升降级 | 真实 SQLite：`0001→0004` 升级、`0004→0003→0002→0001→base` 逐级降级均成功，仅剩 `alembic_version` |
| PostgreSQL pytest | **未重跑**（本机无 PostgreSQL / Docker，`pgserver` 在 GBK locale 下 initdb 失败） |
| `git diff --check` | **通过**（exit 0；先修复 14 个前端文件末尾多余空行） |
| 真实 Uvicorn + 迁移过的 SQLite 库 | 全链路 HTTP 冒烟通过：登录/401/导入/检测/告警详情/状态 409/审计/报告版本/定稿 409/superseded/证据分页/事件过滤/限流 429/登出撤销 401/analyst 403/Agent 未配置 503 |
| 前端生产构建 | 通过 |
| Git | 已 `git init`（分支 `main`），**未 stage、未 commit** |

历史记录（`0002` 时期，认证/RBAC/审计 + 前端）保留在 `docs/TESTING.md`。

详细策略见 `docs/TESTING.md`。

## 数据库与迁移

```bat
alembic upgrade head
alembic downgrade base
alembic current
```

首次迁移：`migrations/versions/0001_core_tables.py`。
认证与审计迁移：`migrations/versions/0002_users_and_audit.py`。当前 head 为 `0002`。

数据库结构由 Alembic 管理；测试中的 SQLite 建表仅用于快速反馈，不代表部署方式。Compose 仅把 PostgreSQL 绑定到 `127.0.0.1:5432`。

回滚：

```bat
alembic downgrade 0001
```

回滚会删除 `audit_logs` 和 `users`，不会影响事件、告警和报告数据。执行前请确认没有需要保留的本地账户或审计记录。

## 目录结构

```text
.
├── src/sentinelflow/
│   ├── main.py                     # FastAPI 应用与错误处理
│   ├── core/
│   │   ├── config.py               # 环境配置（含 JWT 配置）
│   │   ├── permissions.py          # 角色与权限映射
│   │   ├── security.py             # Argon2id、JWT、用户名/密码策略
│   │   └── time.py                 # UTC 时间处理
│   ├── api/
│   │   ├── deps.py                 # Bearer 认证、令牌撤销校验、统一权限依赖
│   │   └── routes/
│   │       ├── health.py
│   │       ├── auth.py             # login / me / logout
│   │       ├── events.py           # 导入、过滤查询
│   │       ├── detections.py
│   │       ├── alerts.py           # 列表、详情、状态流转、证据分页、报告版本
│   │       ├── reports.py          # 持久化报告读取与定稿
│   │       └── audit.py
│   ├── schemas/                    # Pydantic 请求/响应模型
│   ├── models/                     # SecurityEvent、Alert、User、AuditLog、
│   │                               # InvestigationReport、AlertStatusHistory、
│   │                               # RevokedToken、LoginAttempt
│   ├── services/                   # 导入、规则、告警、报告、报告版本、
│   │                               # 认证/限流/撤销、审计
│   ├── db/session.py               # Engine / Session / Base
│   └── cli/
│       ├── import_events.py        # JSONL 导入 CLI
│       └── create_user.py          # 本地用户创建 CLI
├── tests/                          # 规则、认证、RBAC、审计、告警状态、
│                                   # 报告版本、证据分页、事件过滤、迁移测试
├── frontend/                       # React + TypeScript 安全运营控制台
│   ├── src/api/                    # Axios client、类型、错误处理
│   ├── src/auth/                   # JWT 会话、AuthContext、路由守卫
│   ├── src/components/             # layout / ui / domain 组件
│   ├── src/pages/                  # 登录、仪表盘、事件、告警、报告、审计
│   ├── src/__tests__/              # Vitest + RTL + MSW
│   └── README.md                   # 前端使用说明
├── migrations/                     # Alembic 环境与版本
├── data/sample_events.jsonl        # 合成数据（含异常行）
├── docs/                           # 项目文档
├── compose.yaml
├── alembic.ini
├── pyproject.toml
├── .env.example
└── .gitignore
```

## 文档索引

- [项目规格](docs/PROJECT_SPEC.md)
- [架构设计](docs/ARCHITECTURE.md)
- [数据模型](docs/DATA_MODEL.md)
- [API 规范](docs/API_SPEC.md)
- [开发计划](docs/PLAN.md)
- [技术决策](docs/DECISIONS.md)
- [测试策略](docs/TESTING.md)
- [交接说明](docs/HANDOFF.md)
- [前端使用说明](frontend/README.md)

## 已知限制与未实现项

- **认证已实现（含限流与撤销），但缺少 MFA、刷新令牌和密钥轮换**；当前仍只应本机使用。
- **已定稿报告不可修改**；修订需创建新版本，旧版本自动 `superseded`。
- **前端尚未接入状态流转、报告创建/定稿按钮**；后端已提供对应 API。
- 只有一条检测规则 `AUTH-001`。
- 事件查询支持字段过滤、关键词和范围，但**不支持自由查询语言或复杂布尔组合**。
- 没有请求体大小中间件；当前通过 Schema 限制批量条数、字段长度和分页大小。
- **检测会扫描全部认证失败事件**：没有增量或时间范围限制，数据增长后需要优化。
- 数据库错误日志可能包含语句和参数；上线前需要日志脱敏和访问控制。
- 报告接口仍返回 `raw_message`（为兼容性）；事件列表和证据分页可通过 `include_raw_message=false` 关闭。
- 没有审计保留/归档策略；审计表会持续增长。
- 登录限流基于数据库，**不防护能直接写数据库的攻击者**，也不能替代反向代理层全局限流。
- 没有 TLS 终止、反向代理或密钥轮换方案。
- FastAPI `/docs`、`/redoc`、`/openapi.json` 默认公开，会暴露 API 结构；生产环境应禁用或限制访问。
- **Agent 只用 Mock 模型验证过**，没有真实模型调用记录；真实模型的结论质量、延迟和成本均未评估。
- **没有固定评测集和准确率指标**；Agent 测试覆盖的是安全边界（白名单、预算、引用校验、注入），不是研判质量。
- Agent 同步执行，一次请求会阻塞到调查结束（默认上限 5 轮 + 8 次工具调用）；没有后台任务队列。
- 工具超时通过线程池实现，超时后工作线程不会被强制终止。
- 没有自动响应、扫描或阻断能力；Agent 只产出草稿报告。
- Docker Compose 未在当前机器验证；PostgreSQL 上 `0003`/`0004` 迁移验证待补做。
- Git 仓库已初始化但**没有任何提交**，当前无法用 `git diff` 追溯变更。
- SQLite 仅用于测试，不保证与 PostgreSQL 完全一致的并发和类型行为。

### 安全验证记录（认证/RBAC/审计/限流/撤销）

已确认：

- 密码使用 Argon2id 哈希存储；API 响应、审计记录和数据库中均无明文密码。
- JWT 使用 HS256、过期时间、issuer/audience 校验，并携带唯一 `jti`；密钥只来自 `JWT_SECRET`，无默认密钥。
- 授权使用数据库中的当前角色；禁用用户和角色变更立即生效。
- analyst 不能导入、运行检测、修改告警状态、创建/定稿报告或查看审计；后端返回 403，而不是仅隐藏前端按钮。
- 没有公开注册接口；用户只能通过本地 CLI 创建。
- 审计记录覆盖登录成功/失败/被限流、登出、导入、检测、告警状态变更、报告查看/创建/读取/定稿、审计查看和权限拒绝。
- 审计记录不保存密码、JWT 或密码哈希；登录失败与被限流均不记录尝试的用户名。
- 登录限流表只保存 HMAC 摘要，不保存明文用户名或 IP。
- 令牌撤销表只保存 `jti` 和过期时间，不保存 token 本身。
- 422 响应不再回显客户端输入。
- SQL 使用 SQLAlchemy 参数化；关键词搜索转义 LIKE 通配符；未发现 `eval` / `exec` 或系统命令调用。

尚未修复的风险（按优先级）：

1. **检测全表扫描**（中）：应增加时间范围/增量检测或数据量保护。
2. **请求体大小无中间件限制**（中低）：超大 JSON 会在 Schema 拒绝前被解析。
3. **审计无保留策略、日志可能含敏感参数**（中低）：需要归档、访问控制和日志脱敏。
4. **无 TLS/MFA/刷新令牌/密钥轮换**（中）：生产部署前必须补齐并做安全评审。
5. **限流为应用层数据库实现**（中低）：不能防护能写库的攻击者，建议在反向代理再加一层全局限流。
6. **`/docs`、`/redoc`、`/openapi.json` 默认公开**（低）：暴露 API 结构；生产应禁用或限制。

## 安全说明

- `.env` 不入库；`.env.example` 只含占位符。`JWT_SECRET` 至少 32 字符。
- 数据库端口只绑定回环地址；API 默认只绑定 `127.0.0.1`。
- SQL 通过 SQLAlchemy 参数化，不使用字符串拼接。
- 不使用 `eval` / `exec`。
- 报告建议仅为调查动作，不执行封禁、删除、扫描或主机控制。
- 认证、RBAC 和审计已实现，但登录限流、TLS、MFA、令牌撤销和审计保留仍未完成；在这些加固完成前，禁止公网部署。
