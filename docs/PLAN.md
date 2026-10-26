# 开发计划

状态标记：**完成**、**部分完成**、**未开始**、**阻塞**。

## Phase 0：工程初始化

| ID | 任务 | 状态 | 说明 |
| --- | --- | --- | --- |
| P0-1 | 检查目录与 Git 状态 | 完成 | 初始化前为空目录；无 Git 仓库 |
| P0-2 | `src` 布局与包结构 | 完成 | 应用、配置、路由、数据库、模型、服务、CLI |
| P0-3 | 依赖与虚拟环境 | 完成 | Python 3.11.4；pyproject + venv + pip |
| P0-4 | FastAPI 与 `/health` | 完成 | 测试通过 |
| P0-5 | pytest 基础设施 | 完成 | SQLite 默认 + PostgreSQL 可选 |
| P0-6 | 配置与密钥管理 | 完成 | `.env` 忽略；示例仅占位符 |
| P0-7 | PostgreSQL Compose | 阻塞 | 文件已提供；当前机器无 Docker |
| P0-8 | Alembic 脚手架 | 完成 | 已有首次迁移 |
| P0-9 | 项目文档 | 完成 | 8 份文档 |
| P0-10 | Git 差异检查 | 阻塞 | 当前机器无 Git |

## Phase 1：确定性后端闭环

| ID | 任务 | 状态 | 验收条件 / 证据 |
| --- | --- | --- | --- |
| P1-1 | `SecurityEvent`、`Alert`、`alert_events` 模型 | 完成 | CHECK、唯一约束、外键、索引；测试通过 |
| P1-2 | 首次 Alembic 迁移 | 完成 | PostgreSQL 16.2 `upgrade head` 与 `downgrade base` 通过；`alembic check` 无差异 |
| P1-3 | 数据访问与集成测试 | 完成 | 服务层直接使用 `Session`，未引入 Repository 抽象；API/DB 测试通过 |
| P1-4 | 事件导入 API + JSONL CLI | 完成 | 单批 ≤500；重复跳过；CLI 逐行报错；真实 PG 验证 |
| P1-5 | AUTH-001 确定性规则 | 完成 | 5 分钟闭区间、≥5 次、分组隔离、时间排序、幂等 |
| P1-6 | 告警查询与生命周期 | 完成 | 查询/分页/详情完成；状态机 `open→acknowledged→investigating→closed` + reopen，非法 409，写历史与审计 |
| P1-7 | 确定性调查报告 | 完成 | 按需生成、证据完整性校验、证据上限 100、`evidence_total`/`evidence_truncated` |
| P1-8 | 审计日志 | 完成 | `audit_logs`、登录/限流/登出/导入/检测/状态变更/报告/拒绝审计、admin 查询接口 |
| P1-9 | 认证与 RBAC | 完成 | Argon2id、JWT（含 `jti`）、admin/analyst、401/403、本地 CLI 用户创建 |
| P1-10 | 输入限制与安全加固 | 部分完成 | 批量、字段长度、分页上限、报告证据上限、422 不回显输入；仍缺请求体大小中间件 |
| P1-11 | `/ready` 就绪检查 | 未开始 | 当前只有 `/health` |
| P1-12 | 报告持久化与版本 | 完成 | `investigation_reports`、输入快照、版本号、draft/finalized/superseded |
| P1-13 | 告警状态更新 API | 完成 | `PATCH /alerts/{id}`，状态转换规则 + `alert_status_history` + 审计 |
| P1-14 | 登录限流、令牌撤销、MFA | 部分完成 | 限流（429）与令牌撤销/登出完成；MFA、刷新令牌未实现 |
| P1-15 | 事件查询过滤与搜索 | 完成 | 字段过滤、`q` 关键词、时间范围，参数化 + LIKE 转义 |
| P1-16 | 证据分页接口 | 完成 | `GET /alerts/{id}/evidence`，上限 200，默认不含 `raw_message` |

### 工程验收记录（2026-10-19，认证/RBAC/审计）

