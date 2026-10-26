# API 请求与响应实例

> 本文件由 `python scripts/capture_examples.py --markdown docs/portfolio/API_EXAMPLES.md` 生成，
> **不是手写的**。数据来自一次真实运行：全新数据库、真实 `alembic upgrade head`、
> 真实 uvicorn 进程、脚本化模型（桩）。
>
> 抓取时间：`2026-10-26T09:17:55+00:00`　数据库：`sentinelflow_demo`
>
> 唯一的人工处理是显示层截断：长数组只留前 3 项并标注剩余数量，
> JWT 只保留头部。**没有任何数值被改动。**

## 0. 前置

```bash
export BASE=http://127.0.0.1:8000
export TOKEN=<登录返回的 access_token>
```

示例用 `curl` 表示；实际抓取走的是同一个 HTTP 接口。

一共 23 次请求，按业务流程排列如下。


## 1. 探针

### `GET /health` → 200

响应：

```json
{
  "status": "ok",
  "service": "SentinelFlow",
  "version": "0.1.0",
  "environment": "demo"
}
```

### `GET /health/ready` → 200

响应：

```json
{
  "status": "ready",
  "service": "SentinelFlow",
  "version": "0.1.0",
  "database": "ok",
  "detail": null
}
```


## 2. 认证与权限

### `POST /api/v1/auth/login` → 200

请求体（节选）：

```json
{
  "username": "demo.admin",
  "password": "***"
}
```

响应：

```json
{
  "access_token": "***",
  "token_type": "bearer",
  "expires_in": 1800,
  "username": "demo.admin",
  "role": "admin"
}
```

### `GET /api/v1/auth/me` → 200

响应：

```json
{
  "id": "e309b73a-5823-4edc-b706-5a32a8ce4d1f",
  "username": "demo.admin",
  "role": "admin",
  "is_active": true,
  "created_at": "2026-10-26T09:17:51.962754Z",
  "last_login_at": "2026-10-26T09:17:54.512324Z"
}
```

### `GET /api/v1/alerts` → 200

响应：

```json
{
  "items": [],
  "total": 0,
  "limit": 50,
  "offset": 0
}
```

### `PATCH /api/v1/alerts/57c79cfe-980f-49e9-91ca-52ea209ae3d6` → 403

> analyst 只有 alerts:read，改状态被拒

请求体（节选）：

```json
{
  "status": "acknowledged"
}
```

响应：

```json
{
  "detail": "Forbidden"
}
```

### `PATCH /api/v1/alerts/57c79cfe-980f-49e9-91ca-52ea209ae3d6` → 200

请求体（节选）：

```json
{
  "status": "acknowledged",
  "reason": "triaged by demo"
}
```

响应：

```json
{
  "id": "57c79cfe-980f-49e9-91ca-52ea209ae3d6",
  "rule_id": "AUTH-001",
  "rule_version": "1.0.0",
  "title": "Suspicious login activity",
  "description": "6 failed authentication attempts for user 'demo.user' from 198.51.100.77 matched rule AUTH-001 (at least 5 failures in any 5-minute window).",
  "severity": "high",
  "status": "acknowledged",
  "first_seen_at": "2026-05-01T02:00:00Z",
  "last_seen_at": "2026-05-01T02:01:40Z",
  "event_count": 6,
  "created_at": "2026-10-26T09:17:54.623271Z",
  "evidence_count": 6,
  "status_history": [
    {
      "from_status": "open",
      "to_status": "acknowledged",
      "changed_by_username": "demo.admin",
      "reason": "triaged by demo",
      "created_at": "2026-10-26T09:17:54.660402Z"
    }
  ]
}
```

### `POST /api/v1/auth/logout` → 204

无响应体。

### `GET /api/v1/alerts?limit=1` → 401

> 用登出前的同一个 token 再请求

响应：

```json
{
  "detail": "Could not validate credentials"
}
```


## 3. 导入与规则检测

### `POST /api/v1/events/import` → 201

> 七个合成事件：六次失败登录 + 一次成功登录

请求体（节选）：

