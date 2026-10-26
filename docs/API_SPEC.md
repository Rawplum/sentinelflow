# API 规范

## 1. 通用约定

- 本地基础 URL：`http://127.0.0.1:8000`
- 业务接口前缀：`/api/v1`；`/health` 不版本化。
- 请求与响应：UTF-8 JSON，字段使用 `snake_case`。
- ID：字符串形式的 UUID。
- 时间：ISO 8601 UTC，例如 `2026-10-19T09:00:00Z`。输入必须带时区。
- 写接口未知字段：请求 Schema 使用 `extra="forbid"`，返回 422。
- 单批事件导入上限：500 条。
- 单条 `raw_message` 上限：8192 字符。
- `limit` 范围：1–200；`offset` ≥ 0。
- 报告内嵌证据上限：100 条（`evidence_limit` 1–100）。
- 证据分页上限：200 条。
- 认证：除 `/health` 和 `/api/v1/auth/login` 外，所有接口都要求 `Authorization: Bearer <jwt>`。
- 当前没有公开注册接口；用户只能通过本地 CLI 创建。
- API 文档：`/docs`、`/redoc`、`/openapi.json`。

## 2. 角色与权限

| 权限 | admin | analyst |
| --- | --- | --- |
| `events:read` | 是 | 是 |
| `events:import` | 是 | 否 |
| `detections:run` | 是 | 否 |
| `alerts:read` | 是 | 是 |
| `alerts:write` | 是 | 否 |
| `reports:read` | 是 | 是 |
| `reports:write` | 是 | 否 |
| `reports:finalize` | 是 | 否 |
| `audit:read` | 是 | 否 |

权限在后端统一检查，不能通过隐藏前端按钮替代。越权返回 403。

**analyst 权限未扩大**：新增的 `alerts:write`、`reports:write`、`reports:finalize` 全部只授予 admin。原因是没有“告警归属人”模型，无法界定 analyst 可以修改哪些告警；授予写权限需要单独的授权模型决策。

## 3. 已实现接口

### 3.1 GET /health

公开，存活检查，不访问数据库。

响应 `200 OK`：

```json
{
  "status": "ok",
  "service": "SentinelFlow",
  "version": "0.1.0",
  "environment": "development"
}
```

### 3.2 POST /api/v1/auth/login

公开。用户名不区分大小写输入，服务端统一转为小写。

请求：

```json
{
  "username": "admin",
  "password": "<your-password>"
}
```

响应 `200 OK`：

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "expires_in": 1800,
  "username": "admin",
  "role": "admin"
}
```

失败：

- 未知用户、错误密码、禁用用户统一返回 `401 {"detail": "Invalid username or password"}`。
- 未配置 `JWT_SECRET` 返回 `503 {"detail": "Authentication is not configured"}`。
- 密码不会出现在响应中；校验错误也不会回显客户端输入。

### 3.3 GET /api/v1/auth/me

需要 Bearer token，任意已激活角色可访问。

```json
{
  "id": "<user-uuid>",
  "username": "analyst1",
  "role": "analyst",
  "is_active": true,
  "created_at": "2026-10-19T14:20:00Z",
  "last_login_at": "2026-10-19T15:00:00Z"
}
```

不返回密码哈希。

### 3.4 POST /api/v1/events/import

需要 `events:import`，即 admin。

请求：

```json
{
  "events": [
    {
      "event_id": "11111111-1111-4111-8111-111111111111",
      "timestamp": "2026-10-19T09:00:00Z",
      "event_type": "authentication",
      "username": "alice.demo",
      "source_ip": "198.51.100.10",
      "asset_id": "workstation-01",
      "action": "login",
      "outcome": "failure",
      "raw_message": "synthetic event: failed password for alice.demo",
      "source": "synthetic-auth"
    }
  ]
}
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

重复导入同一 `event_id` 会返回 `imported: 0` 和 `skipped: 1`。整批校验失败返回 422，不会部分导入。

