# 数据模型

> **状态（2026-10-23）**：`SecurityEvent`、`Alert`、`alert_events`、`User`、`AuditLog`、`InvestigationReport`、`AlertStatusHistory`、`RevokedToken`、`LoginAttempt`、`Investigation`、`InvestigationToolCall` 已实现（迁移 `0001`–`0004`）。报告支持持久化、版本与定稿；`GET /alerts/{id}/report` 仍按需生成、不写库。

## 1. 建模原则

- 主键使用 UUID。
- 时间以带时区 `TIMESTAMPTZ` 存储，应用统一按 UTC 处理。
- 原始事件只追加，不物理删除；关联表使用 `RESTRICT` 外键。
- 高频过滤字段使用普通列和索引。
- 枚举使用 `VARCHAR + CHECK`，避免 PostgreSQL 原生枚举的迁移成本。
- 生产数据库为 PostgreSQL；测试可用 SQLite，但 SQLite 不是部署目标。
- 认证相关数据与业务证据数据分离，避免用户表影响事件和告警结构。

## 2. 实体关系

```text
security_events (N) ──< alert_events >── (N) alerts
alerts (1) ──< investigation_reports (N)
alerts (1) ──< alert_status_history (N)
users (1) ──< audit_logs (N)            (actor_user_id 可空)
users (1) ──< revoked_tokens (N)        (user_id 可空)
```

- 一个 `Alert` 关联多个 `SecurityEvent`。
- 一个 `SecurityEvent` 可以参与多个 `Alert`。
- 一个 `Alert` 可以有多个报告版本，但最多一个 `finalized`。
- 一个用户可以产生多条审计记录；审计记录保留 `actor_username` 快照。
- `actor_user_id` 使用 `ON DELETE SET NULL`，没有用户删除 API。
- `login_attempts` 不关联用户表，只保存 HMAC 摘要。

## 3. security_events

表名：`security_events`

| 数据库列 | API 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `event_id` | `event_id` | `UUID` | PK | 调用方提供，全局唯一 |
| `occurred_at` | `timestamp` | `TIMESTAMPTZ` | NOT NULL | 事件发生时间；API 命名为 `timestamp` |
| `event_type` | `event_type` | `VARCHAR(100)` | NOT NULL | 事件类型，例如 `authentication` |
| `username` | `username` | `VARCHAR(255)` | NULL | 相关用户 |
| `source_ip` | `source_ip` | `VARCHAR(45)` | NULL | IPv4/IPv6 字符串；Pydantic 校验格式 |
| `asset_id` | `asset_id` | `VARCHAR(255)` | NULL | 资产标识 |
| `action` | `action` | `VARCHAR(100)` | NOT NULL | 操作，例如 `login` |
| `outcome` | `outcome` | `VARCHAR(16)` | NOT NULL，CHECK | `success` / `failure` / `unknown` |
| `raw_message` | `raw_message` | `TEXT` | NOT NULL，CHECK | 原始事件文本，长度 ≤8192 |
| `source` | `source` | `VARCHAR(64)` | NOT NULL | 事件来源 |
| `created_at` | `created_at` | `TIMESTAMPTZ` | NOT NULL，默认当前时间 | 入库时间 |

约束：

- `PRIMARY KEY (event_id)`。
- `CHECK (outcome IN ('success','failure','unknown'))`。
- `CHECK (length(raw_message) <= 8192)`。
- `source_ip` 的 IP 格式由 Pydantic `IPvAnyAddress` 校验；数据库保存规范字符串，长度为 45。

索引：

| 索引 | 列 | 用途 |
| --- | --- | --- |
| `ix_security_events_occurred_at` | `occurred_at` | 时间范围/排序 |
| `ix_security_events_type_outcome_occurred_at` | `event_type, outcome, occurred_at` | 规则筛选 |
| `ix_security_events_user_ip_occurred_at` | `username, source_ip, occurred_at` | 分组和时间窗口 |
| `ix_security_events_source` | `source` | 来源过滤 |

`timestamp` 在 ORM 中映射到 `occurred_at` 列，避免依赖 SQL 类型名作为列名。

## 4. alerts

