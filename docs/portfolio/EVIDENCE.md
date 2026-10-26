# 证据索引

这份材料里出现的每个数字，都能在下面找到出处和复现命令。

**没有估算值，没有"大约"，没有"理论上"。** 测不出来的就写"未测量"。

---

## 1. 测试

| 项 | 结果 | 复现 |
| --- | --- | --- |
| 后端（SQLite，默认） | **363 passed, 3 skipped** | `pytest -q` |
| 后端（PostgreSQL 16） | **365 passed, 1 skipped** | 见下方命令 |
| 后端（PostgreSQL + 迁移测试） | **366 passed, 0 skipped** | CI 的 `postgres` job |
| 迁移升降级 | 1 passed（`0001`→`0006` 再降回） | `pytest tests/test_migrations.py` |
| 前端单元 | **48 passed / 12 个文件** | `cd frontend && npm test` |
| 浏览器端到端 | **16 项全通过** | `node e2e/browser.mjs` |
| 端到端验收 | **65/65** | `python scripts/acceptance.py --reset` |
| 安全负向测试 | **86 passed** | 27（agent）+ 46（hardening）+ 13（unit） |
| 静态检查 | ruff **0 问题**；mypy **109 个文件 0 错误** | `python scripts/check.py --fast` |
| 迁移一致性 | `alembic check` 无漂移 | 需可连数据库 |

```bash
# PostgreSQL 全量
export TEST_DATABASE_URL=postgresql+psycopg://user:pw@127.0.0.1:5432/sentinelflow_test
export MIGRATION_TEST_DATABASE_URL=postgresql+psycopg://user:pw@127.0.0.1:5432/sentinelflow_migration_test
pytest -q
```

**3 个 skip 是什么**（不藏着）：

| 跳过项 | 原因 |
| --- | --- |
| `test_migrations.py`（1 项） | 没设 `MIGRATION_TEST_DATABASE_URL`。它会 DROP 表，必须用独立库 |
| `test_concurrency.py`（2 项） | SQLite 忽略 `SELECT ... FOR UPDATE`，既复现不了竞态也证明不了修复 |

SQLite 与 PostgreSQL 的差值是 3：2 项并发 + 1 项迁移。
这不是"SQLite 上少测了"，是**这些测试在 SQLite 上无意义**。

---

## 2. 性能（实测，`docs/PERFORMANCE.md`）

环境：Windows 10.0.22631 / Python 3.11.4 / PostgreSQL 16.15 本机集群 /
uvicorn 单进程单 worker / 单客户端串行 keep-alive。
数据全部由 `perf/dataset.py` 按固定种子合成，**不混任何真实日志**。

三档规模：1 750 / 16 150 / 96 150 条事件。

### 读路径 P50 / P95（96k 事件）

| 场景 | P50 | P95 |
| --- | --- | --- |
| 事件第一页 | 11.0 ms | 12.8 ms |
| 事件深分页（offset 20000） | 15.1 ms | 16.7 ms |
| 事件按结果过滤 | 18.0 ms | 28.9 ms |
| 事件按用户过滤 | 7.9 ms | 12.9 ms |
| 事件关键字搜索 | 39.1 ms | 47.9 ms |
| 告警列表 | 5.9 ms | 9.4 ms |
| 告警详情 | 5.8 ms | 7.5 ms |
| 告警证据页（50 条） | 8.7 ms | 18.2 ms |
| 报告（150 条证据 → 截断 100） | 12.8 ms | 31.2 ms |

错误率全程 **0%**。报告响应固定约 **50 KB**，不随表增长——这是上限生效的证据。

### 写路径

| 场景 | 1.7k | 16k | 96k |
| --- | --- | --- | --- |
| 导入 500 条新事件 | 15.3 ms | 16.2 ms | 16.0 ms |
| 重复导入同 500 条 | 14.6 ms | 15.0 ms | 16.4 ms |
| 检测（首次，建 N 个告警） | 78 ms | 499 ms | **3 038 ms** |
| 检测（重复运行，全部跳过） | 27 ms | 178 ms | 1 147 ms |

### 一次真实的优化

| | 修复前 | 修复后 |
| --- | --- | --- |
| 检测（96k 事件 → 6000 个告警） | **25.6 s** | **3.0 s** |
| 原因 | 每告警 9 次往返（SAVEPOINT + INSERT + 每条证据一次 INSERT + RELEASE） | 整批一个 savepoint + 批量关联插入 |
| 手段 | — | 批量化。**没有加缓存，没有加组件** |

`cProfile` 显示扫描本身只占 2.2 秒，所以瓶颈确实在写入路径，不在算法。

### 另一个不是"缺索引"的问题

| 状态 | 深分页 P95 |
| --- | --- |
| 批量导入后、`ANALYZE` 之前 | **515 ms** |
| `ANALYZE` 之后 | **16.7 ms** |