- `pip check`：无损坏依赖。
- 应用导入、OpenAPI、Uvicorn 启动：通过；OpenAPI 包含 HTTPBearer。
- SQLite pytest：112 passed, 1 skipped（迁移测试因未设置 PostgreSQL URL 跳过）。
- PostgreSQL 16.2 pytest：113 passed。
- `alembic upgrade head`、`alembic check`、`alembic current`：通过；current 为 `0002 (head)`。
- 用户创建：本地 CLI 交互式密码、Argon2id 哈希、无默认密码。
- 登录：admin/analyst 成功；错误密码/未知用户/禁用用户统一 401。
- RBAC：analyst 可读事件/告警/报告，导入/检测/审计返回 403。
- 审计：登录、导入、检测、报告查看、审计查看、权限拒绝均有记录。
- 真实 Uvicorn + PostgreSQL：无 token 401；admin 导入 5/5、检测 1 个告警、报告 5 条证据；analyst 读 200、写/审计 403。
- 未执行：Docker Compose（无 Docker）、Git 状态/差异（无 Git）、Linux/macOS 命令、并发/大样本性能。
- 验收结论：认证/RBAC/审计闭环可运行；登录限流、MFA、TLS、令牌撤销和审计保留仍未实现。

### 已完成闭环

```text
data/sample_events.jsonl
  → sentinelflow-import
  → security_events
  → POST /api/v1/detections/run (AUTH-001)
  → alerts + alert_events
  → GET /api/v1/alerts
  → GET /api/v1/alerts/{id}/report
```

实际验证：

- 29 行样例 → 24 导入、1 重复跳过、4 无效。
- 检测 22 个认证失败事件 → 2 个告警。
- 每个告警 5 条证据，报告中的证据 ID 全部存在于数据库。
- 重复检测不新增告警。

## 前端控制台（已完成）

| ID | 任务 | 状态 | 验收条件 / 证据 |
| --- | --- | --- | --- |
| FE-1 | React + TypeScript + Vite 独立前端 | 完成 | `frontend/`，后端结构不变 |
| FE-2 | 登录、JWT 会话、路由守卫、401/403 | 完成 | Vitest + 真实浏览器 |
| FE-3 | 仪表盘、事件、告警、报告、审计 | 完成 | 真实 API + 24 项前端测试 |
| FE-4 | admin 导入/检测、analyst 只读 | 完成 | 浏览器联调 + 后端 403 |
| FE-5 | 分页、加载/空/错误状态 | 完成 | 浏览器联调 + 组件测试 |
| FE-6 | 前端文档与代理配置 | 完成 | `frontend/README.md`、Vite proxy |
| FE-7 | 无效 token、后端不可用、403 反馈 | 完成 | 浏览器联调 + Vitest |

前端未实现项：告警状态操作按钮、报告创建/定稿按钮、搜索与字段过滤 UI。后端已提供这些接口（`PATCH /alerts/{id}`、`POST /alerts/{id}/reports`、`POST /reports/{id}/finalize`、事件过滤参数），前端尚未接入，因此不提供假操作。
前端测试：`npm test` **33 passed**；typecheck、lint、build 通过。

## Phase 2：检索、LLM 与 Agent

| ID | 任务 | 状态 | 说明 |
| --- | --- | --- | --- |
| P2-1 | 受控证据检索接口 | 完成 | 工具内复用 service，作用域限本告警 |
| P2-2 | 工具注册与 Schema | 完成 | 4 个只读工具，Pydantic `extra="forbid"` + 超时 + 权限 |
| P2-3 | 单 Agent 研判工作流 | 完成 | 5 轮 / 8 次调用预算，产出 draft 报告 |
| P2-4 | 提示注入与数据泄露防护 | 部分完成 | 系统提示 + 服务端工具边界 + 工具日志脱敏；无独立注入评测集 |
| P2-5 | 评测集与回归 | 未开始 | 当前只有安全边界测试，无研判质量指标 |
| P2-6 | 人工复核与审批 | 部分完成 | Agent 只能产出 draft，定稿由 admin 人工执行；无审批流 |
| P2-7 | 可重复评测集 | 完成 | `evaluation/`：13 用例 / 10 指标 / 独立命令 + pytest 集成 |
| P2-8 | 调查过程可观测 | 完成 | `investigation_rounds`、`duration_ms`、`request_id`、CLI 追踪、中断回收 |
| P2-9 | 前端调查闭环 | 完成 | 报告页启动调查、轮询、步骤/工具/报告展示、失败重试、刷新恢复 |
| P2-10 | 真实模型评测 | 未开始 | 需凭据与人工标注集；当前指标明确标注 Mock |
| P2-11 | 持久化任务队列 | 完成 | 数据库表 + 租约 + 单线程 worker；pending/running/终态、重试上限、崩溃回收 |
| P2-12 | Agent 对比基准 | 完成（模型部分未测） | `benchmark/`：规则 / 单次模型 / Agent 三方对比；确定性基线已出真实数字 |
| P2-13 | 真实模型评测 | 未开始 | 需要 `LLM_*` 凭据；`python -m benchmark.runner --model real` 已就绪 |

