# 架构图

四张图：系统怎么组装、一次调查怎么走、数据怎么连、状态怎么流转。

图用 Mermaid 写，GitHub 直接渲染；本机可用 `npx @mermaid-js/mermaid-cli` 导出 PNG。

---

## 1. 系统组成

```mermaid
flowchart TB
    subgraph browser["浏览器"]
        ui["React 19 控制台<br/>TanStack Query · 相对路径 /api/v1"]
    end

    subgraph app["Python 进程（单 uvicorn worker）"]
        api["FastAPI<br/>20 个操作 · 17 个要鉴权"]
        auth["认证与授权<br/>JWT(jti) · Argon2id · RBAC"]
        svc["服务层<br/>events / detection / alerts<br/>reports / investigations"]
        agent["Agent 调查员<br/>4 个只读工具 · 5 轮 / 8 次预算"]
        worker["队列 worker<br/>租约 · 重试上限 · 卡死回收"]
        audit["审计<br/>append-only"]
    end

    subgraph ext["外部依赖"]
        pg[("PostgreSQL 16<br/>12 张表")]
        llm["模型 Provider<br/>OpenAI 兼容接口"]
    end

    cli["CLI<br/>import / create-user / doctor"]

    ui -->|"HTTPS / 同源"| api
    api --> auth
    api --> svc
    api --> audit
    svc --> pg
    audit --> pg
    worker --> pg
    worker --> agent
    agent -->|"只读查询，按告警作用域"| pg
    agent -->|"tool_calls / findings"| llm
    cli --> pg
    cli -->|"逐行导入，坏行跳过"| pg

    classDef store fill:#1f2937,stroke:#374151,color:#f9fafb
    classDef external fill:#312e81,stroke:#4338ca,color:#e0e7ff
    class pg store
    class llm external
```

三个刻意的边界：

- **API 进程和 worker 在同一个进程里，但不共享内存状态。** 队列是 `investigations` 表，
  租约是 `lease_expires_at` 列。进程崩了，租约到期后任务被别的 worker 领走——
  这就是为什么不需要 Redis 或 Celery。
- **Agent 不直接连数据库。** 它只拿到 `ToolContext`（session + 本告警 + 证据 id 集合），
  所有查询都经过工具层，而工具层只暴露 4 个函数。
- **前端只调相对路径。** 部署时不需要 CORS，也不需要把 API 地址编进构建产物。

---

## 2. 一次调查的时序

这是整个项目最值得看的一张图：标出了三个会**主动失败**的位置。

```mermaid
sequenceDiagram
    autonumber
    participant U as 分析师（前端）
    participant A as API
    participant DB as PostgreSQL
    participant W as 队列 worker
    participant M as 模型 Provider
    participant T as 工具层

    U->>A: POST /alerts/{id}/investigations
    A->>DB: SELECT alert FOR UPDATE
    Note right of A: 行锁：同一告警同时只能有一个在飞的调查
    A->>DB: INSERT investigation (status=pending)
    A-->>U: 202 Accepted + id
    Note over U: 不阻塞，前端开始轮询

    W->>DB: UPDATE ... SET lease_expires_at<br/>WHERE status=pending
    Note right of W: 抢占式领取，租约到期可被回收
    W->>DB: status=running

    W->>M: messages + 4 个工具定义
    M-->>W: tool_call: get_related_events(limit=20)
    W->>T: 校验工具名 → 校验角色权限 → 校验参数（extra=forbid）
    T->>DB: 查本告警的证据（作用域固定）
    DB-->>T: 6 条事件
    T-->>W: 截断后的结果（raw_message ≤ 500 字符）
    W->>M: 工具结果回灌

    M-->>W: findings{cited_event_ids: [3 个 id]}
    W->>W: validate_citations()
    alt 有 id 不在本告警证据集
        W->>DB: status=failed, error_code=citation_invalid
        Note right of W: 幻觉的代价是任务失败，<br/>不是一份错误报告被签发
    else 全部命中
        W->>DB: INSERT report v1 (draft) + rounds + tool_calls
        W->>DB: status=succeeded, completed_at
    end

    U->>A: GET /investigations/{id}（轮询）
    A->>DB: 读任务 + 轮次 + 工具调用
    A-->>U: status / rounds / tool_calls / report_id
    U->>A: GET /reports/{report_id}
    A-->>U: 报告（含引用事件全文）

    Note over W,M: 另两种失败：模型超时 → error_code=model_timeout<br/>预算耗尽 → error_code=budget_exhausted
```