表名：`alerts`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | `UUID` | PK | 应用生成 |
| `rule_id` | `VARCHAR(64)` | NOT NULL | 当前为 `AUTH-001` |
| `rule_version` | `VARCHAR(32)` | NOT NULL | 当前为 `1.0.0` |
| `title` | `VARCHAR(200)` | NOT NULL | 告警标题 |
| `description` | `TEXT` | NOT NULL | 规则命中说明 |
| `severity` | `VARCHAR(16)` | NOT NULL，CHECK | `info` / `low` / `medium` / `high` / `critical` |
| `status` | `VARCHAR(20)` | NOT NULL，CHECK | `open` / `acknowledged` / `investigating` / `closed` |
| `first_seen_at` | `TIMESTAMPTZ` | NOT NULL | 证据中最早事件时间 |
| `last_seen_at` | `TIMESTAMPTZ` | NOT NULL | 证据中最新事件时间 |
| `event_count` | `INTEGER` | NOT NULL | 关联证据数缓存 |
| `dedup_key` | `VARCHAR(255)` | NOT NULL，UNIQUE | 幂等去重键 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL，默认当前时间 | 创建时间 |

约束：

- `UNIQUE (dedup_key)`，名称 `uq_alerts_dedup_key`。
- `CHECK (severity IN (...))`。
- `CHECK (status IN (...))`。

索引：

- `ix_alerts_status_created_at`：按状态查看队列。
- `ix_alerts_severity_created_at`：按严重度查看。

当前告警状态只由规则写入 `open`；**没有状态更新 API**。

### dedup_key

```text
AUTH-001:<sha256("AUTH-001|username|source_ip|first_event_id")>
```

- 使用哈希是为了限制长度并避免用户名中的分隔符造成歧义。
- 同一批输入重复运行检测时，首个证据事件不变，`dedup_key` 稳定。
- 数据库唯一约束是最终防线；并发运行中的冲突会被捕获并计为 `alerts_skipped_existing`。
- 如果之后回填了更早的事件，窗口起点可能变化并产生新告警；这是当前已知限制。

## 5. alert_events

表名：`alert_events`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `alert_id` | `UUID` | FK → `alerts.id`，`ON DELETE RESTRICT` | 告警 |
| `event_id` | `UUID` | FK → `security_events.event_id`，`ON DELETE RESTRICT` | 证据事件 |
| `linked_at` | `TIMESTAMPTZ` | NOT NULL，默认当前时间 | 关联时间 |

- 复合主键 `(alert_id, event_id)`，防止重复关联。
- `ix_alert_events_event_id` 支持从事件反查告警。
- 外键使用 `RESTRICT`，证据不能被级联删除。

## 6. users

表名：`users`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | `UUID` | PK | 应用生成 |
| `username` | `VARCHAR(64)` | NOT NULL，UNIQUE | 统一小写 |
| `password_hash` | `VARCHAR(255)` | NOT NULL | Argon2id 哈希，不含明文 |
| `role` | `VARCHAR(16)` | NOT NULL，CHECK | `admin` / `analyst` |
| `is_active` | `BOOLEAN` | NOT NULL，默认 true | 禁用后现有 token 立即失效 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL，默认当前时间 | 创建时间 |
| `last_login_at` | `TIMESTAMPTZ` | NULL | 最近成功登录时间 |

约束：

- `uq_users_username`。
- `ck_users_role`：`role IN ('admin','analyst')`。
- `ck_users_username_lower`：`username = lower(username)`。
- `ck_users_username_length`：长度 3–64。
- 用户名格式由 Pydantic 校验：`[a-z0-9][a-z0-9._-]{2,63}`。
- 密码长度由 CLI/服务校验：12–128 字符。

没有公开注册或 API 用户管理接口；用户通过 `sentinelflow-create-user` 本地命令创建。

## 7. audit_logs

表名：`audit_logs`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | `UUID` | PK | 应用生成 |
| `actor_user_id` | `UUID` | NULL，FK → `users.id` | `ON DELETE SET NULL` |
| `actor_username` | `VARCHAR(64)` | NULL | 用户名快照 |
| `action` | `VARCHAR(64)` | NOT NULL | 例如 `auth.login` |
| `resource_type` | `VARCHAR(64)` | NULL | 例如 `alert`、`user` |
| `resource_id` | `VARCHAR(128)` | NULL | 资源 ID |
| `outcome` | `VARCHAR(16)` | NOT NULL，CHECK | `success` / `failure` / `denied` |
| `source_ip` | `VARCHAR(45)` | NULL | 请求来源 |
| `request_id` | `VARCHAR(64)` | NULL | 请求追踪 ID |
| `details` | `JSON` | NULL | 非敏感结构化上下文 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL，默认当前时间 | 操作时间 |

