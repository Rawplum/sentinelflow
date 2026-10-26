# 技术决策记录

日期：2026-10-19。状态：`已采用`、`计划中`、`待定`。

## 1. 已采用决策

### D-001：Python 3.11+

- **决策**：要求 `>=3.11`，当前验证版本为 3.11.4。
- **理由**：FastAPI、Pydantic 2、SQLAlchemy 2 均稳定支持；`StrEnum`、`tomllib`、现代类型语法可用；避免为兼容旧版本引入额外依赖。
- **影响**：不使用 3.12+ 独有语法，保证 3.11 可运行。

### D-002：FastAPI + Uvicorn

- **决策**：FastAPI `>=0.115,<1.0`，Uvicorn `>=0.30,<1.0`，不安装 `uvicorn[standard]`。
- **理由**：OpenAPI 生成、Pydantic 集成和依赖注入满足首期需求；Uvicorn 基础版足够本地开发，避免引入 `uvloop`、`watchfiles`、`websockets` 等当前不需要的组件。
- **影响**：热重载由 Uvicorn 的默认实现提供；Windows 上不依赖 `uvloop`。

### D-003：Pydantic 2 + pydantic-settings

- **决策**：Pydantic `>=2.8,<3.0`，pydantic-settings `>=2.4,<3.0`。
- **理由**：请求/响应校验与配置读取统一使用 Pydantic 生态；不手写环境变量解析。
- **影响**：所有外部输入通过 Schema 进入系统；不使用 Pydantic v1 兼容层。

### D-004：SQLAlchemy 2.x 同步模式 + psycopg 3

- **决策**：使用同步 `Session`，驱动为 `psycopg[binary]`，URL 前缀 `postgresql+psycopg://`。
- **理由**：首期请求量小，同步模型更简单、易调试；psycopg 3 是现代驱动，避免同时保留 `psycopg2`。
- **影响**：不引入 async SQLAlchemy、asyncpg 或双驱动。未来若需要异步，必须整体评估事务和会话边界。

### D-005：PostgreSQL 16

- **决策**：本地使用 `postgres:16-alpine`。
- **理由**：`JSONB`、`INET`、部分唯一索引、`gen_random_uuid()` 满足数据模型需求；16 为稳定主版本。
- **影响**：测试和生产应保持同一主版本，避免 SQL 行为差异。

### D-006：Alembic 管理迁移

- **决策**：Alembic `>=1.13,<2.0`，迁移从 `Base.metadata` 自动生成后再人工审查。
- **理由**：数据库结构变更必须可追踪、可回退。
- **影响**：禁止手改生产库结构；所有表变更必须有 migration。当前尚无 revision。

### D-007：pytest + TestClient，测试客户端使用 httpx2

- **决策**：pytest `>=8.2,<9.0`；开发依赖使用 `httpx2>=2.14,<3.0`。
- **理由**：FastAPI 0.148 解析到的 Starlette 1.9 在 `TestClient` 中优先导入 `httpx2`，继续使用 `httpx` 会产生弃用警告。
- **影响**：测试依赖与运行时依赖分离；`httpx2` 只用于测试，不进入生产依赖。

### D-008：pyproject + venv + pip

- **决策**：使用 PEP 621 `pyproject.toml`、标准库 `venv` 和 pip，不引入 Poetry、Pipenv 或 PDM。
- **理由**：依赖规模小，标准工具足够；减少工具链和锁文件格式的额外维护。
- **影响**：当前没有锁文件；构建可复现性依赖版本范围 + 实际验证记录。是否引入锁文件见“待定事项”。

### D-009：模块化单体

- **决策**：单个 FastAPI 应用，按 API / services / models 分层，共享 PostgreSQL。
- **理由**：首期团队和流量规模不需要微服务；单体便于事务一致性和本地测试。
- **影响**：不引入消息队列、服务发现、Kubernetes。

### D-010：`src` 布局

- **决策**：源码位于 `src/sentinelflow/`，通过 editable install 或 pytest `pythonpath` 导入。
- **理由**：避免从仓库根目录误导入未安装代码；打包边界清晰。
- **影响**：新增模块必须位于 `src/sentinelflow/` 下。

### D-011：本地服务只绑定回环地址

- **决策**：Uvicorn 使用 `--host 127.0.0.1`；Compose 端口映射为 `127.0.0.1:5432:5432`。
- **理由**：认证已实现，但仍缺少登录限流、TLS、MFA 和令牌撤销；任何非回环暴露仍可能导致暴力破解或令牌滥用。
- **影响**：局域网其他设备无法访问；这是有意限制，不是配置遗漏。

### D-012：`/health` 不依赖数据库