前置条件：确定性基线稳定；鉴权、审计、报告持久化完成（均已满足）。


## Phase 3：运维与生产化（未开始）

| ID | 任务 | 状态 |
| --- | --- | --- |
| P3-1 | CI（lint、类型检查、测试） | 未开始 |
| P3-2 | 结构化日志、指标、追踪 | 未开始 |
| P3-3 | 依赖漏洞扫描与锁定 | 未开始 |
| P3-4 | 生产认证授权与密钥管理 | 未开始 |
| P3-5 | 备份、恢复、保留策略 | 未开始 |

## 当前阻塞项

1. **Docker 未安装**：Compose 未运行验证；本次 PostgreSQL 验证使用嵌入式 PostgreSQL 16.2。
2. **Git 未安装**：无法检查差异或提交。
3. **无真实生产数据**：所有测试数据均为合成数据。

### 工程验收记录（2026-10-23，阶段 A）

- SQLite pytest：`190 passed, 1 skipped`（跳过迁移测试，未设置 `MIGRATION_TEST_DATABASE_URL`）。
- 既有 112 项测试全部继续通过，未修改既有断言。
- 新增 78 项测试：告警详情、状态机、报告版本、证据分页、事件过滤、登录限流与令牌撤销。
- 前端：`typecheck` 通过、`oxlint` 0 warnings、`npm test` 33 passed、`build` 通过。
- `alembic heads` → `0003 (head)`。
- **未执行**：`alembic check`、PostgreSQL 迁移与全量测试（本机无 PostgreSQL / Docker）。
- 验收结论：阶段 A 的 6 项任务在 SQLite 上全部通过；PostgreSQL 验证待补做，这不阻塞阶段 B 的 Mock 模型开发。

## 阶段 B 验收记录（2026-10-23）

- SQLite pytest：`217 passed, 1 skipped`（阶段 B 当时的快照；第五天结束时为 `245 passed, 1 skipped`）；阶段 B 新增 27 项 Agent 测试。
- 前端未改动（本阶段无前端需求），26 项测试继续通过。
- `alembic heads` → `0004 (head)`（阶段 B 当时；第五天为 `0005`）。
- **未执行**：真实模型调用、PostgreSQL 迁移与全量测试、`alembic check`。
- 验收结论：Agent 的安全边界（白名单、参数校验、权限、作用域、预算、引用校验、日志脱敏、注入处理）
  在 Mock 模型下全部通过；**研判质量未验证**。

## 下一步

### 1. ~~补做 PostgreSQL 验证~~（2026-10-25 已完成）

已用 EDB 免安装二进制包 + `--locale=C` 起临时 PostgreSQL 16.15 集群完成验证：
全量 `334 passed`、迁移测试 `1 passed`、`0001`–`0006` 升降级、`alembic check` 无差异、
真实 Uvicorn + worker 全链路冒烟通过。复现命令见 `docs/TESTING.md`。

以下命令仍然有效，供在标准环境（Docker / 本机 PG）复跑时使用：

```bat
set "MIGRATION_TEST_DATABASE_URL=postgresql+psycopg://user:pass@127.0.0.1:5432/sentinelflow_migration_test"
set "TEST_DATABASE_URL=postgresql+psycopg://user:pass@127.0.0.1:5432/sentinelflow_test"
pytest -q
alembic upgrade head && alembic check
```

### 2. Agent 评测集与真实模型验证

- 固定评测集：正常、边界、恶意输入（注入）各若干条，断言引用完整性与结论要点。
- 真实模型冒烟测试：一次成功、一次超时、一次返回非法 JSON。
- 记录延迟与 token 成本基线。

### 3. 前端接入阶段 A/B 已具备的能力

- 告警状态操作（`PATCH /alerts/{id}`）、报告创建与定稿、事件过滤 UI、Agent 调查触发与结果展示。

### 安全加固（生产前置）

TLS、MFA、刷新令牌、请求体大小中间件、审计保留、日志脱敏以及 `/docs`/`/openapi.json` 访问控制属于生产部署前置条件；在完成前仍只应绑定 `127.0.0.1`。


## 明确不做（当前）

- 不做多 Agent 协作、自主规划或自动处置；Agent 只产出草稿。
- 不实现真实扫描、阻断、删除或主机控制。
- 不引入微服务、消息队列、Kubernetes。
- 不自动执行 Git commit。
