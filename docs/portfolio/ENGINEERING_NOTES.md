# 技术决策、难点与失败记录

这份文档只写**能从代码或测试里指出来**的东西。每个决策都带代价，每个失败都带后续。

---

## 1. 四个关键决策

### 1.1 单个 Agent，不用多 Agent 编排

**做法**：一个调查任务 = 一个 `run_agent()` 循环，最多 5 轮、8 次工具调用、
180 秒运行时长、单次工具 5 秒超时。

**理由**：

- 这个任务的形状是**取证**，不是分工。6 条日志、4 个只读工具，
  一个循环就能覆盖，拆成"分析员 + 审核员 + 汇总员"只会让每一步都多一次模型调用。
- 多 Agent 的收益来自**独立视角**（一个找证据、一个反驳）。但这里反驳的成本更低：
  引用校验是确定性的，不需要第二个模型来质疑第一个。
- 可观测性。单循环意味着 `rounds` 和 `tool_calls` 能一对一落库
  （`investigation_rounds` / `investigation_tool_calls`），出问题能回放到具体哪一轮。
  多 Agent 的调用树落库和重放要复杂一个量级。

**代价，实测出来的**：Agent 输入 token 是单次模型的 **10.7 倍**，延迟 2.2 倍，
而准确率 93% vs 84% 在 22 个用例两次运行的噪声里分不出高下（见 `docs/BENCHMARK.md`）。
**唯一站得住的优势是拒答 3/3 对 0/3**——它逐个取证、看到证据边界，敢说证据不足。

如果重来：我会先做单次模型基线，再决定要不要 Agent。现在这个顺序是反的，
先做了 Agent 才发现它不比单次调用强多少。

### 1.2 权限检查在工具层，不在提示词里

**做法**：`src/sentinelflow/ai/tools.py` 里每个工具声明 `required_permission`，
执行前用**和 HTTP 层同一个** `has_permission()` 检查：

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str
    input_model: type[BaseModel]  # extra="forbid"，参数不接受多余字段
    required_permission: Permission  # 与路由共用一套枚举
    handler: Callable[[ToolContext, Any], dict[str, Any]]