失败路径不是补上去的，是设计的一部分：

| 情况 | 结果 | 代码位置 |
| --- | --- | --- |
| 模型超时 | `error_code=model_timeout`，任务终止 | `ai/agent.py` 的模型调用异常分支 |
| 引用不存在的 id | `error_code=citation_invalid`，整次失败 | `validate_citations()` |
| 轮次/调用/运行时长耗尽 | `error_code=budget_exhausted` | 三个预算检查 |
| 工具超时 | 该次调用记为失败，模型可以换策略 | 线程池 + 5 秒超时 |
| worker 崩溃 | 租约到期后重新领取，超过 `max_attempts` 判 failed | `services/investigation_worker.py` |
| 工具名不在白名单 | 模型调用前就拒绝，不进入执行 | `TOOL_SPECS` 查找 |

---

## 3. 数据模型（12 张表）

```mermaid
erDiagram
    users ||--o{ audit_logs : "actor"
    users ||--o{ investigations : "created_by"
    users ||--o{ investigation_reports : "finalized_by"

    security_events ||--o{ alert_events : ""
    alerts ||--o{ alert_events : "证据关联"
    alerts ||--o{ alert_status_history : "状态流转"
    alerts ||--o{ investigations : ""
    alerts ||--o{ investigation_reports : "版本序列"

    investigations ||--o{ investigation_rounds : "每轮"
    investigations ||--o{ investigation_tool_calls : "每次调用"
    investigations ||--o| investigation_reports : "产出"

    users {
        uuid id PK
        string username UK
        string password_hash "Argon2id"
        string role "admin|analyst"
        bool is_active
    }
    security_events {
        uuid event_id PK
        datetime occurred_at "索引"
        string event_type
        string action
        string outcome
        string username
        string source_ip
        string raw_message
    }
    alerts {
        uuid id PK
        string rule_id
        string rule_version
        string dedup_key UK "重复检测靠它"
        string status
        int event_count
    }
    alert_events {
        uuid alert_id FK
        uuid event_id FK
    }
    investigations {
        uuid id PK
        string status
        string error_code
        int rounds_used
        int tool_calls_used
        int attempt_count
        datetime lease_expires_at "队列租约"
    }
    investigation_reports {
        uuid id PK
        int version "alert 内唯一"
        string status "draft|finalized|superseded"
        string generator "deterministic|agent"
        json content
        json input_snapshot "定稿后不再变"
    }
    audit_logs {
        uuid id PK
        string action
        string resource_type
        string result
        string request_id
    }
```

三个约束值得单独说：

- `alerts.dedup_key` 唯一。**重复运行检测的幂等性不是靠应用层判断，是靠数据库拒绝。**
- `investigation_reports (alert_id, version)` 唯一。并发建版本时后者会撞约束，
  而不是悄悄产生两个 v2。
- `audit_logs` 没有任何 UPDATE/DELETE 路径，也没有对应的 API。

---

## 4. 两个状态机

告警状态（`services/alerts.py`）：

```mermaid
stateDiagram-v2
    [*] --> open: 规则命中
    open --> acknowledged
    open --> investigating
    open --> closed
    acknowledged --> investigating
    acknowledged --> closed
    investigating --> closed
    closed --> open: 需要填写理由
```

报告版本（`services/investigation_reports.py`）：

```mermaid
stateDiagram-v2
    [*] --> draft: 调查产出 / 人工新建
    draft --> finalized: 管理员定稿
    finalized --> superseded: 出现更高版本
    note right of finalized
        定稿后内容不可改
        修订必须建新版本
    end note
```

`closed → open` 是唯一要求写理由的转换（`REASON_REQUIRED_TRANSITIONS`）。
理由不是自由文本摆设：它进 `alert_status_history`，也进审计。

---

## 5. 部署形态

没有容器。三个进程，一条命令各自启动：

```text
终端 1   PostgreSQL 16                     127.0.0.1:5432
终端 2   uvicorn sentinelflow.main:app     127.0.0.1:8000
终端 3   npm run dev                       127.0.0.1:5173
```

生产形态把终端 3 换成 `npm run build` 的静态产物，由任意反向代理托管，
`/api` 反代到 8000。**没有 TLS、没有多副本、没有反向代理配置**——
这三件事在 `docs/V1_ACCEPTANCE.md` §7 里列为"未验证"，
不是漏了，是刻意不写没跑过的东西（见 `docs/DECISIONS.md` D-050）。