- **决策**：`DATABASE_URL` 可选；`/health` 只表示进程存活。
- **理由**：应用可以在数据库未启动时启动并暴露明确的存活信号；避免把存活与就绪混淆。
- **影响**：数据库可用性需要未来的 `/ready` 单独检查；当前不能把 `/health` 当作就绪探针。

### D-013：初始化阶段不实现认证（已被 D-028 取代）

- **决策**：初始化阶段不实现认证、授权或会话。
- **理由**：避免在核心数据模型和 API 形态未稳定前固化安全模型。
- **影响**：该初始化决策已由 D-028 取代；认证、RBAC 和审计已实现。但在登录限流、TLS、MFA 和令牌撤销完成前，仍不建议公网部署。

### D-014：当前不接入 LLM

- **决策**：Phase 1 只实现确定性逻辑。
- **理由**：先建立可靠的数据、规则和审计基础，避免用模型掩盖数据质量问题。
- **影响**：不引入任何模型 SDK、API Key 或外部 AI 服务。

### D-015：初始化阶段不创建空领域模块

- **决策**：本次不创建 `models/`、`services/` 空包。
- **理由**：需求尚未落地到代码时，空模块只增加噪音；目录结构应随功能增长。
- **影响**：首次实现模型和业务逻辑时再创建包，并在文档中更新状态。

### D-016：枚举使用 `VARCHAR + CHECK`（计划）

- **决策**：状态和严重度使用字符串列加 `CHECK` 约束，映射为 Python `StrEnum`。
- **理由**：比 PostgreSQL 原生枚举更容易新增取值和回退迁移。
- **影响**：数据库层仍能约束非法值；应用层负责给出清晰错误。

### D-017：UUID 主键（计划）

- **决策**：核心实体使用 `UUID` 主键，默认 `gen_random_uuid()`。
- **理由**：避免 ID 枚举和信息泄露，便于未来跨环境合并数据。
- **影响**：索引体积略大于自增整数；当前规模可接受。

### D-018：不配置 CORS

- **决策**：当前不添加 CORS 中间件。
- **理由**：没有浏览器前端；默认不放开跨域更安全。
- **影响**：引入前端时必须显式配置受信来源，不能使用 `*` 搭配凭据。

### D-019：Compose 只运行 PostgreSQL

- **决策**：本地 Compose 仅包含数据库服务，应用在宿主机虚拟环境中运行。
- **理由**：开发时热重载和调试更直接；减少应用镜像构建的维护成本。
- **影响**：部署镜像和容器化运行留到后续阶段。

### D-020：模型使用可移植类型，SQLite 仅用于测试

- **决策**：主键使用 SQLAlchemy `Uuid`，`source_ip` 使用 `VARCHAR(45)`，时间使用 `DateTime(timezone=True)`。
- **理由**：让同一套模型和 API 测试可以在 SQLite 上快速运行，同时生产迁移仍针对 PostgreSQL。
- **影响**：PostgreSQL 的 IP 格式约束由 Pydantic 负责，数据库负责长度、非空和 CHECK；SQLite 不支持 PostgreSQL 的 `INET` 行为，因此不作为部署目标。

### D-021：AUTH-001 的窗口与去重算法

- **决策**：按 `(username, source_ip)` 分组；按时间升序；窗口为闭区间 `[start, start + 5 分钟]`；阈值 5；邻近合格窗口合并；`dedup_key` 使用规则、组和首个证据事件 ID 的 SHA-256。
- **理由**：规则可解释、可测试；不同用户/IP 不误合并；同一批数据重复运行时产生稳定去重键；哈希避免长用户名导致键超长。
- **影响**：合并后的证据跨度可能超过 5 分钟；这是“一个事件簇一个告警”的取舍，已在报告和文档中说明。

### D-022：调查报告按需生成，不持久化

- **决策**：当前 `GET /alerts/{id}/report` 从数据库实时生成报告，不保存报告表。
- **理由**：第一版优先验证证据链和规则闭环；避免在输入快照和版本语义未确定时固化报告存储。
- **影响**：没有报告版本历史或定稿状态；后续需要新增 `investigation_reports` 表和快照。

### D-023：API 导入原子校验，CLI 支持逐行部分导入

- **决策**：`POST /events/import` 通过 Pydantic 校验整批，任一事件无效返回 422；CLI 逐行校验，报告行号和错误，继续导入有效行。
- **理由**：API 调用方需要明确的全成功/全失败语义；本地数据接入需要处理脏数据。
- **影响**：两种入口的行为差异必须在文档中明确。

### D-024：报告只提供安全调查建议

- **决策**：`recommended_actions` 只包含核对来源、查看日志、人工复核等动作，不执行封禁、删除、扫描或主机控制。
- **理由**：当前没有授权、审批和审计，自动处置风险不可接受。
- **影响**：即使未来接入 Agent，破坏性动作仍需显式授权和人工确认。

### D-025：初始化阶段暂无认证/授权/审计（已被 D-028 取代）