```

**为什么不能靠提示词**：提示词是给模型的建议，模型可以不听。而 `TOOL_SPECS` 是查找表，
不在表里的名字在**触碰任何模型提供的参数之前**就被拒绝。

四层，从外到内：

| 层 | 拦住什么 | 在哪 |
| --- | --- | --- |
| 1. 白名单 | 不存在的工具名、`delete_*`、`run_sql` | `TOOL_SPECS` 查找 |
| 2. 权限 | analyst 用需要写权限的工具 | `has_permission(role, spec.required_permission)` |
| 3. 参数 | 多余字段、越界数值、`"5"` 冒充 `5` | Pydantic `extra="forbid"` + `strict=True` |
| 4. 作用域 | 查别的告警、跨告警聚合 | `ToolContext` 只持有本告警 + 证据 id 集合 |

第 4 层是关键：`ToolContext` 里**没有 session factory，没有 engine**，
只有 `session`、`alert`、`evidence_ids`。工具函数拿不到"查全库"的能力，
因为 `evidence_query(alert.id)` 已经把作用域钉死了。

**代价**：加一个工具要改三处（spec、input model、handler），比"给模型一个通用 SQL 工具"啰嗦得多。
但这个啰嗦换的是"负向测试能写出来"——`tests/test_security_hardening.py` 里有
2 个用例专门让模型请求禁用工具，断言被拦。

### 1.3 确定性规则作为基线，不是产品核心

**做法**：`AUTH-001`，同一账号 + 同一来源，任意 5 分钟窗口内 ≥5 次失败 → 一个 high 告警。
滑窗 O(n)，纯函数 `find_suspicious_login_windows()` 与数据库解耦，可以单独测。

**理由**：

- **它给出可对照的下界。** 没有基线，"Agent 93%"这个数字没有意义——
  93% 是比 72% 好，还是比 99% 差？
- **它保证系统在没模型时仍然可用。** 没配 `LLM_*` 时，导入、检测、告警、
  确定性报告全都能跑，只有 Agent 返回 503。演示脚本的前 5 步就是这个路径。
- **它的失败方式是可预测的。** 它永远给结论、永远按 `alert.severity` 分级，
  所以三处必错：证据不足不拒答（0/3）、日志自相矛盾不指出（0/2）、
  失败原因写在日志里不据此降级。**这三处正好是"要不要引入模型"的论证材料。**

**一个诚实的说明**：规则基线在 `min_risk`/`max_risk` 上的分数是**同义反复**——
`build_report` 的 `risk_level` 直接取自 `alert.severity`，而 severity 是测试用例里写死的输入。
所以基准报告里这个基线带 `caveat` 字段。它真正可比的是：结构化输出 100%、
引用有效性 100%（直接从数据库生成）、**能不能表达不确定 0/3**。

### 1.4 队列用数据库，不用 Redis 或 Celery

**做法**：`investigations` 表就是队列。`lease_expires_at` 是租约，
`attempt_count` / `max_attempts` 是重试上限。worker 用
`UPDATE ... WHERE status='pending' AND (lease IS NULL OR lease < now)` 抢占。

**理由**：

- 任务量是**人工触发**的（点一下按钮一个任务），不是每秒上千。
  数据库的行锁完全够，多引入一个组件换来的是多一个会挂的东西。
- 队列状态和业务状态**在同一个事务里**。任务成功时，报告、轮次、工具调用、
  任务状态一次提交；用 Redis 就得处理"消息发出去了但事务回滚了"。
- 进程崩了不需要额外机制：租约到期，任务自动可被重新领取；
  超过 `max_attempts` 的由回收逻辑判 `failed`，错误码留在表里。

**代价**：

- 轮询领取有延迟（worker 间隔），不适合低延迟场景。
- 单进程单 worker，**多副本并发没有验证过**。两个 worker 同时抢同一条任务靠
  `UPDATE ... WHERE` 的原子性保证只有一个成功，但这条没有在 CI 里测。
- 一个真实观察：两个 API 进程连同一个库时，**任意一个 worker 都可能领走任务**，
  用它自己的模型配置执行。我做引用校验实验时就撞上了——起了第二个进程配假模型，
  结果任务被第一个进程的 worker 领走，跑出了正常结果。

---

## 2. 五个技术难点

### 2.1 "证据"到底怎么定义

引用校验的难点不在比较 id，在**什么算合法引用**。

第一版想的是"引用的 id 必须存在于数据库"——太松，模型可以引用别的告警的事件。
现在定义是：**必须属于本告警的 `alert_events` 关联集**。

```python
def validate_citations(findings, evidence_ids: frozenset[uuid.UUID]) -> list[uuid.UUID]:
    for event_id in findings.cited_event_ids:
        if event_id not in evidence_ids:
            raise CitationValidationError(...)
        ...
    if not seen:
        raise CitationValidationError("Findings cite no evidence")
```

两个细节：

- `evidence_ids` 在**任务开始时**取一次快照，不是每次校验时重查。
  否则调查过程中告警证据变了，同一次调查的前后轮次会面对不同的合法集。
- **必须至少引用一条**（`if not seen: raise`）。允许零引用等于允许"没有任何依据的结论"。

### 2.2 超时了，线程不会停

工具超时用线程池 + `Future.result(timeout=5)`。Python 没有安全的线程终止机制，
所以**超时后工作线程还在跑**，只是结果被丢弃。

这不是疏忽，是权衡：真要能中断，就得把工具改成协作式（每步检查取消标志），
或者换成进程池（序列化开销 + 每进程一个连接）。对一个最多 5 秒的只读查询，不值得。

**诚实地说**：一个卡在数据库连接上的工具线程会一直占着，直到驱动自己超时。
现在的缓解是 SQL 层有限制（`limit ≤ 50`）和 PostgreSQL 的 `connect_timeout`。
这是已知局限，写在 README 的「已知限制」里。

### 2.3 两个并发缺陷，同一个形状

**症状**（`perf/concurrency.py` 实测）：

| 场景 | 结果 |
| --- | --- |
| 8 客户端 × 6 轮改告警状态 | 历史链断裂：出现"`investigating` 之后接 `open`" |
| 3 个告警 × 6 个并发 POST 调查 | 接受了 **5 个**调查（应恰好 3 个） |

**原因**：两处都是同一个形状——先读、再判断、再写，中间没有原子性。

```python
alert = session.get(Alert, alert_id)  # 读
if alert.status == ...:
    raise ...  # 判断