```json
{
  "events": [
    {
      "event_id": "b8eaeb9d-6daf-4eef-9b6d-b185e3f0fea8",
      "timestamp": "2026-05-01T02:00:00+00:00",
      "event_type": "authentication",
      "action": "login",
      "outcome": "failure",
      "username": "demo.user",
      "source_ip": "198.51.100.77",
      "asset_id": "web-01",
      "source": "demo",
      "raw_message": "Failed password for demo.user from 198.51.100.77 attempt 1"
    },
    {
      "event_id": "8cfaac03-7168-464a-8eeb-d62945b93cb4",
      "timestamp": "2026-05-01T02:00:20+00:00",
      "event_type": "authentication",
      "action": "login",
      "outcome": "failure",
      "username": "demo.user",
      "source_ip": "198.51.100.77",
      "asset_id": "web-01",
      "source": "demo",
      "raw_message": "Failed password for demo.user from 198.51.100.77 attempt 2"
    },
    {
      "event_id": "8dad2965-b8f3-4438-a0e6-77dc47ce1d0b",
      "timestamp": "2026-05-01T02:00:40+00:00",
      "event_type": "authentication",
      "action": "login",
      "outcome": "failure",
      "username": "demo.user",
      "source_ip": "198.51.100.77",
      "asset_id": "web-01",
      "source": "demo",
      "raw_message": "Failed password for demo.user from 198.51.100.77 attempt 3"
    },
    "... 另有 4 项"
  ]
}
```

响应：

```json
{
  "received": 7,
  "imported": 7,
  "skipped": 0,
  "skipped_event_ids": []
}
```

### `POST /api/v1/events/import` → 201

> 同一批数据再导一次：幂等，全部识别为重复

请求体（节选）：

```json
{
  "events": [
    {
      "event_id": "b8eaeb9d-6daf-4eef-9b6d-b185e3f0fea8",
      "timestamp": "2026-05-01T02:00:00+00:00",
      "event_type": "authentication",
      "action": "login",
      "outcome": "failure",
      "username": "demo.user",
      "source_ip": "198.51.100.77",
      "asset_id": "web-01",
      "source": "demo",
      "raw_message": "Failed password for demo.user from 198.51.100.77 attempt 1"
    },
    {
      "event_id": "8cfaac03-7168-464a-8eeb-d62945b93cb4",
      "timestamp": "2026-05-01T02:00:20+00:00",
      "event_type": "authentication",
      "action": "login",
      "outcome": "failure",
      "username": "demo.user",
      "source_ip": "198.51.100.77",
      "asset_id": "web-01",
      "source": "demo",
      "raw_message": "Failed password for demo.user from 198.51.100.77 attempt 2"
    },
    {
      "event_id": "8dad2965-b8f3-4438-a0e6-77dc47ce1d0b",
      "timestamp": "2026-05-01T02:00:40+00:00",
      "event_type": "authentication",
      "action": "login",
      "outcome": "failure",
      "username": "demo.user",
      "source_ip": "198.51.100.77",
      "asset_id": "web-01",
      "source": "demo",
      "raw_message": "Failed password for demo.user from 198.51.100.77 attempt 3"
    },
    "... 另有 4 项"
  ]
}
```

响应：

```json
{
  "received": 7,
  "imported": 0,
  "skipped": 7,
  "skipped_event_ids": [
    "b8eaeb9d-6daf-4eef-9b6d-b185e3f0fea8",
    "8cfaac03-7168-464a-8eeb-d62945b93cb4",
    "8dad2965-b8f3-4438-a0e6-77dc47ce1d0b",
    "... 另有 4 项"
  ]
}
```

### `POST /api/v1/detections/run` → 200

响应：

```json
{
  "rule_id": "AUTH-001",
  "rule_version": "1.0.0",
  "events_scanned": 6,
  "windows_detected": 1,
  "alerts_created": 1,
  "alerts_skipped_existing": 0,
  "created_alert_ids": [
    "57c79cfe-980f-49e9-91ca-52ea209ae3d6"
  ]
}
```

### `POST /api/v1/detections/run` → 200

> 重复运行不产生新告警（dedup key）

响应：

```json
{
  "rule_id": "AUTH-001",
  "rule_version": "1.0.0",
  "events_scanned": 6,
  "windows_detected": 1,
  "alerts_created": 0,
  "alerts_skipped_existing": 1,
  "created_alert_ids": []
}
```


## 4. 告警查询

### `GET /api/v1/alerts?limit=10` → 200

响应：