- **决策**：本轮继续不实现认证和审计。
- **理由**：先建立确定性闭环和测试基线；避免在 API 形态未稳定前固化安全模型。
- **影响**：**禁止公网或多人使用**。认证、RBAC 和审计必须在部署前完成；`limitations` 也会提示当前没有访问控制。

### D-026：测试数据库策略

- **决策**：默认使用 SQLite 内存库；设置 `TEST_DATABASE_URL` 时使用真实 PostgreSQL；迁移测试使用独立的 `MIGRATION_TEST_DATABASE_URL`。
- **理由**：本地快速反馈与真实数据库验证兼顾；测试库名称必须包含 `test`，降低误连开发库风险。
- **影响**：本次使用 `pgserver` 0.1.4 提供的嵌入式 PostgreSQL 16.2 做验证，但它不是项目依赖；正式环境仍推荐 Docker Compose。
  （2026-10-25 更新：`pgserver` 在 GBK locale 下不可用，已改用免安装二进制包，见 D-049。）

### D-027：2026-10-19 确定性闭环验收结论（认证实现前，已由 D-029 补充）

- **决策**：验收阶段不新增功能，不改变 API 或数据模型；只记录并分级已知风险。
- **理由**：当前确定性闭环已经可用，先保证交接和验证证据可靠，避免在验收中引入未测试的行为变化。
- **当时已验证**：`pip check`、编译、应用导入、OpenAPI、SQLite 55 passed/1 skipped、PostgreSQL 56 passed、`alembic check` 无差异、`alembic current = 0001 (head)`、真实 Uvicorn + PostgreSQL 完整 HTTP 链路。
- **未验证**：Docker Compose（无 Docker）、Git 状态/差异（无 Git）、Linux/macOS 命令、并发和大样本性能。
- **已确认的安全事实**：无硬编码密钥；`.env` 被忽略；SQL 参数化；无 `eval`/`exec`；无 Agent，因此日志不能作为模型指令执行；合成数据不含真实凭据。
- **保留的风险（不阻塞本地使用，阻塞共享/公网）**：
  1. 无认证、授权、审计和限流（前三项已由 D-028 实现；登录限流仍未实现）。
  2. 报告 evidence 列表无上限，可能产生大响应。
  3. 检测全表扫描认证失败事件。
  4. 请求体大小没有中间件级限制。
  5. 422 响应和数据库错误日志可能回显原始输入。
- **影响**：上述风险已写入 README 和 HANDOFF；在修复前，服务只能绑定回环地址。下一阶段优先完成认证/审计，并在产品侧增加报告证据上限。

### D-028：认证、RBAC 与审计实现

- **决策**：
  - 密码使用 `argon2-cffi` 的 Argon2id 哈希。
  - 访问令牌使用 PyJWT、固定 HS256、默认 30 分钟过期，校验 `iss`/`aud`/`type`。
  - 角色只有 `admin` 和 `analyst`；权限集中定义在 `core/permissions.py`。
  - 授权使用数据库中的当前角色，不信任 JWT 中的角色声明；禁用用户立即失效。
  - 用户只能通过本地 `sentinelflow-create-user` CLI 创建，不提供公开注册或 API 用户管理。
  - 审计表 `audit_logs` 为应用层 append-only，记录登录、导入、检测、报告查看、审计查看、权限拒绝和 CLI 用户创建。
  - API 写操作和审计使用同一事务：`import_events` / `run_detection` 增加可选 `commit` 参数，路由传 `commit=False` 后写审计并统一提交。
  - 422 处理器去掉 `input`/`ctx`，避免回显密码等输入。
  - 请求 ID 由中间件生成/校验，并写入审计和响应头。
- **理由**：满足认证、最小权限和可追溯要求，同时不改变事件导入、规则判断和报告内容。
- **影响**：所有业务接口现在需要 Bearer token；旧匿名客户端需要登录。登录限流、MFA、刷新令牌、令牌撤销、TLS 和审计保留仍未实现，服务仍只应绑定 `127.0.0.1`。

### D-029：2026-10-19 认证/RBAC/审计验收结论

- **已验证**：SQLite 112 passed/1 skipped；PostgreSQL 113 passed；`alembic check` 无差异；current `0002 (head)`；真实 Uvicorn + PostgreSQL 完成 admin/analyst 登录、导入、检测、报告、审计和 401/403 验证。
- **未验证**：Docker Compose、Git 状态/差异、Linux/macOS 命令、并发和大样本性能。
- **保留风险**：登录无速率限制；报告 evidence 无上限；检测全表扫描；请求体大小无中间件限制；审计无保留策略；无 TLS/MFA/令牌撤销；`/docs`、`/redoc`、`/openapi.json` 默认公开。
- **结论**：认证/RBAC/审计闭环可运行，但不具备生产部署条件。