约束与索引：

- `ck_audit_logs_outcome`。
- `ix_audit_logs_actor_created_at`。
- `ix_audit_logs_action_created_at`。
- `ix_audit_logs_created_at`。

审计原则：

- 应用层 append-only，没有更新/删除 API。
- 不保存密码、JWT、API Key、密码哈希或完整 raw_message。
- 登录失败不保存尝试的用户名；如果账户存在，只保存内部 `actor_user_id`。
- 报告查看、审计查看和权限拒绝都会记录。

## 8. investigation_reports

表名：`investigation_reports`（迁移 `0003`）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | `UUID` | PK | 报告版本 ID |
| `alert_id` | `UUID` | FK → `alerts.id`，`ON DELETE RESTRICT` | 关联告警 |
| `version` | `INTEGER` | NOT NULL，≥1 | 同一告警内递增 |
| `status` | `VARCHAR(20)` | NOT NULL，CHECK | `draft` / `finalized` / `superseded` |
| `generator` | `VARCHAR(32)` | NOT NULL，CHECK | `deterministic` / `agent` |
| `generator_version` | `VARCHAR(32)` | NOT NULL | 生成器版本，例如 `1.0.0` |
| `input_snapshot` | `JSON` | NOT NULL | 创建时的告警字段与证据 ID 快照 |
| `content` | `JSON` | NOT NULL | 渲染后的报告正文 |
| `evidence_count` | `INTEGER` | NOT NULL | 快照时证据总数 |
| `evidence_truncated` | `BOOLEAN` | NOT NULL | 快照时证据是否被截断 |
| `created_by_user_id` / `created_by_username` | `UUID` / `VARCHAR(64)` | NULL | 创建人 |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | 创建时间 |
| `finalized_at` | `TIMESTAMPTZ` | NULL | 定稿时间 |
| `finalized_by_user_id` / `finalized_by_username` | `UUID` / `VARCHAR(64)` | NULL | 定稿人 |

约束与索引：

- `uq_investigation_reports_alert_version`：`(alert_id, version)` 唯一，保证版本号可追溯且并发安全。
- `ck_investigation_reports_status`、`ck_investigation_reports_generator`、`ck_investigation_reports_version`。
- `ck_investigation_reports_finalized_at`：`status <> 'finalized' OR finalized_at IS NOT NULL`。
- `ix_investigation_reports_alert_version`、`ix_investigation_reports_status`。

### 快照与当前数据的区别

- `input_snapshot.evidence_ids` 记录**报告生成时**使用的证据事件 ID。
- `content.evidence` 是**报告生成时**渲染出的证据字段值。
- 两者都是时间点快照。之后如果事件被补充、规则版本升级或代码变更，**当前** `security_events` 与 `alerts` 中的值可能与报告内容不同；已定稿报告不会因此改变。
- 需要当前状态时，应查询 `GET /api/v1/alerts/{id}` 或 `GET /api/v1/alerts/{id}/evidence`，而不是读取报告快照。

### 状态语义

- `draft`：可继续修订；可被定稿。
- `finalized`：不可修改；同一告警最多一个 `finalized` 版本。
- `superseded`：被同一告警更新版本的定稿取代；不可再定稿。

`GET /api/v1/alerts/{id}/report` 仍然**按需生成、不写库**，不产生任何 `investigation_reports` 行。

## 8.1 alert_status_history

表名：`alert_status_history`（迁移 `0003`）

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `id` | `UUID` | PK |
| `alert_id` | `UUID` | FK → `alerts.id`，`ON DELETE RESTRICT` |
| `from_status` | `VARCHAR(20)` | NULL，CHECK |
| `to_status` | `VARCHAR(20)` | NOT NULL，CHECK |
| `changed_by_user_id` | `UUID` | NULL，FK → `users.id` `SET NULL` |
| `changed_by_username` | `VARCHAR(64)` | NULL |
| `reason` | `VARCHAR(500)` | NULL |
| `created_at` | `TIMESTAMPTZ` | NOT NULL |

- 应用层 append-only，没有更新/删除接口。
- 索引 `ix_alert_status_history_alert_created`。
- `closed → open` 必须带 `reason`。

## 8.2 revoked_tokens

表名：`revoked_tokens`（迁移 `0003`）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `jti` | `UUID` | PK，JWT 唯一标识 |
| `user_id` | `UUID` | NULL，FK → `users.id` `SET NULL` |
| `expires_at` | `TIMESTAMPTZ` | NOT NULL，用于过期清理 |
| `revoked_at` | `TIMESTAMPTZ` | NOT NULL |
| `reason` | `VARCHAR(64)` | NOT NULL，例如 `logout` |