```json
{
  "items": [
    {
      "id": "57c79cfe-980f-49e9-91ca-52ea209ae3d6",
      "rule_id": "AUTH-001",
      "rule_version": "1.0.0",
      "title": "Suspicious login activity",
      "description": "6 failed authentication attempts for user 'demo.user' from 198.51.100.77 matched rule AUTH-001 (at least 5 failures in any 5-minute window).",
      "severity": "high",
      "status": "open",
      "first_seen_at": "2026-05-01T02:00:00Z",
      "last_seen_at": "2026-05-01T02:01:40Z",
      "event_count": 6,
      "created_at": "2026-10-26T09:17:54.623271Z",
      "evidence_count": 6
    }
  ],
  "total": 1,
  "limit": 10,
  "offset": 0
}
```

### `GET /api/v1/alerts/57c79cfe-980f-49e9-91ca-52ea209ae3d6` → 200

响应：

```json
{
  "id": "57c79cfe-980f-49e9-91ca-52ea209ae3d6",
  "rule_id": "AUTH-001",
  "rule_version": "1.0.0",
  "title": "Suspicious login activity",
  "description": "6 failed authentication attempts for user 'demo.user' from 198.51.100.77 matched rule AUTH-001 (at least 5 failures in any 5-minute window).",
  "severity": "high",
  "status": "open",
  "first_seen_at": "2026-05-01T02:00:00Z",
  "last_seen_at": "2026-05-01T02:01:40Z",
  "event_count": 6,
  "created_at": "2026-10-26T09:17:54.623271Z",
  "evidence_count": 6,
  "status_history": []
}
```

### `GET /api/v1/alerts/57c79cfe-980f-49e9-91ca-52ea209ae3d6/evidence?limit=3` → 200

响应：

```json
{
  "items": [
    {
      "event_id": "b8eaeb9d-6daf-4eef-9b6d-b185e3f0fea8",
      "timestamp": "2026-05-01T02:00:00Z",
      "event_type": "authentication",
      "username": "demo.user",
      "source_ip": "198.51.100.77",
      "asset_id": "web-01",
      "action": "login",
      "outcome": "failure",
      "source": "demo",
      "raw_message": null
    },
    {
      "event_id": "8cfaac03-7168-464a-8eeb-d62945b93cb4",
      "timestamp": "2026-05-01T02:00:20Z",
      "event_type": "authentication",
      "username": "demo.user",
      "source_ip": "198.51.100.77",
      "asset_id": "web-01",
      "action": "login",
      "outcome": "failure",
      "source": "demo",
      "raw_message": null
    },
    {
      "event_id": "8dad2965-b8f3-4438-a0e6-77dc47ce1d0b",
      "timestamp": "2026-05-01T02:00:40Z",
      "event_type": "authentication",
      "username": "demo.user",
      "source_ip": "198.51.100.77",
      "asset_id": "web-01",
      "action": "login",
      "outcome": "failure",
      "source": "demo",
      "raw_message": null
    }
  ],
  "total": 6,
  "limit": 3,
  "offset": 0
}
```


## 5. Agent 调查

### `POST /api/v1/alerts/57c79cfe-980f-49e9-91ca-52ea209ae3d6/investigations` → 202

响应：

```json
{
  "id": "01800f9a-8bc3-4b53-9890-eed4ba6c447a",
  "alert_id": "57c79cfe-980f-49e9-91ca-52ea209ae3d6",
  "status": "pending",
  "model_provider": "stub",
  "model_name": "stub-model",
  "prompt_version": "1.0.0",
  "rounds_used": 0,
  "tool_calls_used": 0,
  "error": null,
  "error_code": null,
  "attempt_count": 0,
  "max_attempts": 2,
  "request_id": "a3806c617d5e478d89ea6ac411180a41",
  "duration_ms": null,
  "report_id": null,
  "created_by_username": "demo.admin",
  "created_at": "2026-10-26T09:17:54.675403Z",
  "started_at": null,
  "completed_at": null,
  "rounds": [],
  "tool_calls": []
}
```

### `GET /api/v1/investigations/01800f9a-8bc3-4b53-9890-eed4ba6c447a` → 200

响应：