先 `EXPLAIN (ANALYZE, BUFFERS)` 直接跑 SQL 只用了 4 ms，才去查
`pg_stat_user_tables` 发现 `last_analyze` 是 NULL。**是统计信息过期，不是索引缺失。**

复现：`python -m perf.runner --alerts 6000`（需要 `PERF_DATABASE_BASE` 指向一个 PostgreSQL）。

---

## 3. Agent 评测（`docs/BENCHMARK.md`）

25 个合成用例，三条基线跑同一套数据。模型基线可评 **22** 个
（3 个依赖故障注入，模型无法满足，显式跳过并打印）。

模型：DeepSeek-V4.1-Flash，`temperature: 0`，跑两遍。

| 指标 | 规则基线 | 单次模型 | Agent |
| --- | --- | --- | --- |
| 期望匹配（两遍合计） | **13/18 = 72%** | **37/44 = 84%** | **41/44 = 93%** |
| 期望匹配（逐遍） | 72% / 72% | 82% / 86% | 91% / 95% |
| 合理拒答（3 个用例） | 0/3 | 0/3 – 1/3 | **3/3** |
| 引用有效率 | 100% | 100% | 100% |
| 结构校验通过率 | 100% | 100% | 100% |
| 工具调用成功率 | — | — | 100%（110 次） |
| 不安全操作拦截 | — | — | 2/2 |
| 平均延迟 | 4 ms | 5.1 s | 11.0 s |
| 输入 token（22 用例） | — | **15.6k** | **166k** |

### 三条必须一起说的结论

1. **有模型远好于没模型**：72% → 84–93%。差距不在"算得准"，在规则引擎只有一种输出形态，
   三处必错（不拒答、不指出矛盾、不据日志降级）。
2. **Agent 和单次模型在准确率上分不出高下**：93% vs 84% 看着差 9 个点，
   但 **22 个用例两次运行有 5 处判定翻转**（44 个判定里 ≈11%），这个差距在噪声里。
3. **Agent 真正赢的是拒答 3/3 vs 0/3**。它逐个取证、看到证据边界，敢说证据不足。
   这是能力差异，不是随机波动。

代价是量出来的：**输入 token 10.7 倍，延迟 2.2 倍**。金额成本未测量（没有写死单价）。

### 这份评测最弱的地方

22 个可评用例、**一个人标注**、rubric 改过两版。所以
`expectation_match_rate` 衡量的是"与作者判断一致的程度"，**不是客观正确率**。
任何引用这个数字的场合都必须带上这句。

---

## 4. 安全

| 检查 | 结果 |
| --- | --- |
| 硬编码密钥（全历史扫描 7 种模式） | **0 处**（仅测试桩 `sk-stub-not-a-real-key`） |
| 公开 API 操作 | 20 个操作中 3 个公开（`/health`、`/health/ready`、`/auth/login`） |
| 登录限流 | 第 6 次失败 → **429**（按用户名 5 次 / 按 IP 20 次） |
| 超大请求体 | 6 MiB → **413** |
| SQL 注入 | `' OR 1=1 --`、`%'; DROP TABLE ...` 等 3 种 → 无效果，参数化查询 |
| 未认证访问业务接口 | → **401** |
| 422 错误响应 | 不含 traceback / SQLAlchemy / 文件路径 |
| 日志 | 不打印 token / 密码 / DSN |
| 登出后复用 token | → **401** |

复现：`docs/V1_ACCEPTANCE.md` §5 有逐项命令。

**已知未修**：`/docs`、`/redoc`、`/openapi.json` 是公开的。本地演示方便，
对外是信息暴露面。记为已知限制——修它会移除文档化能力，超出"只修阻塞问题"的范围。

---

## 5. 代码规模

| 部分 | 行数 |
| --- | --- |
| 后端 `src/sentinelflow` | 7 323 |
| 前端 `frontend/src` | 5 715 |
| 测试 `tests/` | 7 375 |

测试行数与后端代码接近 1:1。数据库 12 张表，6 个迁移版本（`0001`→`0006`）。

---

## 6. 这些数字是怎么来的（可复核性）

| 类别 | 谁产生的 | 能不能重跑 |
| --- | --- | --- |
| 测试结果 | `pytest` / `vitest` / `node e2e/browser.mjs` | 能，命令在上表 |
| 验收 65 项 | `scripts/acceptance.py` | 能，自己起服务、自带桩模型 |
| API 示例 | `scripts/capture_examples.py` | 能，**文档由脚本生成**，不是手写 |
| 性能 | `perf/runner.py` + `perf/concurrency.py` | 能，但耗时几分钟 |
| 评测 | `benchmark/runner.py --model real` | 能，但**需要付费密钥** |
| 安全负向 | 手工脚本 + `tests/test_security_*.py` | 测试能重跑；手工脚本已并入验收脚本 |

`docs/portfolio/API_EXAMPLES.md` 是唯一"不能手改"的文档——它由脚本生成，
改内容只能改脚本或改代码。
