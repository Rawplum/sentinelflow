# 演示流程与演示脚本

一条**不需要模型密钥**就能跑完的链路，和一条需要模型的对照链路。

脚本是 `scripts/demo.py`。它自己生成合成数据、自己调 API、自己打印旁白，
所以演示时不用手敲 12 条 curl，也不会因为记错一个参数而卡住。

---

## 1. 准备（一次性，约 5 分钟）

```bash
# 1) 数据库
createdb sentinelflow

# 2) 依赖
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"

# 3) 配置
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # 填进 JWT_SECRET
# 再把 POSTGRES_PASSWORD 和 DATABASE_URL 里的 CHANGE_ME 换成同一个密码

# 4) 建表 + 建账号
sentinelflow-doctor          # 会告诉你还差什么，每项都给出可复制的命令
alembic upgrade head
sentinelflow-create-user --username demo.admin --role admin   # 密码交互输入

# 5) 起服务
uvicorn sentinelflow.main:app --host 127.0.0.1 --port 8000
```

控制台另开一个终端：`cd frontend && npm install && npm run dev`，然后打开 <http://localhost:5173>。

> **不想装 PostgreSQL**：`scripts/demo.py` 只跟 HTTP 打交道，任何能跑起 API 的数据库都行。
> 但项目只在 PostgreSQL 上验证过并发行为，SQLite 会静默忽略 `FOR UPDATE`。

---

## 2. 演示脚本

```bash
export DEMO_PASSWORD='你刚才输入的密码'      # 不放在命令行里，避免进 shell 历史
python scripts/demo.py --username demo.admin
```

六步，每步一行旁白，大约 15 秒跑完：

| 步骤 | 演示什么 | 关键点 |
| --- | --- | --- |
| 1 导入 | 合成日志进库 | 7 条：6 次失败 + 1 次成功 |
| 2 再导一次 | **幂等** | `imported=0, skipped=7`，不是 409 也不是重复插入 |
| 3 检测 | 规则命中 | `AUTH-001`，5 分钟 / ≥5 次失败 |
| 3b 再跑一次 | **不重复告警** | `alerts_created=0`，靠 `dedup_key` 唯一约束 |
| 4 看告警 | 证据可追溯 | 6 条证据，每条能回到原始日志 |
| 5 确定性报告 | **不需要模型** | 模板化，永远给结论 |
| 6 Agent 调查 | 需要模型 | 异步 202 → 轮询 → 带引用的报告 |

### 真实运行结果

下面这段是**实际输出**，在一台干净数据库上跑出来的（`sentinelflow_demo`，2026-10-26）：

```text
SentinelFlow 演示
  服务  http://127.0.0.1:8001
  账号  demo.admin
      就绪：database=ok
      登录成功：role=admin

[1/6] 导入合成日志
      7 条：同一账号从同一来源，5 分钟内 6 次失败，随后 1 次成功
      HTTP 201  imported=7  skipped=0

[2/6] 再导一次（幂等性）
      HTTP 201  imported=0  skipped=7
      不是报错，是识别为重复：事件主键已经存在，整批被跳过

[3/6] 运行规则检测
      规则 AUTH-001：同一账号 + 同一来源，任意 5 分钟窗口内 ≥5 次失败
      扫描 6 条事件 → 1 个窗口 → 新建 1 个告警，跳过 0 个已存在
      再跑一次：新建 0，跳过 1（dedup_key 唯一约束兜底）

[4/6] 查看告警与证据
      告警 1914621e…  severity=high  status=open
      标题：Suspicious login activity
      证据：6 条（点击任一条都能回到原始日志）
        2026-05-01T02:00:00Z  login/failure  demo.user@198.51.100.77
        2026-05-01T02:00:20Z  login/failure  demo.user@198.51.100.77
        2026-05-01T02:00:40Z  login/failure  demo.user@198.51.100.77

[5/6] 生成确定性报告（不需要模型）
      结论：Rule AUTH-001 identified 6 failed authentication attempts for user 'demo.user' f
      风险：high　引用事件：6 条
      这份报告是模板化的：它永远给结论，永远按 severity 分级——
      这也正是它的局限，下面用 Agent 对照。

[6/6] Agent 调查（需要服务端配置 LLM_*）
      HTTP 202  status=pending（异步，立即返回）
      最终：succeeded  轮次=2  工具调用=1  耗时=61ms
        调用 get_related_events({'limit': 20}) → ok
      报告版本 v1　状态=draft
      结论：同一来源在 5 分钟内产生 6 次失败登录，随后一次成功登录，符合自动化撞库特征。
      引用：3 条 / 全量 6 条
      局限（模型自述）：仅覆盖认证日志，无法判断登录后的行为
      每个引用 id 都经过数据库校验，编造的 id 会让整次调查失败。

演示结束。所有数据都是合成数据，不含真实日志或凭据。
```

> 第 6 步的 `耗时=61ms` 是**桩模型**的延迟，不是真实模型的。真实模型 11 秒左右，
> 见 `docs/BENCHMARK.md`。演示时不这么说清楚，就是在暗示一个不存在的性能。

### 合成数据是什么

`scripts/demo.py` 里的 `synthetic_events()`：