### 3.5 GET /api/v1/events

需要 `events:read`，admin 和 analyst 都可访问。

查询参数（全部可选）：

| 参数 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- |
| `limit` | 50 | 1–200 | 页大小 |
| `offset` | 0 | ≥0 | 跳过行数 |
| `event_type` | 无 | ≤100 字符 | 精确匹配 |
| `username` | 无 | ≤255 字符 | 精确匹配 |
| `source_ip` | 无 | ≤45 字符 | 精确匹配 |
| `asset_id` | 无 | ≤255 字符 | 精确匹配 |
| `action` | 无 | ≤100 字符 | 精确匹配 |
| `outcome` | 无 | `success` / `failure` / `unknown` | 精确匹配 |
| `q` | 无 | 1–200 字符 | 对 `raw_message` 的大小写不敏感子串匹配 |
| `start` | 无 | 带时区的 ISO 8601 | 事件时间 ≥ `start` |
| `end` | 无 | 带时区的 ISO 8601 | 事件时间 ≤ `end` |
| `include_raw_message` | `true` | 布尔 | 设为 `false` 时响应中的 `raw_message` 为 `null` |

约束：

- `q` 中的 `%` 和 `_` 按字面量处理，不会被当作通配符。
- 所有过滤条件都通过 SQLAlchemy 参数化，不存在字符串拼接 SQL。
- 只能按上表列出的字段过滤，没有自由查询语言。
- `start > end` 返回 422。

响应：