### D-030：前端技术栈与令牌存储

- **决策**：独立 `frontend/` 使用 React 19、TypeScript 6、Vite 8、React Router 7、Axios、TanStack Query 5、CSS Modules 和 lucide-react；不引入重型 UI 组件库。
- **理由**：需要类型安全、分页/缓存、一致的设计系统和可控依赖；CSS Modules 避免额外样式工具链。
- **代理**：Vite 将 `/api` 和 `/health` 代理到 `127.0.0.1:8000`，避免为前端修改后端 CORS。
- **令牌存储**：演示环境使用 `sessionStorage`，关闭标签页/退出/401 时清除；这不是生产最佳实践，生产应使用 HttpOnly Cookie、短期令牌、CSP 和令牌撤销。
- **权限**：前端路由守卫和按钮隐藏只改善体验；后端 RBAC 仍是最终授权边界。
- **影响**：Node.js LTS 成为前端开发前置依赖；生产部署需要同源反向代理或显式 CORS。

### D-031：报告持久化采用「渲染内容 + 输入快照」双存储

- **决策**：`investigation_reports` 同时保存 `content`（渲染后的完整报告）和 `input_snapshot`（告警字段 + 证据 ID + 总数）。定稿后不可原地修改；修订创建新版本，旧版本置为 `superseded`。
- **理由**：只存快照再实时重算，会导致规则版本升级后同一份“已定稿报告”内容变化，违背定稿语义；只存内容则无法说明报告基于什么数据。
- **影响**：报告内容与当前数据库可能不一致，这是**设计意图**；读取当前状态应查告警详情接口。`GET /alerts/{id}/report` 保持只读、不写库，因此刷新页面不会产生版本。

### D-032：报告证据硬上限 100 + 独立证据分页

- **决策**：报告内嵌证据最多 100 条，响应固定返回 `evidence_total` 与 `evidence_truncated`；新增 `GET /alerts/{id}/evidence`（上限 200，默认不含 `raw_message`）。
- **理由**：合并告警可能包含数百条事件，无上限会导致大响应和内存压力；总数与截断标记让客户端能区分“只有 5 条”和“显示了 600 条中的 5 条”。
- **影响**：`timeline` 与本次返回的证据页保持同长度。`evidence_limit > 100` 返回 422，不能通过参数绕过上限。

### D-033：告警状态机显式白名单

- **决策**：`open → acknowledged | investigating | closed`；`acknowledged → investigating | closed`；`investigating → closed`；`closed → open`（必须带 `reason`）。非法转换返回 409，同状态提交为幂等 no-op。
- **理由**：显式转换表可测试、可审计；禁止 `acknowledged → open` 之类回退，避免状态语义混乱。reopen 需要理由，因为重新打开已关闭事件是有后果的动作。
- **影响**：状态变更、`alert_status_history` 与审计在同一事务提交。当前没有“重开审批”流程，只有理由记录。

### D-034：登录限流使用数据库计数而非进程内存

- **决策**：`login_attempts` 表按 `(username, source_ip)` 和 `source_ip` 两个维度统计失败次数（5 次 / 20 次每 5 分钟），超限返回 429 + `Retry-After`。
- **理由**：进程内计数器重启即失效、多 worker 不一致；数据库实现让同一数据库下的所有 worker 共享计数。
- **影响**：每次登录多一次读 + 一次写；数据库不可用时登录 fail-closed。**不防护**能直接写库的攻击者，也不能替代反向代理层全局限流。被限流的请求不会延长锁定时间，避免攻击者用持续请求永久锁死账户。

### D-035：JWT 增加 `jti`，撤销表只存标识

- **决策**：访问令牌增加唯一 `jti`；`revoked_tokens` 只保存 `jti`、`user_id`、`expires_at`、`reason`；每请求校验一次；`POST /auth/logout` 撤销当前令牌。
- **理由**：没有 `jti` 只能靠“按用户全量失效”或“等过期”，粒度太粗；只存标识可避免数据库泄露后被重放。
- **影响**：`decode_access_token` 要求 `jti`，**不带 `jti` 的旧 token 会被拒绝**（fail-closed）。这是一次性影响，最长 30 分钟（默认过期时间）。撤销粒度是单 token，不影响同用户其他 token。

### D-036：事件过滤采用固定字段白名单

- **决策**：只允许 `event_type`、`username`、`source_ip`、`asset_id`、`action`、`outcome`、`q`（仅匹配 `raw_message`）、`start`、`end`。全部参数化；`q` 中的 `%`/`_` 转义为字面量。
- **理由**：白名单避免引入查询语言和注入面；转义避免用户用 `%` 意外拉取全表。
- **影响**：不支持复杂布尔组合。事件列表支持 `include_raw_message=false`；报告接口为兼容性仍返回 `raw_message`。

