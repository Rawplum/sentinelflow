# 作品集材料

给技术面试官看的一组文档。**每一份都能追到代码或测试**，没有估算值。

| 文档 | 内容 | 什么时候看 |
| --- | --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 系统组成、一次调查的时序、数据模型、两个状态机 | 想知道它怎么搭的 |
| [DEMO.md](DEMO.md) | 可复现的演示流程、演示脚本、真实输出、故障排查 | 想看它跑起来 |
| [API_EXAMPLES.md](API_EXAMPLES.md) | 23 次真实请求/响应，含完整报告 | 想看接口长什么样 |
| [ENGINEERING_NOTES.md](ENGINEERING_NOTES.md) | 四个关键决策、六个技术难点、八个失败记录 | 想听判断过程 |
| [EVIDENCE.md](EVIDENCE.md) | 所有数字的出处和复现命令 | 想核对我说的话 |
| [RESUME.md](RESUME.md) | 三个岗位方向的简历描述 + 英文版 | 想看怎么包装 |
| [INTERVIEW.md](INTERVIEW.md) | 三个方向的 30 秒陈述、必问题目、危险问题 | 准备面试 |

---

## 如果你只有 5 分钟

1. 看 [ARCHITECTURE.md](ARCHITECTURE.md) 第 2 节「一次调查的时序」——
   它标出了三个**会主动失败**的位置，这是整个项目的设计核心。
2. 看 [EVIDENCE.md](EVIDENCE.md) 第 3 节的三条结论，
   特别是"Agent 和单次模型在准确率上分不出高下"。
3. 看 [ENGINEERING_NOTES.md](ENGINEERING_NOTES.md) 第 3.1 节——
   我做过容器化，验证不了，删了。

## 如果你只有 1 分钟

> 规则先按行为标出可疑登录，然后一个受控 Agent 去查日志、写结论。
> **它引用的每个事件 id 都必须真实存在于这条告警的证据里，编造一个整次调查就失败。**
> 幻觉的代价从"一份错误报告被签发"降为"任务失败"。
>
> 三方对照评测（规则 / 单次模型 / Agent）：72% / 84% / 93%，
> 但准确率差距在两次运行 5 处翻转的噪声内；Agent 唯一显著优势是拒答 3/3 对 0/3，
> 代价是 10.7 倍 token。

---

## 这些文档的可信度分级

| 级别 | 含义 | 有哪些 |
| --- | --- | --- |
| **可复现** | 一条命令能重跑出同样的结论 | API_EXAMPLES（脚本生成）、EVIDENCE 的测试与验收、DEMO |
| **有记录** | 数字来自某次真实运行，记录了环境与日期 | EVIDENCE 的性能、BENCHMARK 的评测 |
| **有解释** | 是设计判断，不是测量结果 | ARCHITECTURE、ENGINEERING_NOTES 的决策部分 |
| **主观** | 我自己的评价 | RESUME、INTERVIEW |

第三类和第四类不是"证据"，面试时要说清楚。比如"单 Agent 比多 Agent 更适合"
是我的判断，不是测出来的结论——我没做过多 Agent 的对照实验。

---

## 和其他文档的关系

```
README.md                    项目门面：解决什么问题、怎么启动
docs/ARCHITECTURE.md         工程向的架构说明（比 portfolio 版本更细）
docs/API_SPEC.md             接口契约
docs/DATA_MODEL.md           表结构
docs/TESTING.md              测试体系
docs/PERFORMANCE.md          性能实测
docs/BENCHMARK.md            Agent 评测
docs/SECURITY.md             安全设计与已知限制
docs/DECISIONS.md            决策记录（D-001 ~ D-052）
docs/V1_ACCEPTANCE.md        V1.0 验收报告
docs/HANDOFF.md              按天记录的开发日志，含失败与返工
docs/portfolio/              本目录：面向面试的材料
```

`docs/HANDOFF.md` 值得一读——它按天记录了每个决策的来龙去脉，包括把 Docker
加进来又删掉、CI 第一轮为什么挂。这类东西通常被藏起来，我留着是因为
**它比结论更能说明判断过程**。