```json
{
  "items": [
    {
      "event_id": "11111111-1111-4111-8111-111111111111",
      "timestamp": "2026-10-19T09:00:00Z",
      "event_type": "authentication",
      "username": "alice.demo",
      "source_ip": "198.51.100.10",
      "asset_id": "workstation-01",
      "action": "login",
      "outcome": "failure",
      "raw_message": "synthetic event: failed password for alice.demo",
      "source": "synthetic-auth",
      "created_at": "2026-10-19T14:20:00Z"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

### 3.6 POST /api/v1/detections/run

需要 `detections:run`，即 admin。

响应 `200 OK`：

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

重复运行同一数据时 `alerts_created` 为 0，`alerts_skipped_existing` 反映已存在的告警。

### 3.7 GET /api/v1/alerts

需要 `alerts:read`，admin 和 analyst 都可访问。

查询参数同事件列表。

响应：

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

### 3.8 GET /api/v1/alerts/{alert_id}/report

需要 `reports:read`，admin 和 analyst 都可访问。报告按需生成，**不写库**。

查询参数：

| 参数 | 默认 | 约束 |
| --- | --- | --- |
| `evidence_limit` | 100 | 1–100（硬上限） |
| `evidence_offset` | 0 | ≥0 |

响应在上述字段之外还包含：

```json
{
  "evidence_total": 150,
  "evidence_truncated": true
}
```

响应（示例，含新增的 `evidence_total` / `evidence_truncated`）：

```json
{
  "alert_id": "<alert-uuid>",
  "summary": "Rule AUTH-001 identified 5 failed authentication attempts for user 'alice.demo' from 198.51.100.10 between 2026-10-19T09:00:00+00:00 and 2026-10-19T09:04:00+00:00.",
  "risk_level": "high",
  "evidence": [
    {
      "event_id": "11111111-1111-4111-8111-111111111111",
      "timestamp": "2026-10-19T09:00:00Z",
      "event_type": "authentication",
      "username": "alice.demo",
      "source_ip": "198.51.100.10",
      "asset_id": "workstation-01",
      "action": "login",
      "outcome": "failure",
      "source": "synthetic-auth",
      "raw_message": "synthetic event: failed password for alice.demo"
    }
  ],
  "timeline": [
    {
      "timestamp": "2026-10-19T09:00:00Z",
      "event_id": "11111111-1111-4111-8111-111111111111",
      "description": "login failure for user 'alice.demo' from 198.51.100.10 on asset 'workstation-01'"
    }
  ],
  "reasoning": "Rule AUTH-001 (version 1.0.0) fires when the same username and source IP produce at least 5 failed authentication/login events within a 5-minute window. ...",
  "recommended_actions": [
    "Verify whether the source IP is expected for this user ...",
    "Review authentication, VPN, and application logs ...",
    "Check whether any successful login followed the failures ...",
    "Contact the account owner or identity team ...",
    "Escalate the alert to a human analyst ...; do not take automated blocking or account-disabling actions."
  ],
  "limitations": [
    "This rule detects a pattern of failed authentication attempts; it does not prove that a system was compromised.",
    "The analysis covers only imported event data. ...",
    "Event timestamps depend on source clocks ...",
    "A successful login after the failures may be legitimate or malicious ...",
    "The deterministic report does not use an LLM ...",
    "Raw messages are included as evidence and may contain sensitive data ..."
  ]
}
```

保证：

- `evidence[*].event_id` 来自数据库实际事件，且生成前会重新校验。
- `timeline` 按事件时间升序，条数与本次返回的 `evidence` 一致。
- `evidence` 最多 100 条；`evidence_total` 始终是完整证据数，`evidence_truncated` 表示本次是否为子集。
- 该 GET 请求**不产生任何写入**（除审计外），因此刷新页面不会创建报告版本。
- 报告查看会产生 `reports.view` 审计记录。

### 3.9 GET /api/v1/alerts/{alert_id}

需要 `alerts:read`。返回告警详情及状态历史，供前端刷新后仍能渲染真实告警信息。

```json
{
  "id": "<alert-uuid>",
  "rule_id": "AUTH-001",
  "rule_version": "1.0.0",
  "title": "Suspicious login activity",
  "description": "...",
  "severity": "high",
  "status": "acknowledged",
  "first_seen_at": "2026-10-19T09:00:00Z",
  "last_seen_at": "2026-10-19T09:04:00Z",
  "event_count": 5,
  "created_at": "2026-10-19T14:20:00Z",
  "evidence_count": 5,
  "status_history": [
    {
      "from_status": "open",
      "to_status": "acknowledged",
      "changed_by_username": "admin",
      "reason": "triaged",
      "created_at": "2026-10-19T15:00:00Z"
    }
  ]
}
```

未知告警返回 404。

### 3.10 PATCH /api/v1/alerts/{alert_id}

需要 `alerts:write`，即 admin。

请求：

```json
{"status": "acknowledged", "reason": "triaged"}
```

`reason` 可选（≤500 字符），但 `closed → open` 必须提供。

合法转换：

```text
open          → acknowledged, investigating, closed
acknowledged  → investigating, closed
investigating → closed
closed        → open   (必须带 reason)
```

行为：

- 合法转换：更新 `status`，追加 `alert_status_history`，写 `alerts.status_change` 审计，三者在同一事务提交。
- 与当前状态相同：返回 200 且不写历史（幂等），审计标记 `noop: true`。
- 非法转换：`409 {"detail": "Illegal status transition from 'x' to 'y'"}`。
- `closed → open` 缺少 reason：422。
- 未知告警：404。

响应体与 `GET /api/v1/alerts/{alert_id}` 相同（含最新 `status_history`）。

### 3.11 GET /api/v1/alerts/{alert_id}/evidence

需要 `alerts:read`。证据分页遍历，用于超过报告证据上限的告警。

| 参数 | 默认 | 约束 |
| --- | --- | --- |
| `limit` | 50 | 1–200 |
| `offset` | 0 | ≥0 |
| `include_raw_message` | `false` | 布尔 |

```json
{
  "items": [
    {
      "event_id": "...",
      "timestamp": "2026-10-19T09:00:00Z",
      "event_type": "authentication",
      "username": "alice.demo",
      "source_ip": "198.51.100.10",
      "asset_id": "workstation-01",
      "action": "login",
      "outcome": "failure",
      "source": "synthetic-auth",
      "raw_message": null
    }
  ],
  "total": 150,
  "limit": 50,
  "offset": 0
}
```

该接口默认不返回 `raw_message`（最小数据原则）；报告接口为兼容性仍返回。

### 3.12 POST /api/v1/alerts/{alert_id}/reports

需要 `reports:write`，即 admin。生成并持久化一个草稿版本。

请求体可选：`{"note": "..."}`（≤500 字符，仅记录在审计中）。

响应 `201 Created`：

```json
{
  "id": "<report-uuid>",
  "alert_id": "<alert-uuid>",
  "version": 1,
  "status": "draft",
  "generator": "deterministic",
  "generator_version": "1.0.0",
  "evidence_count": 5,
  "evidence_truncated": false,
  "created_by_username": "admin",
  "created_at": "2026-10-19T15:00:00Z",
  "finalized_at": null,
  "finalized_by_username": null,
  "content": { "...InvestigationReportResponse..." }
}
```

- 版本号 = 该告警现有最大版本 + 1，由 `(alert_id, version)` 唯一约束保证。
- `content` 是生成时的渲染结果；`input_snapshot` 不在响应中，仅存库。
- 并发冲突返回 409。

### 3.13 GET /api/v1/alerts/{alert_id}/reports

需要 `reports:read`。返回版本列表，按版本号降序。

```json
{"items": ["...InvestigationReportRead..."], "total": 2}
```

### 3.14 GET /api/v1/reports/{report_id}

需要 `reports:read`。返回单个持久化版本，结构与 3.12 响应一致。产生 `reports.read` 审计。

### 3.15 POST /api/v1/reports/{report_id}/finalize

需要 `reports:finalize`，即 admin。

- 草稿 → `finalized`，写入 `finalized_at` / `finalized_by_*`。
- 同一告警先前 `finalized` 的版本自动变为 `superseded`。
- 已定稿或已取代的版本再次定稿返回 409。
- 定稿后不可修改；修订必须 `POST` 新版本。
- 产生 `reports.finalize` 审计。

### 3.16 POST /api/v1/auth/logout

需要 Bearer token。返回 `204 No Content`。

- 将该 token 的 `jti` 写入 `revoked_tokens`，token 立即失效。
- 只保存标识，不保存 token 本身。
- 同一 token 重复登出返回 401（已被撤销）。
- 不影响该用户其他 token。
- 产生 `auth.logout` 审计。

### 3.17 POST /api/v1/alerts/{alert_id}/investigations

需要 `reports:write`，即 admin。把调查**持久化入队**，立即返回，不等待模型。

前置：必须配置 `LLM_PROVIDER`、`LLM_MODEL`、`LLM_API_BASE`、`LLM_API_KEY`。未配置时返回
`503 {"detail": "AI agent is not configured"}`，其余接口不受影响。

行为：

1. 校验告警存在（否则 404）。
2. 写入 `investigations` 记录（状态 `pending`）并提交，返回 `202 Accepted`。
3. 进程内的队列 worker 领取任务（`running`，带租约）后执行。
4. 客户端轮询 `GET /api/v1/investigations/{id}` 直到终态。

**请求不会调用模型**，因此慢 provider 不会导致 HTTP 超时；任务在数据库里，进程重启后仍会被领取。
3. 在**只读白名单工具**范围内循环调用模型，最多 `AGENT_MAX_ROUNDS`（默认 5）轮、
   `AGENT_MAX_TOOL_CALLS`（默认 8）次工具调用，单工具超时 `AGENT_TOOL_TIMEOUT_SECONDS`（默认 5 秒）。
4. 校验模型输出的结构化结论；每个 `cited_event_ids` 必须是该告警的真实证据，否则整次调查失败。
5. 成功时创建 `generator='agent'` 的**草稿**报告版本，等待人工审核和定稿。

**并发保护**：同一告警同一时间只允许一个未过期的 `pending`/`running` 调查（服务端强制，不依赖前端禁用按钮）。
已存在未过期的运行中调查时返回 `409`：

```json
{"detail": "Investigation <uuid> is already running for this alert"}
```

超过 `AGENT_STALE_AFTER_SECONDS` 的 `running` 记录不参与该判断，避免崩溃的 worker 永久锁死告警。

响应 `202 Accepted`（创建瞬间，`rounds` / `tool_calls` 为空）：

```json
{
  "id": "<investigation-uuid>",
  "alert_id": "<alert-uuid>",
  "status": "running",
  "model_provider": "openai",
  "model_name": "<model>",
  "prompt_version": "1.0.0",
  "rounds_used": 0,
  "tool_calls_used": 0,
  "error": null,
  "error_code": null,
  "attempt_count": 0,
  "max_attempts": 2,
  "request_id": "<x-request-id>",
  "duration_ms": null,
  "report_id": null,
  "created_by_username": "admin",
  "created_at": "2026-10-23T10:00:00Z",
  "completed_at": null,
  "started_at": null,
  "rounds": [],
  "tool_calls": [
    {
      "sequence": 1,
      "attempt_index": 1,
      "tool_name": "get_alert_details",
      "arguments": {},
      "status": "ok",
      "result_summary": {"alert_id": "<alert-uuid>", "total": 5},
      "error": null,
      "duration_ms": 3,
      "created_at": "2026-10-23T10:00:04Z"
    }
  ]
}
```

`status` 取值：

| 值 | 含义 | 是否产出报告 |
| --- | --- | --- |
| `pending` | 已入队，等待 worker 领取 | 否 |
| `running` | worker 已领取并持有租约 | 否 |
| `succeeded` | 模型给出结论且引用全部有效 | 是（draft） |
| `failed` | 模型调用失败、输出不合规或引用无效 | 否 |
| `limit_reached` | 轮次或工具调用预算耗尽 | 否 |

**重试**：只有可恢复的模型错误（传输错误、超时、5xx、429）会回到 `pending` 并带退避，
受 `AGENT_MAX_ATTEMPTS`（默认 2）限制。Schema 违规、引用无效、预算耗尽属于确定性失败，不重试。
工具超时在单次运行内记录并恢复，不触发任务级重试。

**进程中断**：`running` 的租约（`AGENT_LEASE_SECONDS`，默认 120 秒）过期后，任务可被重新领取；
若已达 `max_attempts`，则转 `failed`，`error_code=interrupted`。不存在永久 `running` 的任务。

`error_code` 取值：`model_timeout` / `model_transient` / `model_invalid_output` / `citation_invalid` /
`budget_exhausted` / `interrupted` / `crashed` / `context_missing`。

工具调用 `status`：`ok` / `error` / `timeout` / `denied` / `invalid`。
`denied` 表示工具不在白名单或调用者缺少该工具所需权限。

工具白名单（全部只读，且只能访问本告警的证据）：

| 工具 | 参数 | 用途 |
| --- | --- | --- |
| `get_alert_details` | 无 | 告警字段、证据总数、状态历史 |
| `get_related_events` | `limit` 1–50、`offset` ≥0 | 分页读取本告警证据 |
| `search_events` | `keyword` ≤100、`outcome`、`action`、`limit` 1–50 | 在本告警证据内检索 |
| `search_runbooks` | `query` 1–100、`limit` 1–5 | 检索本地离线 runbook |

### 3.18 GET /api/v1/investigations/{investigation_id}

需要 `reports:read`。返回调查状态、**逐轮模型耗时**、工具调用日志与耗时。

响应在 3.17 的字段之外还包括：

```json
{
  "status": "succeeded",
  "rounds_used": 3,
  "tool_calls_used": 2,
  "duration_ms": 1450,
  "report_id": "<report-uuid>",
  "rounds": [
    {
      "round_index": 1,
      "attempt_index": 1,
      "latency_ms": 620,
      "outcome": "tool_calls",
      "tool_call_count": 1,
      "error": null,
      "created_at": "2026-10-23T10:00:01Z"
    },
    {
      "round_index": 2,
      "latency_ms": 830,
      "outcome": "findings",
      "tool_call_count": 0,
      "error": null,
      "created_at": "2026-10-23T10:00:02Z"
    }
  ]
}
```

`rounds[].outcome`：`tool_calls` / `findings` / `error` / `budget_exhausted`。

- 只保存元数据：**不保存**模型提示词、模型原始响应、`raw_message`。
- **中断回收**：状态为 `running` 且创建时间超过 `AGENT_STALE_AFTER_SECONDS`（默认 600 秒）的调查，
  在读取时会被标记为 `failed`，`error = "Investigation did not finish (interrupted or timed out)"`，
  不会永久停留在运行中。
- 未知调查返回 404。

### 3.19 GET /api/v1/audit-logs

需要 `audit:read`，即 admin。

查询参数：

| 参数 | 默认 | 约束 |
| --- | --- | --- |
| `limit` | 50 | 1–200 |
| `offset` | 0 | ≥0 |
| `action` | 无 | ≤64 字符，精确匹配 |

响应：

```json
{
  "items": [
    {
      "id": "<audit-uuid>",
      "actor_user_id": "<user-uuid>",
      "actor_username": "admin",
      "action": "events.import",
      "resource_type": null,
      "resource_id": null,
      "outcome": "success",
      "source_ip": "127.0.0.1",
      "request_id": "<request-id>",
      "details": {
        "received": 5,
        "imported": 5,
        "skipped": 0
      },
      "created_at": "2026-10-19T15:00:00Z"
    }
  ],
  "total": 10,
  "limit": 50,
  "offset": 0
}
```

审计记录只读；没有更新或删除接口。审计查询本身会产生 `audit.view` 记录。

### 3.20 审计动作

| action | 说明 |
| --- | --- |
| `auth.login` | 登录成功 |
| `auth.login_failed` | 登录失败（不记录尝试的用户名/密码） |
| `auth.login_throttled` | 登录被限流（不记录尝试的用户名） |
| `auth.logout` | 令牌被撤销 |
| `auth.inactive_user` | 禁用用户持有有效 token |
| `events.import` | 事件导入成功 |
| `detections.run` | 检测执行成功 |
| `alerts.status_change` | 告警状态变更（含 `from_status`/`to_status`/`noop`） |
| `reports.view` | 查看按需生成的调查报告 |
| `reports.create` | 创建报告版本 |
| `reports.read` | 读取持久化报告 |
| `reports.finalize` | 报告定稿 |
| `investigations.run` | 调查被创建并入队（`status: running`） |
| `investigations.complete` | 调查结束（含最终状态、轮次、工具调用次数、耗时、报告 ID） |
| `audit.view` | 查看审计列表 |
| `authorization.denied` | 权限不足 |
| `users.create` | 本地 CLI 创建用户 |

## 4. 错误处理

| 状态码 | 场景 |
| --- | --- |
| `200` | 查询/检测/报告成功 |
| `201` | 事件导入成功；报告版本创建成功 |
| `204` | 登出成功（无响应体） |
| `401` | 缺少、无效、过期或已撤销 token；登录凭据错误 |
| `403` | 已认证但权限不足 |
| `404` | 未知告警、报告或路由 |
| `405` | 对只读审计接口使用不支持的 HTTP 方法 |
| `409` | 非法的告警状态转换；对已定稿/已取代报告重复定稿；报告版本并发冲突 |
| `422` | Schema、UUID、分页参数、IP、时间格式错误；`closed → open` 缺少 reason |
| `429` | 登录失败次数超限，响应带 `Retry-After` |
| `500` | 未处理的数据库错误，响应不泄露内部细节 |
| `503` | `JWT_SECRET` 缺失或过短；Agent 模型未配置 |

401 响应包含：

```json
{"detail": "Could not validate credentials"}
```

403 响应：

```json
{"detail": "Forbidden"}
```

422 只返回 `type`、`loc`、`msg`，**不回显 `input`**：

```json
{
  "detail": [
    {
      "type": "timezone_aware",
      "loc": ["body", "events", 0, "timestamp"],
      "msg": "Input should have timezone info"
    }
  ]
}
```

## 5. 计划中但尚未实现

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/ready` | 数据库就绪检查 |
| `POST` | `/api/v1/alerts/{alert_id}/investigations` | 触发 Agent 调查（Phase 2） |