```json
{
  "id": "01800f9a-8bc3-4b53-9890-eed4ba6c447a",
  "alert_id": "57c79cfe-980f-49e9-91ca-52ea209ae3d6",
  "status": "succeeded",
  "model_provider": "stub",
  "model_name": "stub-model",
  "prompt_version": "1.0.0",
  "rounds_used": 2,
  "tool_calls_used": 1,
  "error": null,
  "error_code": null,
  "attempt_count": 1,
  "max_attempts": 2,
  "request_id": "a3806c617d5e478d89ea6ac411180a41",
  "duration_ms": 0,
  "report_id": "a78862b7-bd7e-410f-8997-646d644e6dd4",
  "created_by_username": "demo.admin",
  "created_at": "2026-10-26T09:17:54.675403Z",
  "started_at": "2026-10-26T09:17:55.320641Z",
  "completed_at": "2026-10-26T09:17:55.371335Z",
  "rounds": [
    {
      "round_index": 1,
      "attempt_index": 1,
      "latency_ms": 0,
      "outcome": "tool_calls",
      "tool_call_count": 1,
      "error": null,
      "created_at": "2026-10-26T09:17:55.359520Z"
    },
    {
      "round_index": 2,
      "attempt_index": 1,
      "latency_ms": 0,
      "outcome": "findings",
      "tool_call_count": 0,
      "error": null,
      "created_at": "2026-10-26T09:17:55.359520Z"
    }
  ],
  "tool_calls": [
    {
      "sequence": 1,
      "attempt_index": 1,
      "tool_name": "get_related_events",
      "arguments": {
        "limit": 20
      },
      "status": "ok",
      "result_summary": {
        "returned": 6,
        "total": 6,
        "offset": 0,
        "event_ids": [
          "b8eaeb9d-6daf-4eef-9b6d-b185e3f0fea8",
          "8cfaac03-7168-464a-8eeb-d62945b93cb4",
          "8dad2965-b8f3-4438-a0e6-77dc47ce1d0b",
          "... 另有 3 项"
        ]
      },
      "error": null,
      "duration_ms": 0,
      "created_at": "2026-10-26T09:17:55.362590Z"
    }
  ]
}
```


## 6. 报告：版本与定稿

### `GET /api/v1/reports/a78862b7-bd7e-410f-8997-646d644e6dd4` → 200

响应：

```json
{
  "id": "a78862b7-bd7e-410f-8997-646d644e6dd4",
  "alert_id": "57c79cfe-980f-49e9-91ca-52ea209ae3d6",
  "version": 1,
  "status": "draft",
  "generator": "agent",
  "generator_version": "1.0.0",
  "evidence_count": 6,
  "evidence_truncated": true,
  "created_by_username": "demo.admin",
  "created_at": "2026-10-26T09:17:55.364606Z",
  "finalized_at": null,
  "finalized_by_username": null,
  "content": {
    "alert_id": "57c79cfe-980f-49e9-91ca-52ea209ae3d6",
    "summary": "同一来源在 5 分钟内产生 6 次失败登录，随后一次成功登录，符合自动化撞库特征。",
    "risk_level": "high",
    "evidence": [
      {
        "event_id": "b8eaeb9d-6daf-4eef-9b6d-b185e3f0fea8",
        "timestamp": "2026-05-01T02:00:00Z",
        "event_type": "authentication",
        "username": "demo.user",
        "source_ip": "198.51.100.77",
        "asset_id": "web-01",
        "action": "login",
        "outcome": "failure",
        "source": "demo",
        "raw_message": "Failed password for demo.user from 198.51.100.77 attempt 1"
      },
      {
        "event_id": "8cfaac03-7168-464a-8eeb-d62945b93cb4",
        "timestamp": "2026-05-01T02:00:20Z",
        "event_type": "authentication",
        "username": "demo.user",
        "source_ip": "198.51.100.77",
        "asset_id": "web-01",
        "action": "login",
        "outcome": "failure",
        "source": "demo",
        "raw_message": "Failed password for demo.user from 198.51.100.77 attempt 2"
      },
      {
        "event_id": "8dad2965-b8f3-4438-a0e6-77dc47ce1d0b",
        "timestamp": "2026-05-01T02:00:40Z",
        "event_type": "authentication",
        "username": "demo.user",
        "source_ip": "198.51.100.77",
        "asset_id": "web-01",
        "action": "login",
        "outcome": "failure",
        "source": "demo",
        "raw_message": "Failed password for demo.user from 198.51.100.77 attempt 3"
      }
    ],
    "timeline": [
      {
        "timestamp": "2026-05-01T02:00:00Z",
        "event_id": "b8eaeb9d-6daf-4eef-9b6d-b185e3f0fea8",
        "description": "login failure for user 'demo.user' from 198.51.100.77"
      },
      {
        "timestamp": "2026-05-01T02:00:20Z",
        "event_id": "8cfaac03-7168-464a-8eeb-d62945b93cb4",
        "description": "login failure for user 'demo.user' from 198.51.100.77"
      },
      {
        "timestamp": "2026-05-01T02:00:40Z",
        "event_id": "8dad2965-b8f3-4438-a0e6-77dc47ce1d0b",
        "description": "login failure for user 'demo.user' from 198.51.100.77"
      }
    ],
    "reasoning": "6 次失败集中在同一账号与同一来源地址，间隔约 20 秒，非人工输入节奏；随后的成功登录需要确认是否为账号主人操作。",
    "recommended_actions": [
      "联系账号主人确认该次登录",
      "如非本人操作则重置凭据",
      "检索该来源地址是否命中其他账号"
    ],
    "limitations": [
      "仅覆盖认证日志，无法判断登录后的行为",
      "This report was produced by an AI agent under human review; it is a draft until finalized.",
      "The agent had read-only access to imported event data and a local runbook corpus only.",
      "Event log text is untrusted input. It was analysed as data and never executed as instructions.",
      "Evidence citations were validated against the database, but the analytical conclusions were not."
    ],
    "evidence_total": 6,
    "evidence_truncated": true
  }
}
```