### D-037：新增权限全部只授予 admin，analyst 保持只读

- **决策**：新增 `alerts:write`、`reports:write`、`reports:finalize`，analyst 权限集合不变。
- **理由**：当前没有告警归属人/队列模型，无法界定 analyst 可修改哪些告警；状态变更和定稿都是有后果的签核动作。
- **影响**：如果产品需要 analyst 处理告警，必须先设计归属或队列授权模型，再单独决策，不能在本次实现中顺手放开。

### D-038：Agent 采用「白名单只读工具 + 服务端强制边界」

- **决策**：只实现单 Agent；模型通过 4 个只读工具访问数据；工具在服务端做白名单查找、Pydantic 严格校验、权限检查和告警作用域限制；模型输出必须通过固定 Schema，且引用的事件 ID 必须属于该告警；Agent 只产出草稿报告。
- **理由**：提示词防护可以被绕过，不能作为安全边界。真正的边界必须由服务端代码决定：能调用什么、能看到哪些数据、能写入什么。
- **影响**：
  - Agent 无法修改告警状态、无法定稿、无法执行任何处置动作。
  - 预算硬限制（5 轮 / 8 次调用 / 单工具 5 秒），耗尽即 `limit_reached` 且不产出报告。
  - 引用校验失败整次调查失败，避免“看起来有依据”的编造结论落库。
  - 模型客户端用标准库 `urllib`，不引入运行时 HTTP 依赖；只有 `LLM_API_BASE` 会被访问。

### D-039：Agent 测试使用依赖注入的 Mock 客户端

- **决策**：自动化测试在 FastAPI 依赖边界（`provide_model_client`）替换为脚本化客户端，生产代码中不包含 Mock 实现。
- **理由**：测试必须确定性、无需凭据、不产生费用；把 Mock 放进生产代码会让人误以为存在“假模型模式”。
- **影响**：测试覆盖的是编排与安全边界，不覆盖真实模型的输出质量。真实模型调用需要在有凭据的环境中单独验证。

### D-040：调查改为「创建即返回 + 后台执行」

- **决策**：`POST /alerts/{id}/investigations` 只创建 `running` 记录并返回 `202`，真正的模型调用在后台任务中执行；前端轮询 `GET /investigations/{id}`。
- **理由**：同步执行会让单个请求最多阻塞 5 轮 × 30 秒，且前端无法展示中间状态；刷新页面会丢失整个请求。异步后调查 ID 成为可分享、可刷新恢复的锚点。
- **影响**：后台任务使用独立 Session（绑定同一 engine）。**这是本地单节点实现，不是任务队列**：进程重启不会恢复执行，需靠 `AGENT_STALE_AFTER_SECONDS` 回收为 `failed`；没有重试与优先级。

### D-041：中断回收而非取消接口

- **决策**：不提供用户主动取消；改为在读取时回收超时的 `running` 记录（`created_at` 超过 `AGENT_STALE_AFTER_SECONDS`，默认 600 秒）→ `failed` + 固定错误文案。
- **理由**：线程无法被安全强杀，取消只能做成"协作式"（每轮检查标志位），收益有限却要改状态枚举与约束；而"永远停在 running"是必须消除的缺陷。
- **影响**：进程崩溃后的记录会保持 `running` 直到下一次读取触发回收；`failed` 的 error 明确写明 interrupted，不会伪装成业务失败。

### D-042：评测集用 Mock，且明确不衡量模型质量

- **决策**：`evaluation/` 用脚本化模型客户端跑 13 个用例，产出 10 项指标；`model_cost` 在无 token 数据时标记 `not measured`。
- **理由**：真实模型调用需要凭据与预算，且输出不稳定，不适合作为回归门禁；安全边界与编排正确性可以用确定性 Mock 精确断言。
- **影响**：指标只能证明"平台没有放行危险动作"，不能证明"Agent 研判得好"。真实质量评测需要人工标注集，列为后续任务。

### D-043：同一告警只允许一个运行中的调查

- **决策**：`create_investigation` 在写入前检查该告警是否存在"未过期"的 `running` 调查，存在则抛 `InvestigationConflictError` → HTTP 409；过期行不参与判断。
- **理由**：前端禁用按钮不能防住双击竞态、脚本重放或直接调 API。两个并发调查会各自产出一个报告版本（v1、v2），虽不损坏数据但属无意义重复写入，且双倍消耗模型调用。
- **影响**：用 `agent_stale_after_seconds` 作为"未过期"边界，与中断回收共用同一阈值，避免两套超时语义。没有数据库唯一约束，因为需要允许过期行与新行并存。

### D-044：端到端用本地 stub provider 验证协议链路

