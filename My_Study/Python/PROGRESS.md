# 学习打卡表

> 每天完成后把 `[ ]` 改成 `[x]`，并在"笔记"列写一句话。
> 周末回头看一眼：连续三天没打勾，就砍掉"加练"，只保底做练习题。

## 第 1 周：语法 + 数据结构

| Day | 内容 | 完成 | 笔记（3 行以内） |
|---|---|---|---|
| 1 | 环境、fizzbuzz、环境变量布尔解析 | [ ] | |
| 2 | 字符串清洗、回文、统计 | [ ] | |
| 3 | 词频、去重、dict/set | [ ] | |
| 4 | 深合并、分组、递归 | [ ] | |
| 5 | 分块生成器、闭包 + 周复盘 | [ ] | |

**本周验收**：`pytest stage1_basics stage2_structures -q` 全绿；能解释"可变默认值陷阱"。

## 第 2 周：类 / 异常 / 文件 / 日志

| Day | 内容 | 完成 | 笔记 |
|---|---|---|---|
| 6 | dataclass Claim、property | [ ] | |
| 7 | default_factory、add_tag、to_dict | [ ] | |
| 8 | 自定义异常、金额解析 | [ ] | |
| 9 | JSON 配置、JSONL 读取 | [ ] | |
| 10 | Timer、logger + 周复盘 | [ ] | |

**本周验收**：`pytest stage3_oop_errors -q` 全绿；能说清 `raise ... from e` 的作用。

## 第 3 周：类型 / pydantic / 测试

| Day | 内容 | 完成 | 笔记 |
|---|---|---|---|
| 11 | typing 基础、补标注 | [ ] | |
| 12 | TypedDict、parse_tool_call | [ ] | |
| 13 | pydantic ClaimInput | [ ] | |
| 14 | retry 装饰器 | [ ] | |
| 15 | extract_json、pytest + 周复盘 | [ ] | |

**本周验收**：`pytest stage4_typing_testing -q` 全绿；`ruff check .` 无 error；能独立写 parametrize 测试。

## 第 4 周：并发 / asyncio / HTTP

| Day | 内容 | 完成 | 笔记 |
|---|---|---|---|
| 16 | 线程池计时实验 | [ ] | |
| 17 | 协程串行 vs 并发 | [ ] | |
| 18 | 信号量限流、超时 | [ ] | |
| 19 | 异步重试、httpx demo | [ ] | |
| 20 | 流式输出 + 周复盘 | [ ] | |

**本周验收**：`pytest stage5_async_http -q` 全绿；能说出"协程里调用阻塞函数"的后果。

## 第 5 周：Agent 核心

| Day | 内容 | 完成 | 笔记 |
|---|---|---|---|
| 21 | messages 结构、dry-run | [ ] | |
| 22 | 工具 schema、工具分发 | [ ] | |
| 23 | Agent Loop | [ ] | |
| 24 | 上下文裁剪、结构化输出 | [ ] | |
| 25 | capstone 真实调用 + 复盘 | [ ] | |

**本周验收**：`pytest stage6_agent -q` 全绿；能白板画出 Agent Loop。

## 第 6 周：项目实战

| Day | 内容 | 完成 | 产出 |
|---|---|---|---|
| 26 | 读配置与工具层 | [ ] | 依赖图 + 疑问清单 |
| 27 | 读 Agent 编排 | [ ] | 手写 Loop vs LangGraph 对照表 |
| 28 | 新增一个工具 + 测试 | [ ] | 代码 + 2 个用例 |
| 29 | 超时/重试/结构化日志 | [ ] | 降级方案说明 |
| 30 | 复盘文章 + 毕业自测 | [ ] | 800 字笔记 |

---

## 毕业自测（不看资料）

- [ ] 写出一个带类型标注、pydantic 校验、自定义异常的函数，并配 3 个 pytest 用例。
- [ ] 用 `asyncio.gather` + `Semaphore` + 超时并发调用 20 个接口。
- [ ] 手写 Agent Loop，并用假 LLM 测试"工具调用 → 最终回答"。
- [ ] 解释 `list` / `dict` / `set` 的复杂度与适用场景。
- [ ] 解释 GIL、协程、线程池的取舍。
- [ ] 读懂 `agents/claim_agent.py` 的主流程并指出 3 个失败点。