alert.status = new_status  # 写
```

**修法**：`session.get(Alert, alert_id, with_for_update=True)`，一行。

**为什么不是版本号或重试循环**：行锁不引入新列、不改 API 契约、不加重试。
代价是同一告警上的状态更新串行化——但人工操作频率极低，不是性能问题。

**为什么 SQLite 上测不出来**：SQLite 忽略 `FOR UPDATE`。所以
`tests/test_concurrency.py` 的两项**只在 PostgreSQL 下执行**，skip 理由写在测试里：

```python
pytestmark = pytest.mark.skipif(
    "sqlite" in os.environ.get("TEST_DATABASE_URL", "sqlite"),
    reason="SQLite ignores SELECT ... FOR UPDATE",
)
```

**一个更诚实的说明**：状态更新那条单元测试**抓不稳这个竞态**。
窗口只有微秒级，我加了 50ms 延迟、10 线程 × 4 轮，仍然不能可靠复现。
所以测试 docstring 里写的是：

> Invariant check, not a race reproducer. ... The reproduction is
> `python -m perf.concurrency`, which drives the same path over HTTP.

我没有把它包装成"复现器"。真正的复现证据是修复前那次 perf 运行。
另一条（并发发起调查）做了变异验证：撤掉行锁，测试报
`5 investigations were created for one alert`。

### 2.4 检测写入：每个告警 9 次往返

**症状**：96k 事件、6000 个告警，检测耗时 **25.6 秒**。
`cProfile` 显示扫描只占 **2.2 秒**——剩下的 23 秒全在写入。

**原因**：每个告警一个 SAVEPOINT + 一次 INSERT + 每条证据一次 INSERT + RELEASE，
6000 × 9 ≈ 54000 次往返。

**修法**：整批一个 savepoint，`session.add_all()` + `insert(alert_events)` 批量关联；
撞 dedup 唯一约束时整批回滚，退回逐条路径。

**结果**：3.0 秒（8.4 倍）。**没有加缓存。**

保留逐条回退的原因：原来的逐条 savepoint 语义是"并发撞键时跳过而不是整批失败"。
批量化不能丢掉这个语义，所以让它成为异常路径。

### 2.5 查询慢 20 倍，不是缺索引

**症状**：96k 事件刚导入后，`offset=20000` 的深分页 P95 **515 ms**；
`ANALYZE` 之后 **16.7 ms**。

**排查顺序**（重要：先看 SQL 再看统计）：

1. `EXPLAIN (ANALYZE, BUFFERS)` 直接跑 SQL → **4 ms**。索引没问题。
2. 但 API 实测 306 ms。差距 75 倍 → 不是 SQL 本身。
3. 查 `pg_stat_user_tables` → `last_analyze` 是 NULL，`last_autoanalyze` 在批量导入之后才触发。
4. 结论：**规划器在用导入前的行数估计**，选了顺序扫描 + 全排序。

**修法**：不是加索引，是让这件事**可观测**——`perf/runner.py` 显式测量冷/热两态，
`_read_scenarios_cold()` 在 `ANALYZE` 之前跑，`_read_scenarios()` 之后跑。
文档里写明"批量导入后要 ANALYZE"。

这个修复没让代码变快一行，但它把一个隐藏的悬崖变成了一个数字。

### 2.6 一个语义坑：`evidence_truncated` 有两种含义

Agent 报告里 `evidence` 只有 3 条，而 `evidence_count=6`、`evidence_truncated=true`。

容易误读成"分页截断了"。实际语义是：**Agent 报告的证据是"引用子集"，不是"第一页"**。
所以 `evidence_truncated` 在这里表示"这不是全集"，`evidence_total` 给全集大小。

确定性报告才是真的分页：最多 100 条（`MAX_REPORT_EVIDENCE`），超出标记截断。
两种含义共用同一个字段是个**命名缺陷**——如果重来，我会叫 `evidence_is_subset`。

---

## 3. 失败记录

### 3.1 容器化：做了，验证不了，删了

完整过程：先补齐四服务 `compose.yaml` + 两个非 root 镜像 + nginx 同源反代，
用静态校验 17 项（还做了变异测试）+ 命令级等价验证 + 生产构建 E2E 去补。

然后删掉。理由不是麻烦：

- 那套配置**从头到尾没有一次真实执行**。静态校验证明的是"命令序列可行"，
  不是"容器可行"——两者之间的差距（镜像构建、容器 DNS、healthcheck 触发、
  非 root 权限）恰好是最容易出问题的地方。
- 它承诺"一条命令起整套"，代价是每次 schema 变更都要同步维护一份没人验证的配置。
- Docker 唯一真正解决的问题是"不用装 PostgreSQL"，而 PostgreSQL 是一次性安装。

删了 7 个文件，换成 `sentinelflow-doctor`（诊断工具）+ 一条走通的本地路径。
容器版留在 Git 历史 `704d4f9`。决策记在 `docs/DECISIONS.md` D-050。

**这一条是整份文档里最能说明判断力的**：我做过，验证不了，于是不声称它可用。

### 3.2 基准第一轮：Agent 33%，比规则还差

第一轮真实模型跑出来 `agent 3/9 = 33%`。查下来**三处都是基准的错，不是模型的错**：

| 缺陷 | 表现 | 修法 |
| --- | --- | --- |
| 三个用例依赖故障注入 | 真实模型不可能满足 `should_fail` | 标 `requires_fault_injection`，模型基线跳过并打印跳过了哪些 |
| 风险等级没定义就评分 | 提示词只说 `low/medium/high`，没说各等级对应什么证据 | 两处提示词都写入 rubric |
| rubric 与用例期望矛盾 | rubric 说"失败后成功 → high"，但良性用例期望 medium | rubric 补降级条件 |

第三条最值得记：**模型照着 rubric 执行，被判错了**。
这不是"模型不行"，是评分标准自相矛盾。修 rubric 之后，Agent 从 33% 到 93%。

改标注的 5 个用例全部记录在 `docs/BENCHMARK.md`，包括"这些改动会让规则基线变好看"。

### 3.3 接入一个网关：token 无效，不是客户端问题

试过 `agentrouter.org/v1` 的 `gpt-6.1-sol`，全部 401。排查用对照实验：

| 检验 | 结果 |
| --- | --- |
| 无 key / 假 key / 真 key | 三者返回**完全相同**的 `unauthorized client detected` |
| 真实 Chromium（Playwright 同源 fetch） | 同样 401 → 排除 TLS 指纹、UA |
| 直连 / 走代理 | 相同 → 排除出口 IP |
| 4 种鉴权头 | 全部 401 |
| `GET /api/status` | 200（网关可达） |
| `GET /api/user/self` | 200 + `access token 无效` |

**关键推理**：假 key 和真 key 返回同一个字符串，说明服务端根本没走到鉴权比对。
结论是 token 本身无效，不是客户端实现问题。

这次排查沉淀成了 `python -m benchmark.runner --probe`。

### 3.4 CI 第一次跑就红了，因为工作流违反了自己的守卫

```text
FAILED tests/test_migrations.py::test_alembic_upgrade_and_downgrade
Failed: MIGRATION_TEST_DATABASE_URL must point to a test database
```

测试里有一道守卫：数据库 URL 必须含 `test`，否则拒绝运行——防止误把测试指向生产库。
而工作流建的是 `sentinelflow_migrations` 和 `sentinelflow_ci`，都不含 `test`。

**本地跑不出来的原因**：本地只设了 `TEST_DATABASE_URL`，迁移测试被 skip；
CI 两个 URL 都设了，守卫立刻触发。**差别在环境变量的组合。**

修法：改库名，**没有**放宽守卫，**没有**加 skip。另加一条测试盯着工作流本身：
`test_ci_test_databases_satisfy_the_test_guard` 解析 YAML，断言每个
`*_TEST_DATABASE_URL` 都含 `test`。变异验证：改回去，报出的错误和 CI 一模一样。

### 3.5 一次真实的误判：是我断言错了，不是产品错了

并发测试第一次报"3 个告警接受了 5 个调查"，我判定为产品缺陷并加了行锁。
后来发现**断言写错了**：桩模型瞬间返回，第一个调查已经结束后再发就是合法的。

真正的判据不是"接受了几次"，而是**"同一告警的两个调查时间区间不得重叠"**。
改成查 `started_at`/`completed_at` 的区间重叠，并把桩模型调慢到 1.5 秒。

**这条值得单独讲**：如果我当时满足于"加个行锁就好了"，会留下一个
"看起来修好了、其实没测对"的测试。行锁本身是对的（并发确实超发了），
但**证据是错的**，而错误的证据会掩盖下一次回归。

### 3.6 验收脚本自己把 success 写成了 failure

`scripts/acceptance.py` 里构造事件时：

```python
{"outcome": outcome, **EVENT_TEMPLATE}  # 错
```

`EVENT_TEMPLATE` 里有 `outcome: "failure"`，展开在后面覆盖了参数。
结果 7 条事件全是失败，检测出 7 条证据，而期望是 6。

我第一反应是"产品 bug"。查数据库才看到 `linked evidence by outcome` 全是 failure。
**产品是对的，脚本错了。** 修的是顺序：模板在前，具体字段在后。

### 3.7 两次运行 5 处判定翻转

客户端已经发 `temperature: 0`，两次运行仍有 5 处判定翻转（44 个判定里 ≈11%）：

```text
single_shot/insufficient_single_event: run1=(False,'low')   run2=(True,'low')
agent/expired_password_retry:          run1=(False,'medium') run2=(True,'medium')
agent/double_typo_success:             run1=(True,'medium')  run2=(False,None)
agent/success_failure_alternating:     run1=(True,'medium')  run2=(True,'high')
agent/injection_secret_request:        run1=(False,'medium') run2=(True,'medium')
```

**结论：报区间，不报单值。** 文档里写的是"93% vs 84%，但 22 个用例两次运行就有 5 处翻转，
这个差距在噪声里"。任何声称"我的 Agent 准确率 93%"的简历写法，我都不写。

### 3.8 那些"通过检查才暴露"的问题

引入 ruff + mypy 之后修了 185 条告警、49 个文件格式、25 个类型错误。
其中**三条不是风格问题**：

1. `agent.py` 的 `round_ms()` 是闭包，捕获循环变量 `round_started`。
   当前在同一迭代内调用所以没出错，但任何后续调用点都会读到最后一轮的值。
2. `test_agent.py` 本地又定义了一个 `FailingClient`，和 `tests/support` 里的
   字节级相同，只是遮蔽了导入。
3. `evaluation/metrics.py` 对可空的 `item.report` 直接 `.get()`。

第 1 条是典型的"现在没坏、以后会坏"。静态检查的价值就在这里——
它不看你今天跑没跑过。

---

## 4. 刻意没做的事

| 没做 | 为什么 | 有数字吗 |
| --- | --- | --- |
| 关键字搜索装 `pg_trgm` | 96k 事件下 39 ms。加索引要加部署依赖，39ms 可以接受 | 有，`docs/PERFORMANCE.md` |
| 深分页换 keyset | 15 ms。根治要改 API 契约（游标），当前不值得 | 有 |
| `count(*)` 优化 | 19 ms，非选择性过滤本就不适合索引 | 有 |
| 检测扫描列投影 | 能再省约 0.4 秒（2.2 → 1.8），改动面大 | 有 |
| 多 Agent 编排 | 见 1.1，单循环已经够，且更好观测 | 无（未实现） |
| 缓存层 | 所有接口 P95 < 50 ms（检测除外），缓存只会引入一致性风险 | 有 |
| 前端定稿按钮 | `finalizeReport` 只有 API 封装，没有组件调用 | 无（未接入） |
| TLS / MFA / 审计归档 | 属于部署与合规，不是功能缺口 | 无 |

---

## 5. 如果继续做，优先级

1. **评测集的期望换成多人标注**。现在 22 个可评用例、一个人标注、rubric 改过两版。
   这是整份材料里最弱的一环——所有准确率数字都建立在这上面。
2. **多副本 worker 的并发验证**。队列设计支持，但没有测过两个 worker 抢同一任务。
3. **审计日志的保留与归档**。append-only 只解决了"不能改"，没解决"不能无限长"。
4. **真实日志的适配层**。现在只认一种 JSONL 形状，接真实 sshd / Windows 事件日志需要映射层。