### `GET /api/v1/alerts/57c79cfe-980f-49e9-91ca-52ea209ae3d6/reports` → 200

响应：

```json
{
  "items": [
    {
      "id": "a78862b7-bd7e-410f-8997-646d644e6dd4",
      "alert_id": "57c79cfe-980f-49e9-91ca-52ea209ae3d6",
      "version": 1,
      "status": "draft",
      "generator": "agent",
      "generator_version": "1.0.0",
      "evidence_count": 6,
      "evidence_truncated": true,
      "created_by_username": "demo.admin",
      "created_at": "2026-10-26T09:17:55.364606Z",
      "finalized_at": null,
      "finalized_by_username": null,
      "content": {
        "alert_id": "57c79cfe-980f-49e9-91ca-52ea209ae3d6",
        "summary": "同一来源在 5 分钟内产生 6 次失败登录，随后一次成功登录，符合自动化撞库特征。",
        "risk_level": "high",
        "evidence": [
          {
            "event_id": "b8eaeb9d-6daf-4eef-9b6d-b185e3f0fea8",
            "timestamp": "2026-05-01T02:00:00Z",
            "event_type": "authentication",
            "username": "demo.user",
            "source_ip": "198.51.100.77",
            "asset_id": "web-01",
            "action": "login",
            "outcome": "failure",
            "source": "demo",
            "raw_message": "Failed password for demo.user from 198.51.100.77 attempt 1"
          },
          {
            "event_id": "8cfaac03-7168-464a-8eeb-d62945b93cb4",
            "timestamp": "2026-05-01T02:00:20Z",
            "event_type": "authentication",
            "username": "demo.user",
            "source_ip": "198.51.100.77",
            "asset_id": "web-01",
            "action": "login",
            "outcome": "failure",
            "source": "demo",
            "raw_message": "Failed password for demo.user from 198.51.100.77 attempt 2"
          },
          {
            "event_id": "8dad2965-b8f3-4438-a0e6-77dc47ce1d0b",
            "timestamp": "2026-05-01T02:00:40Z",
            "event_type": "authentication",
            "username": "demo.user",
            "source_ip": "198.51.100.77",
            "asset_id": "web-01",
            "action": "login",
            "outcome": "failure",
            "source": "demo",
            "raw_message": "Failed password for demo.user from 198.51.100.77 attempt 3"
          }
        ],
        "timeline": [
          {
            "timestamp": "2026-05-01T02:00:00Z",
            "event_id": "b8eaeb9d-6daf-4eef-9b6d-b185e3f0fea8",
            "description": "login failure for user 'demo.user' from 198.51.100.77"
          },
          {
            "timestamp": "2026-05-01T02:00:20Z",
            "event_id": "8cfaac03-7168-464a-8eeb-d62945b93cb4",
            "description": "login failure for user 'demo.user' from 198.51.100.77"
          },
          {
            "timestamp": "2026-05-01T02:00:40Z",
            "event_id": "8dad2965-b8f3-4438-a0e6-77dc47ce1d0b",
            "description": "login failure for user 'demo.user' from 198.51.100.77"
          }
        ],
        "reasoning": "6 次失败集中在同一账号与同一来源地址，间隔约 20 秒，非人工输入节奏；随后的成功登录需要确认是否为账号主人操作。",
        "recommended_actions": [
          "联系账号主人确认该次登录",
          "如非本人操作则重置凭据",
          "检索该来源地址是否命中其他账号"
        ],
        "limitations": [
          "仅覆盖认证日志，无法判断登录后的行为",
          "This report was produced by an AI agent under human review; it is a draft until finalized.",
          "The agent had read-only access to imported event data and a local runbook corpus only.",
          "... 另有 2 项"
        ],
        "evidence_total": 6,
        "evidence_truncated": true
      }
    }
  ],
  "total": 1
}
```