- **决策**：`tests/test_e2e_chain.py` 与 `tests/test_model_client_http.py` 用本地 HTTP stub 冒充
  OpenAI 兼容端点，跑**不替换依赖**的完整链路（生产客户端 → 真实 HTTP → stub → 报告落库）。
- **理由**：没有凭据时，这是唯一能证明"请求发得出、响应解得出、后台任务接得上"的方法；
  在依赖边界替换模型无法覆盖 `OpenAICompatibleClient` 的序列化与错误映射。
- **影响**：它证明协议与编排正确，**不证明**任何真实模型的输出质量、延迟或成本。
  `evaluation/` 的指标同样只覆盖编排与安全。文档中禁止把这类结果表述为"模型性能"。

### D-045：调查任务用「数据库表 + 租约」做持久化队列，不引入 Redis/Celery

- **决策**：`investigations` 表本身即队列。新增 `pending` 状态与 `attempt_count` / `max_attempts` /
  `lease_expires_at` / `next_attempt_at` / `started_at` / `error_code`；进程内单线程 worker 用
  条件 UPDATE 领取任务（`rowcount==1` 才算领到），随 lifespan 启停。
- **理由**：FastAPI 的 `BackgroundTasks` 只活在进程内存，进程一死任务就没了，**不能算队列**。
  但项目是单节点、数据库本来就在，为此引入 Redis + Celery 等于新增一个必须运维、备份、做高可用的组件。
  一张表 + 租约能同时满足"持久化、崩溃可恢复、不重复领取"，且 PostgreSQL 与 SQLite 共用一套代码。
- **影响**：
  - `POST` 只入队（`pending`），请求不再调用模型，慢 provider 不会拖垮 HTTP。
  - 只有可恢复错误（传输/超时/5xx/429）回 `pending` 重试，上限 `AGENT_MAX_ATTEMPTS`；确定性失败直接 `failed`。
  - 租约过期 + 次数耗尽 → `failed(interrupted)`，不存在永久 `running`。
  - 代价：worker 与进程同生共死，没有优先级/延迟队列/死信；多副本时吞吐不随副本线性增长（但不会重复领取）。

### D-046：追踪记录按 attempt 区分

- **决策**：`investigation_rounds` 与 `investigation_tool_calls` 增加 `attempt_index`；
  `investigation_rounds` 的唯一约束改为 `(investigation_id, attempt_index, round_index)`。
- **理由**：重试会从第 1 轮重新开始，旧约束 `(investigation_id, round_index)` 会在第二次尝试时直接冲突
  —— 这是实现重试时真实踩到的 bug，不是假设。
- **影响**：一次任务的多次尝试都保留完整轨迹，可按 attempt 分组查看；代价是多一列与一个联合唯一约束。

### D-047：运行时长上限必须小于租约，且在配置层强制

- **决策**：新增 `AGENT_MAX_RUNTIME_SECONDS`（180s）在 agent 循环内逐轮检查；`AGENT_LEASE_SECONDS`
  默认改为 240s；`Settings` 增加 `model_validator`，租约 ≤ 运行上限时**直接启动失败**。
- **理由**：审计时发现原默认值租约 120s、最坏运行 190s（5×30s 模型 + 8×5s 工具）。
  一次健康但慢的运行会先丢租约，然后被判定 interrupted 或被第二个 worker 重复执行——
  这是"不会重复执行有副作用操作"的直接反例。
- **影响**：单次调查硬上限 180 秒；超时转 `limit_reached` + `error_code=deadline_exceeded`。
  配置写错时进程起不来，而不是在运行时悄悄重复执行。

### D-048：请求体、队列深度、工具参数类型的硬限制

- **决策**：中间件按 `Content-Length` 拒绝 > 5 MiB 的请求（413）；`AGENT_MAX_PENDING=50`，
  超出返回 429；工具数值参数 `strict=True`，拒绝 `"5"` / `true` 之类的类型混淆。
- **理由**：这三项此前都只靠"调用方守规矩"。模型是攻击面之一，不能假设它给的是干净 JSON。
- **影响**：分块传输（无 `Content-Length`）不受该中间件保护，必须由反向代理补一层——已写入
  `SECURITY.md` 的残余风险。

### D-049：PostgreSQL 验证用免安装二进制包，不用 pgserver、不装系统服务

- **决策**：用 EDB 的 `postgresql-16.15-1-windows-x64-binaries.zip` 解压到 `%TEMP%`，
  `initdb --locale=C` 初始化，`postgres -p 55432` 直接起进程，验证完删目录。
- **理由**：`pgserver` 在本机 GBK 系统 locale 下 `initdb` 失败（历史阻塞点）；
  用 winget 装 PostgreSQL 会注册系统服务、占 5432、写注册表，为一次性验证改动系统不划算。
  `--locale=C` 直接绕开 GBK 编码问题，端口 55432 避开任何已有实例。