**只保存 token 标识，不保存 token 本身、密码或 API Key。**

## 8.3 login_attempts

表名：`login_attempts`（迁移 `0003`）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `UUID` | PK |
| `subject_hash` | `VARCHAR(64)` | `HMAC-SHA256(JWT_SECRET, "subject\|username\|ip")` |
| `ip_hash` | `VARCHAR(64)` | NULL，`HMAC-SHA256(JWT_SECRET, "ip\|ip")` |
| `succeeded` | `BOOLEAN` | 成功/失败 |
| `attempted_at` | `TIMESTAMPTZ` | 尝试时间 |

- **不保存明文用户名或 IP**，与“登录失败不记录尝试用户名”的审计原则一致。
- 成功登录会删除该 subject 的失败记录，从而重置计数。
- 索引：`(subject_hash, attempted_at)`、`(ip_hash, attempted_at)`、`attempted_at`。

## 8.4 investigations

表名：`investigations`（迁移 `0004`）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `UUID` | PK |
| `alert_id` | `UUID` | FK → `alerts.id` `RESTRICT` |
| `status` | `VARCHAR(20)` | CHECK：`pending` / `running` / `succeeded` / `failed` / `limit_reached` |
| `model_provider` / `model_name` | `VARCHAR` | 实际使用的提供方与模型名（便于事后复盘） |
| `prompt_version` | `VARCHAR(32)` | 提示词/编排版本 |
| `rounds_used` / `tool_calls_used` | `INTEGER` | 实际消耗的预算 |
| `error` | `VARCHAR(500)` | 失败原因（已截断、不含敏感内容） |
| `error_code` | `VARCHAR(32)` | 机器可读原因：`model_timeout` / `model_transient` / `model_invalid_output` / `citation_invalid` / `budget_exhausted` / `interrupted` / `crashed` / `context_missing` |
| `attempt_count` | `INTEGER` | 已被 worker 领取的次数 |
| `max_attempts` | `INTEGER` | 领取上限（默认 2） |
| `lease_expires_at` | `TIMESTAMPTZ` | 当前 worker 的租约到期时间；过期即可被重新领取 |
| `next_attempt_at` | `TIMESTAMPTZ` | 重试退避的最早可领取时间 |
| `started_at` | `TIMESTAMPTZ` | 首次被领取的时间（区别于 `created_at`） |
| `request_id` | `VARCHAR(64)` | 创建该调查的 HTTP 请求 ID，与响应头/审计对齐 |
| `duration_ms` | `INTEGER` | 端到端耗时，终止时写入 |
| `report_id` | `UUID` | FK → `investigation_reports.id` `SET NULL`，成功时指向草稿 |
| `created_by_user_id` / `created_by_username` | | 发起人 |
| `created_at` / `completed_at` | `TIMESTAMPTZ` | |

- 记录在调用模型**之前**以 `pending` 写入，因此崩溃或重启后任务仍在队列里。
- **应用层约束**：同一 `alert_id` 同时最多一个"未过期"的 `pending`/`running` 调查；这是服务层检查而非数据库唯一约束（过期行需要允许新任务启动）。
- **状态机**：`pending → running → succeeded | failed | limit_reached`；`running` 租约过期后回到 `pending`（还有次数）或转为 `failed(error_code=interrupted)`。
- 索引 `ix_investigations_queue(status, next_attempt_at)` 支撑领取查询。
- 索引：`(alert_id, created_at)`、`status`。

## 8.5 investigation_tool_calls

表名：`investigation_tool_calls`（迁移 `0004`）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `UUID` | PK |
| `investigation_id` | `UUID` | FK → `investigations.id` `CASCADE` |
| `sequence` | `INTEGER` | 调用顺序（每次尝试从 1 开始） |
| `attempt_index` | `INTEGER` | 第几次尝试产生该调用 |
| `tool_name` | `VARCHAR(64)` | 工具名 |
| `arguments` | `JSON` | 模型提出的参数（已通过 Schema 校验或标记为 invalid） |
| `status` | `VARCHAR(16)` | CHECK：`ok` / `error` / `timeout` / `denied` / `invalid` |
| `result_summary` | `JSON` | 结果摘要：计数与事件 ID，**不含 raw_message** |
| `error` | `VARCHAR(500)` | 错误摘要 |
| `duration_ms` | `INTEGER` | 耗时 |