不提供公开注册或 API 用户管理接口。用户创建必须通过本地 `sentinelflow-create-user` 命令。

## 6. 安全说明

- JWT 使用 HS256，默认 30 分钟过期，携带唯一 `jti`；密钥来自 `JWT_SECRET`，没有默认值。
- 授权使用数据库中的当前角色，不信任 token 中的角色声明。
- 密码使用 Argon2id 哈希；不会在任何响应或审计记录中返回。
- 登录按 `(username, source_ip)` 和 `source_ip` 两个维度限流，超限返回 429。
- 登出通过 `revoked_tokens` 立即失效当前 token；每请求校验一次。
- 仍缺少 TLS、MFA、刷新令牌和审计保留策略，默认只应绑定 `127.0.0.1`。
- `/docs`、`/redoc` 和 `/openapi.json` 当前公开，会暴露 API 结构；生产环境应禁用或限制访问。
- **Agent 安全边界**：模型只能调用白名单只读工具；工具在服务端做参数校验、权限检查和作用域限制（只限本告警证据）；模型输出必须通过结构化 Schema 校验，引用的事件 ID 必须属于该告警的真实证据；Agent 不能修改告警状态、不能定稿报告、不能执行任何处置动作。提示词中的防注入说明只是辅助，真正的边界由工具和权限实现。
- Agent 不持久化模型提示词、模型原始响应或 `raw_message`；`investigation_tool_calls` 只保存参数、状态、耗时和结果摘要。