- **影响**：验证可复现且零污染；代价是数据目录在 `%TEMP%`，重启机器即失效，
  所以**每次验证都要重新 initdb**，这也是把完整命令写进 `docs/TESTING.md` 的原因。
- **结果**：全量 `334 passed`、迁移测试 `1 passed`、`0001`–`0006` 升降级、真机冒烟全通。

### D-050：移除容器化部署，改为已验证的本地路径 + doctor 预检

- **决策**：删除 `compose.yaml`、两个 `Dockerfile`、`nginx.conf`、`.dockerignore`、
  `tests/test_deploy_config.py`；新增 `sentinelflow-doctor`，README 改为一条从零开始、
  已端到端验证的本地路径。
- **理由**：这套配置在本机**从未被执行过**（无 Docker daemon，`wsl.exe` 被安全策略阻断）。
  一份没人跑过的部署方案不是资产：它承诺"一条命令起整套"，实际上把第一次真跑的人变成测试者，
  而且每次 schema 变更都要同步维护。之前用"静态校验 + 命令级等价验证"去补，
  但那些补丁证明的是**命令序列**可用，不是**容器**可用。
- **代价**：使用者必须自己装 PostgreSQL 16（Windows 一次点击，macOS/Linux 一条命令）。
  这是 Docker 唯一真正解决的问题。
- **替代**：`sentinelflow-doctor` 按新用户实际会撞上的顺序检查环境（Python → `.env` →
  数据库连通 → 迁移版本 → 是否有用户 → 可选项），每项失败给出可复制的命令，
  并且**只读不写、不打印密码**。这条路径已端到端验证：空库 → doctor 报"没迁移" →
  `alembic upgrade head` → doctor 报"没用户" → 建用户 → doctor 全绿 → 起 API →
  浏览器 E2E 16 项通过。
- **保留**：容器化版本留在 Git 历史（`704d4f9`）。若将来有能跑 Docker 的环境，
  可以取回并按当时的状态重新验证——但不应再以"未验证"的形式留在主线。

### D-051：并发一致性用行锁，批量写入用「整批 + 回退」

- **决策**：`change_status` 与 `create_investigation` 在读写之间对告警行加
  `SELECT ... FOR UPDATE`；检测的告警写入改成整批一个 savepoint + 批量 INSERT，
  撞 dedup key 时整批回滚并退回逐条路径。
- **理由**：两处并发缺陷都是同一个形状——先读、再判断、再写，中间没有原子性。
  实测 8 个客户端改状态会让历史链断裂，6 个并发 POST 会给一个告警起 5 个任务。
  行锁是最小的修复：不引入版本列、不加重试循环、不改 API 契约。
  检测写入的瓶颈是往返次数（每告警 9 次），批量化把 6000 个告警从 25.6 s 降到 3.0 s；
  保留逐条回退是为了不丢失"并发撞键时跳过而不是失败"的语义。
- **影响**：
  - 行锁只在 PostgreSQL 生效。SQLite 忽略 `FOR UPDATE`，所以那两条回归测试在 SQLite 下
    会跳过并在理由里说明——不假装它们通过了。
  - 同一告警上的状态更新现在是串行的；这是期望行为，不是性能问题（人工操作频率极低）。
  - 批量写入失败时性能退回旧水平，但正确性不变。

## 2. 已验证的版本组合

> 本节记录 2026-10-19（`0002` 时期）的验证结果，其中的测试数量（112/113）与 head（`0002`）为历史值。
> 2026-10-23 的最新结果见 `README.md` 与 `docs/TESTING.md`（210 passed / 1 skipped，head `0004`）。

`pip install -e ".[dev]"` 在本机解析并安装的版本：

| 包 | 版本 |
| --- | --- |
| Python | 3.11.4 |
| fastapi | 0.148.0 |
| starlette | 1.9.0 |
| uvicorn | 0.54.0 |
| pydantic | 2.14.1 |
| pydantic-core | 2.50.1 |
| pydantic-settings | 2.16.0 |
| SQLAlchemy | 2.1.5 |
| alembic | 1.20.0 |
| psycopg | 3.3.6 |
| psycopg-binary | 3.3.6 |
| PyJWT | 2.15.1 |
| argon2-cffi | 25.1.0 |
| pytest | 8.4.2 |
| httpx2 | 2.14.0 |
| Node.js / npm | 24.20.0 / 11.19.0 |
| React / TypeScript | 19.3.1 / 6.0.3 |
| Vite / React Router / Axios | 8.3.5 / 7.18.4 / 1.20.0 |
| TanStack Query | 5.104.5 |
| Vitest / RTL / MSW | 5.0.5 / 16.3.3 / 3.0.3 |

验证范围：