- 不保存模型提示词、模型原始响应或日志原文。
- `denied` 同时覆盖“工具不在白名单”和“调用者缺少所需权限”。
- 索引：`(investigation_id, sequence)`。

## 8.6 investigation_rounds

表名：`investigation_rounds`（迁移 `0005`）

每次模型调用一条，用于回答"卡在第几轮、花了多久"。**只存元数据**。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `UUID` | PK |
| `investigation_id` | `UUID` | FK → `investigations.id` `CASCADE` |
| `round_index` | `INTEGER` | 第几轮，≥1 |
| `latency_ms` | `INTEGER` | 该轮模型调用耗时 |
| `outcome` | `VARCHAR(20)` | CHECK：`tool_calls` / `findings` / `error` / `budget_exhausted` |
| `tool_call_count` | `INTEGER` | 该轮发起的工具数 |
| `error` | `VARCHAR(500)` | 脱敏错误摘要 |

- 唯一约束 `(investigation_id, attempt_index, round_index)`：重试会从第 1 轮重新开始，所以必须按"第几次尝试"区分。
- 索引 `(investigation_id, attempt_index, round_index)`。
- **不存**提示词、模型原始响应、`raw_message`。
- `rounds_used` 统计"完成的模型轮次"，`rounds` 行数统计"尝试的轮次"；模型首轮即失败时后者为 1、前者为 0。

## 9. 迁移

- 首次迁移：`migrations/versions/0001_core_tables.py`。
- 认证与审计迁移：`migrations/versions/0002_users_and_audit.py`。
- 报告/状态/安全迁移：`migrations/versions/0003_reports_status_and_security.py`。
- Agent 调查迁移：`migrations/versions/0004_investigations.py`。
- 追踪迁移：`migrations/versions/0005_investigation_rounds.py`。
- 持久化队列迁移：`migrations/versions/0006_investigation_queue.py`。
- 当前 head：`0006`。
- 已验证：`0001`+`0002` 的 `upgrade head` / `downgrade base` 在 PostgreSQL 16.2 上成功（历史记录）；`0003` 与 `0004` 目前只在 SQLite 元数据层面验证，**PostgreSQL 验证待补做**。
- `0003` / `0004` / `0005` 均为纯增量迁移，不修改既有表结构，且可逐级单独回退。
- 升级后存在：`security_events`、`alerts`、`alert_events`、`users`、`audit_logs`、`investigation_reports`、`alert_status_history`、`revoked_tokens`、`login_attempts`、`investigations`、`investigation_tool_calls`、`investigation_rounds`、`alembic_version`（共 12 张表 + `alembic_version`）。
- 回滚到认证前：`alembic downgrade 0001`，会删除 `audit_logs` 和 `users`，不影响事件和告警数据。
- 数据库结构以 Alembic 为唯一来源；应用启动时不会自动建表。

## 10. 计划中的实体

以下实体尚未实现：

- `rules`：规则在线管理（当前规则版本化在代码中）。
- `investigation_eval_cases`：固定评测集的持久化（当前评测集以测试代码形式存在）。

## 11. 数据生命周期（计划）

- 原始事件默认保留 90 天；具体周期待合规确认。
- 关闭告警不删除证据。
- 报告和审计数据保留更久，需备份和清理审批。
- 审计记录当前没有自动清理/归档，需要后续实现。
- 测试数据只能使用合成内容，禁止真实日志、个人信息和凭据。

## 12. 与早期设计的差异

| 早期计划 | 当前实现 | 原因 |
| --- | --- | --- |
| `source_ip INET` | `VARCHAR(45)` + Pydantic IP 校验 | 保持 SQLite 测试可移植；PostgreSQL 仍有长度约束 |
| `InvestigationReport` 表 | 已实现 `investigation_reports`（版本 + 快照 + 定稿） | Phase 1 后半段补齐持久化 |
| 事件主键 `id` + `occurred_at` | `event_id` 主键；API `timestamp`，DB `occurred_at` | 对齐任务要求并避免列名歧义 |
| Repository 层 | 服务层直接使用 `Session` | 当前查询简单，避免无收益抽象 |
| 无认证/审计 | Argon2id + JWT + RBAC + append-only 审计 | 当前阶段安全要求 |
| 进程内限流 | 数据库 `login_attempts` | 多 worker / 重启后仍有效 |