## 7. 前端调用约定

前端位于 `frontend/`，使用 Axios + TanStack Query。

- 开发服务器：`http://127.0.0.1:5173`。
- API base：`VITE_API_BASE_URL`，默认 `/api/v1`。
- Vite 将 `/api` 和 `/health` 代理到 `VITE_PROXY_TARGET`（默认 `http://127.0.0.1:8000`），因此本地开发不修改后端 CORS。
- 除登录外，请求统一携带 `Authorization: Bearer <token>`。
- 401：清除客户端会话并返回登录页。
- 403：显示无权限提示；后端仍是最终授权边界。
- 422：按 `detail[].loc/msg` 展示字段错误，不展示 `input`。
- 409：展示后端返回的转换/定稿冲突说明。
- 429：登录页提示稍后重试。
- 分页：`limit` + `offset`，使用响应的 `total/limit/offset`。
- 报告页的告警标题、状态和历史来自 `GET /alerts/{id}`，**不依赖路由 state**，因此刷新和直接分享链接都能正确渲染。

前端页面与接口对应：

| 页面 | 接口 |
| --- | --- |
| 登录 | `POST /auth/login`、`GET /auth/me` |
| 仪表盘 | `GET /events`、`GET /alerts`、`GET /audit-logs`（admin） |
| 安全事件 | `GET /events`、`POST /events/import`（admin） |
| 告警 | `GET /alerts`、`POST /detections/run`（admin） |
| 调查报告 | `GET /alerts/{alert_id}`、`GET /alerts/{alert_id}/report`、`GET /alerts/{alert_id}/reports` |
| 操作审计 | `GET /audit-logs`（admin） |

前端目前不提供告警状态操作、报告创建和定稿按钮；这些能力已由后端提供，但 UI 尚未接入，因此不会出现“看起来能用但实际无效”的假操作。

生产构建需要同源反向代理，或由后端显式配置受信 CORS；当前后端未配置 CORS。