### `POST /api/v1/alerts/57c79cfe-980f-49e9-91ca-52ea209ae3d6/reports` → 201

请求体（节选）：

```json
{
  "note": "second version after triage"
}
```

响应：

```json
{
  "id": "d3b33773-785f-4e71-8af6-9a4f75ea1d93",
  "alert_id": "57c79cfe-980f-49e9-91ca-52ea209ae3d6",
  "version": 2,
  "status": "draft",
  "generator": "deterministic",
  "generator_version": "1.0.0",
  "evidence_count": 6,
  "evidence_truncated": false,
  "created_by_username": "demo.admin",
  "created_at": "2026-10-26T09:17:55.507179Z",
  "finalized_at": null,
  "finalized_by_username": null,
  "content": {
    "alert_id": "57c79cfe-980f-49e9-91ca-52ea209ae3d6",
    "summary": "Rule AUTH-001 identified 6 failed authentication attempts for user 'demo.user' from 198.51.100.77 between 2026-05-01T02:00:00+00:00 and 2026-05-01T02:01:40+00:00.",
    "risk_level": "high",
    "evidence": [
      {
        "event_id": "b8eaeb9d-6daf-4eef-9b6d-b185e3f0fea8",
        "timestamp": "2026-05-01T02:00:00Z",
        "event_type": "authentication",
        "username": "demo.user",
        "source_ip": "198.51.100.77",
        "asset_id": "web-01",
        "action": "login",
        "outcome": "failure",
        "source": "demo",
        "raw_message": "Failed password for demo.user from 198.51.100.77 attempt 1"
      },
      {
        "event_id": "8cfaac03-7168-464a-8eeb-d62945b93cb4",
        "timestamp": "2026-05-01T02:00:20Z",
        "event_type": "authentication",
        "username": "demo.user",
        "source_ip": "198.51.100.77",
        "asset_id": "web-01",
        "action": "login",
        "outcome": "failure",
        "source": "demo",
        "raw_message": "Failed password for demo.user from 198.51.100.77 attempt 2"
      },
      {
        "event_id": "8dad2965-b8f3-4438-a0e6-77dc47ce1d0b",
        "timestamp": "2026-05-01T02:00:40Z",
        "event_type": "authentication",
        "username": "demo.user",
        "source_ip": "198.51.100.77",
        "asset_id": "web-01",
        "action": "login",
        "outcome": "failure",
        "source": "demo",
        "raw_message": "Failed password for demo.user from 198.51.100.77 attempt 3"
      },
      "... 另有 3 项"
    ],
    "timeline": [
      {
        "timestamp": "2026-05-01T02:00:00Z",
        "event_id": "b8eaeb9d-6daf-4eef-9b6d-b185e3f0fea8",
        "description": "login failure for user 'demo.user' from 198.51.100.77 on asset 'web-01'"
      },
      {
        "timestamp": "2026-05-01T02:00:20Z",
        "event_id": "8cfaac03-7168-464a-8eeb-d62945b93cb4",
        "description": "login failure for user 'demo.user' from 198.51.100.77 on asset 'web-01'"
      },
      {
        "timestamp": "2026-05-01T02:00:40Z",
        "event_id": "8dad2965-b8f3-4438-a0e6-77dc47ce1d0b",
        "description": "login failure for user 'demo.user' from 198.51.100.77 on asset 'web-01'"
      },
      "... 另有 3 项"
    ],
    "reasoning": "Rule AUTH-001 (version 1.0.0) fires when the same username and source IP produce at least 5 failed authentication/login events within a 5-minute window. This alert links 6 evidence events from the database. The rule sorts events by timestamp, includes both window boundaries, and groups only events with the same username and source IP. The deduplication key is derived from the rule and the first ev…",
    "recommended_actions": [
      "Verify whether the source IP is expected for this user (for example VPN, office, or known travel).",
      "Review authentication, VPN, and application logs for the user and affected assets around the alert window.",
      "Check whether any successful login followed the failures and whether the account owner recognizes the activity.",
      "... 另有 2 项"
    ],
    "limitations": [
      "This rule detects a pattern of failed authentication attempts; it does not prove that a system was compromised.",
      "The analysis covers only imported event data. Endpoint, network, and identity-provider telemetry are not correlated.",
      "Event timestamps depend on source clocks and may be inaccurate or skewed.",
      "... 另有 3 项"
    ],
    "evidence_total": 6,
    "evidence_truncated": false
  }
}
```