- FastAPI 应用、全部业务路由和 `/health` API 测试通过。
- SQLAlchemy 模型注册、CHECK/唯一约束/外键和会话测试通过。
- Alembic `upgrade head` / `downgrade base` 在 PostgreSQL 16.2 上通过。
- `alembic check` 输出 `No new upgrade operations detected`；`alembic current` 为 `0002 (head)`。
- 样例数据通过 CLI 导入真实 PostgreSQL：29 行 → 24 导入、1 重复跳过、4 无效。
- AUTH-001 检测生成 2 个告警；报告证据全部来自数据库实际事件。
- 认证：Argon2id、JWT 过期/签名校验、角色变更即时生效、禁用用户拒绝。
- RBAC：admin/analyst 权限矩阵、401/403、后端强制检查。
- 审计：登录、导入、检测、报告查看、审计查看、权限拒绝。
- 真实 Uvicorn + PostgreSQL：admin/analyst 登录、admin 导入/检测/报告/审计、analyst 读 200、写/审计 403。
- SQLite 测试：112 passed, 1 skipped；PostgreSQL 测试：113 passed。
- 前端：typecheck/lint/build 通过；Vitest 24 passed；真实浏览器联调通过。
- 未执行：Docker Compose、Git 状态/差异、Linux/macOS 命令、并发/大样本性能、登录限流/MFA/令牌撤销。

兼容性结论：上述组合在当前环境中可安装、可导入、迁移和测试通过。由于 `pyproject.toml` 使用范围约束，未来重新安装可能解析到更新版本；届时应重新运行测试并更新本表。

本地验证额外使用 `pgserver` 0.1.4（嵌入式 PostgreSQL 16.2）。它**不是**项目依赖，也没有写入 `pyproject.toml`；正式环境使用 Docker Compose 或本机 PostgreSQL。
（2026-10-25 更新：本机 GBK locale 下 `pgserver` 不可用，改用 EDB 免安装二进制包 + `--locale=C`，见 D-049。）

## 3. 待定事项

| 主题 | 当前倾向 | 需要确认的问题 |
| --- | --- | --- |
| 认证方式 | 已采用 JWT HS256 + Bearer | 是否需要 SSO/MFA/刷新令牌 |
| 授权模型 | 已采用 admin/analyst 固定 RBAC | 是否需要按资产或团队授权 |
| 登录限流 | 未实现 | 应用层还是反向代理实现 |
| 令牌撤销 | 未实现 | 是否需要短期 token + 黑名单 |
| 审计保留 | 未实现 | 保留周期、归档和访问控制 |
| 多租户 | Phase 1 不引入 | 未来是否需要 `tenant_id` |
| 规则配置 | 多规则代码化 + 版本号 | 是否需要在线编辑与审批 |
| 去重策略 | 当前按规则 + 组 + 首个证据事件 | 回填更早事件时是否更新已有告警 |
| 报告结构 | 当前为固定 JSON | 是否需要持久化快照、版本和定稿 |
| 分页 | `limit` + `offset` | 事件量增长后是否改游标 |
| 速率限制 | 暂未实现 | 是否在应用层或反向代理实现 |
| 数据保留 | 原始事件 90 天 | 合规和存储成本要求 |
| 锁文件 | 暂不引入 | 是否需要哈希锁和离线安装 |
| Agent 模型 | Phase 2 决定 | 供应商、成本、数据出境约束 |
| 前端 | 暂不开发 | 何时需要，是否独立仓库 |

## 4. 已发现并处理的冲突

1. **TestClient 与 httpx**：初次安装使用 `httpx` 时，Starlette 1.9 发出弃用警告，要求 `httpx2`。已把开发依赖切换为 `httpx2`，测试无警告通过。
2. **数据库可选性与启动**：为避免无数据库时应用无法启动，`DATABASE_URL` 设为可选；需要数据库的代码路径显式报错。
3. **Compose 密码默认值**：不在仓库写入可用密码，Compose 要求从 `.env` 提供 `POSTGRES_PASSWORD`，缺失时明确失败。

## 5. 未采用的方案

| 方案 | 未采用原因 |
| --- | --- |
| Django | 首期只需要 REST API，FastAPI 的 Schema 和 OpenAPI 更直接 |
| async SQLAlchemy | 当前无高并发需求，增加会话和测试复杂度 |
| Poetry / uv | 标准 venv + pip 足够，避免额外工具链 |
| PostgreSQL 原生 ENUM | 迁移扩展成本较高 |
| passlib | 与新版 bcrypt 存在兼容问题；直接使用 argon2-cffi 更清晰 |
| python-jose | 维护活跃度和安全记录不如 PyJWT |
| 公开注册 / API 用户管理 | 增加任意创建管理员的风险；改为本地 CLI |
| 微服务 / 消息队列 | 无量化需求，违背首期最小化原则 |
| 自动响应/阻断 | 高风险能力，需人工审批和完整授权体系 |