```text
2026-05-01T02:00:00Z  login/failure  demo.user@198.51.100.77  attempt 1
2026-05-01T02:00:20Z  login/failure  demo.user@198.51.100.77  attempt 2
2026-05-01T02:00:40Z  login/failure  demo.user@198.51.100.77  attempt 3
2026-05-01T02:01:00Z  login/failure  demo.user@198.51.100.77  attempt 4
2026-05-01T02:01:20Z  login/failure  demo.user@198.51.100.77  attempt 5
2026-05-01T02:01:40Z  login/failure  demo.user@198.51.100.77  attempt 6
2026-05-01T02:02:20Z  login/success  demo.user@198.51.100.77
```

三件事让它可复现：

1. **事件 id 是 `uuid5(固定命名空间, "demo-event-N")`**，不是随机数。所以第二次运行
   导入的是同一批主键，整批被跳过——幂等性当场可见。
2. **`198.51.100.0/24` 是 RFC 5737 保留给文档的地址段**，不是任何真实网络。
3. **没有真实用户名、真实 IP、真实日志行**。`raw_message` 是拼出来的，
   格式像 sshd，内容不对应任何真实主机。

---

## 3. 对照实验：编造一个引用会怎样

这是最能说明设计意图的一段，30 秒，值得在面试时演示。

Agent 的结论里必须给出 `cited_event_ids`，每个 id 都要在**本告警的证据集**里。
用一个返回假 id 的桩模型就能看到后果：

```bash
# 1) 起一个永远引用 00000000-0000-0000-0000-000000000000 的桩
python - <<'EOF'
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        msg = {"content": json.dumps({
            "summary": "看起来像撞库",
            "risk_level": "high",
            "reasoning": "六次失败后成功",
            "recommended_actions": ["联系账号主人确认"],
            "limitations": ["仅覆盖认证日志"],
            "cited_event_ids": ["00000000-0000-0000-0000-000000000000"],
        })}
        body = json.dumps({"choices": [{"message": msg}],
                           "usage": {"prompt_tokens": 10, "completion_tokens": 10}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a): pass

ThreadingHTTPServer(("127.0.0.1", 8099), H).serve_forever()
EOF

# 2) 让 API 用这个桩（换一个终端重启 API）
export LLM_PROVIDER=stub LLM_MODEL=fake-citation LLM_API_BASE=http://127.0.0.1:8099/v1 LLM_API_KEY=sk-stub
uvicorn sentinelflow.main:app --port 8000

# 3) 再跑一次演示
python scripts/demo.py --username demo.admin --with-agent
```

预期结果（已实测）：

```text
最终：failed  轮次=1  工具调用=0  耗时=15ms
error_code=citation_invalid：Cited event 00000000-0000-0000-0000-000000000000 is not evidence of this alert
失败是可见的，不是静默产出一份错误报告。
```

**这就是这个项目的核心论点**：没有引用校验，上面那份"看起来像撞库"的报告会被签发；
有了它，幻觉的代价是任务失败。

顺带一个副产品：如果把 `limitations` 写成空数组，会先撞到 schema 校验：

```text
error_code=model_invalid_output：Model output did not match the required findings schema
```

因为 `AgentFindings.limitations` 要求 `min_length=1`——**模型不能声称自己没有局限**。
这条是写代码时定的，不是提示词里求它诚实。


---

## 4. 90 秒版（面试现场）

如果只有一分半，不要跑脚本，打开控制台讲这三屏：

| 屏幕 | 说什么 |
| --- | --- |
| 告警列表 | "规则只看行为，不做判断。它标记，不解释。" |
| 告警详情上半 | "6 条证据，每条能点回原始日志。这是所有结论的地基。" |
| 告警详情下半 | "Agent 调了一次工具，看了 6 条事件，引用了 3 条。**这 3 个 id 是数据库校验过的。**" |

然后补一句成本：**"这个 Agent 比单次调用模型贵 10.7 倍 token，准确率从 84% 到 93%——
但 22 个用例里这个差距在噪声范围内。它真正赢的地方是敢说'证据不足'：3/3 对 0/3。"**

---

## 5. 演示出问题时

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `失败：/health/ready 返回 503` | 数据库没起 | `pg_isready`；看 `DATABASE_URL` |
| `失败：登录失败（401）` | 账号不存在 | `sentinelflow-create-user --username demo.admin --role admin` |
| `失败：DEMO_PASSWORD 未设置` | 忘了导出 | `export DEMO_PASSWORD='...'` |
| 第 3 步 `新建 0 个告警` | 这个库跑过演示了 | 正常，幂等；想重来就换库或 `TRUNCATE` |
| 第 6 步 `503` | 服务端没配 `LLM_*` | 正常，这是明确的能力缺失而不是崩溃 |
| 第 6 步一直 `pending` | worker 没起 | `AGENT_WORKER_ENABLED=true`（默认开） |
| 第 6 步 `failed / model_timeout` | 模型太慢或连不上 | 调 `LLM_TIMEOUT_SECONDS`；检查 `LLM_API_BASE` |

前 5 步不依赖任何外部服务，所以**即使模型配错了，演示也不会开天窗**——
这是刻意设计的：确定性链路和模型链路分开。