### `POST /api/v1/reports/d3b33773-785f-4e71-8af6-9a4f75ea1d93/finalize` → 200

请求体（节选）：

```json
{
  "note": "accepted by demo admin"
}
```

响应：

```json
{
  "id": "d3b33773-785f-4e71-8af6-9a4f75ea1d93",
  "alert_id": "57c79cfe-980f-49e9-91ca-52ea209ae3d6",
  "version": 2,
  "status": "finalized",
  "generator": "deterministic",
  "generator_version": "1.0.0",
  "evidence_count": 6,
  "evidence_truncated": false,
  "created_by_username": "demo.admin",
  "created_at": "2026-10-26T09:17:55.507179Z",
  "finalized_at": "2026-10-26T09:17:55.516753Z",
  "finalized_by_username": "demo.admin",
  "content": {
    "alert_id": "57c79cfe-980f-49e9-91ca-52ea209ae3d6",
    "summary": "Rule AUTH-001 identified 6 failed authentication attempts for user 'demo.user' from 198.51.100.77 between 2026-05-01T02:00:00+00:00 and 2026-05-01T02:01:40+00:00.",
    "risk_level": "high",
    "evidence": [
      {
        "event_id": "b8eaeb9d-6daf-4eef-9b6d-b185e3f0fea8",
        "timestamp": "2026-05-01T02:00:00Z",
        "event_type": "authentication",
        "username": "demo.user",
        "source_ip": "198.51.100.77",
        "asset_id": "web-01",
        "action": "login",
        "outcome": "failure",
        "source": "demo",
        "raw_message": "Failed password for demo.user from 198.51.100.77 attempt 1"
      },
      {
        "event_id": "8cfaac03-7168-464a-8eeb-d62945b93cb4",
        "timestamp": "2026-05-01T02:00:20Z",
        "event_type": "authentication",
        "username": "demo.user",
        "source_ip": "198.51.100.77",
        "asset_id": "web-01",
        "action": "login",
        "outcome": "failure",
        "source": "demo",
        "raw_message": "Failed password for demo.user from 198.51.100.77 attempt 2"
      },
      {
        "event_id": "8dad2965-b8f3-4438-a0e6-77dc47ce1d0b",
        "timestamp": "2026-05-01T02:00:40Z",
        "event_type": "authentication",
        "username": "demo.user",
        "source_ip": "198.51.100.77",
        "asset_id": "web-01",
        "action": "login",
        "outcome": "failure",
        "source": "demo",
        "raw_message": "Failed password for demo.user from 198.51.100.77 attempt 3"
      },
      "... 另有 3 项"
    ],
    "timeline": [
      {
        "timestamp": "2026-05-01T02:00:00Z",
        "event_id": "b8eaeb9d-6daf-4eef-9b6d-b185e3f0fea8",
        "description": "login failure for user 'demo.user' from 198.51.100.77 on asset 'web-01'"
      },
      {
        "timestamp": "2026-05-01T02:00:20Z",
        "event_id": "8cfaac03-7168-464a-8eeb-d62945b93cb4",
        "description": "login failure for user 'demo.user' from 198.51.100.77 on asset 'web-01'"
      },
      {
        "timestamp": "2026-05-01T02:00:40Z",
        "event_id": "8dad2965-b8f3-4438-a0e6-77dc47ce1d0b",
        "description": "login failure for user 'demo.user' from 198.51.100.77 on asset 'web-01'"
      },
      "... 另有 3 项"
    ],
    "reasoning": "Rule AUTH-001 (version 1.0.0) fires when the same username and source IP produce at least 5 failed authentication/login events within a 5-minute window. This alert links 6 evidence events from the database. The rule sorts events by timestamp, includes both window boundaries, and groups only events with the same username and source IP. The deduplication key is derived from the rule and the first ev…",
    "recommended_actions": [
      "Verify whether the source IP is expected for this user (for example VPN, office, or known travel).",
      "Review authentication, VPN, and application logs for the user and affected assets around the alert window.",
      "Check whether any successful login followed the failures and whether the account owner recognizes the activity.",
      "... 另有 2 项"
    ],
    "limitations": [
      "This rule detects a pattern of failed authentication attempts; it does not prove that a system was compromised.",
      "The analysis covers only imported event data. Endpoint, network, and identity-provider telemetry are not correlated.",
      "Event timestamps depend on source clocks and may be inaccurate or skewed.",
      "... 另有 3 项"
    ],
    "evidence_total": 6,
    "evidence_truncated": false
  }
}
```


## 7. 审计

### `GET /api/v1/audit-logs?limit=8` → 200

响应：

```json
{
  "items": [
    {
      "id": "774e0f7b-74e5-408a-83fc-61625eba929a",
      "actor_user_id": "e309b73a-5823-4edc-b706-5a32a8ce4d1f",
      "actor_username": "demo.admin",
      "action": "reports.finalize",
      "resource_type": "report",
      "resource_id": "d3b33773-785f-4e71-8af6-9a4f75ea1d93",
      "outcome": "success",
      "source_ip": "127.0.0.1",
      "request_id": "d233b4f6315c4c068491b45eae9247fc",
      "details": {
        "alert_id": "57c79cfe-980f-49e9-91ca-52ea209ae3d6",
        "version": 2
      },
      "created_at": "2026-10-26T09:17:55.517754Z"
    },
    {
      "id": "83062198-59fb-49a3-ba9e-b2be5f63fb75",
      "actor_user_id": "e309b73a-5823-4edc-b706-5a32a8ce4d1f",
      "actor_username": "demo.admin",
      "action": "reports.create",
      "resource_type": "alert",
      "resource_id": "57c79cfe-980f-49e9-91ca-52ea209ae3d6",
      "outcome": "success",
      "source_ip": "127.0.0.1",
      "request_id": "fe8941d960cf4f49801793bffea77095",
      "details": {
        "report_id": "d3b33773-785f-4e71-8af6-9a4f75ea1d93",
        "version": 2,
        "generator": "deterministic",
        "evidence_total": 6,
        "evidence_truncated": false,
        "note_provided": true
      },
      "created_at": "2026-10-26T09:17:55.510222Z"
    },
    {
      "id": "3a40c375-f955-4041-bfaf-e306acb77312",
      "actor_user_id": "e309b73a-5823-4edc-b706-5a32a8ce4d1f",
      "actor_username": "demo.admin",
      "action": "reports.read",
      "resource_type": "report",
      "resource_id": "a78862b7-bd7e-410f-8997-646d644e6dd4",
      "outcome": "success",
      "source_ip": "127.0.0.1",
      "request_id": "18710e1d5d8a4e9db090585bde794b9e",
      "details": {
        "version": 1,
        "status": "draft"
      },
      "created_at": "2026-10-26T09:17:55.493596Z"
    },
    "... 另有 5 项"
  ],
  "total": 16,
  "limit": 8,
  "offset": 0
}
```


## 8. 这份记录证明了什么

| 结论 | 证据 |
| --- | --- |
| 重复导入幂等 | `import_duplicate` 返回 `imported=0, skipped=7`，不是 409 也不是重复插入 |
| 重复检测不重复告警 | 第二次 `run_detection` 返回 `alerts_created=0`，`alerts_skipped_existing=1` |
| 权限是真在服务端拦的 | analyst 的 `PATCH` 返回 403，同一个请求换 admin 就成功 |
| 调查是异步的 | `POST` 返回 202 + `status=pending`，最终态要靠轮询拿 |
| 报告引用的是真实事件 | `content.evidence` 里的 `event_id` 都能在 `/evidence` 里找到 |
| 定稿不可逆 | 版本 2 定稿后 `status=finalized`，带 `finalized_at` 与操作人 |
| 登出即失效 | 同一个 token 再请求返回 401 |
| 审计可追溯 | `audit_logs` 里每条都有 `action`、资源、`request_id` 和操作人 |

告警 id：`57c79cfe-980f-49e9-91ca-52ea209ae3d6`
调查 id：`01800f9a-8bc3-4b53-9890-eed4ba6c447a`
