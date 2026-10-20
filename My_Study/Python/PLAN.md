# 30 天逐日计划（每天 60~90 分钟）

时间分配建议：**读 20 分钟 + 写 50 分钟 + 复盘 10 分钟**。
每天结束时在 `PROGRESS.md` 打勾，并写 3 行笔记。

> 命令统一在 `G:\Workspace\claims-ai-agent\My_Study\Python` 下执行。
> 下文 `pytest stageN -q` 均指 `.\.venv\Scripts\python.exe -m pytest stageN -q`。

---

## 第 1 周：语法地基 + 数据结构与函数

目标：能读懂并写出 100 行以内的普通 Python 脚本；彻底搞清 dict/list 与函数参数。

### Day 1 —— 环境与语法速通
- 读：`cheatsheet/java_vs_python.md` 第 1~3 节；`stage1_basics/README.md` 第 1~2 节。
- 做：`stage1_basics/exercises.py` 的 `fizzbuzz`、`parse_env_flag`。
- 验：`pytest stage1_basics -q -k "fizzbuzz or env"`。
- 重点：缩进即语法、无分号、`None` vs `null`、`and/or/not`、真值判断。
- 项目对照：`config.py` 里环境变量读取的写法。

### Day 2 —— 字符串与真实文本处理
- 读：`stage1_basics/README.md` 第 3~4 节（f-string、字符串方法、`re` 入门）。
- 做：`clean_text`、`is_palindrome`、`stats`。
- 验：`pytest stage1_basics -q`（应当全绿）。
- 重点：字符串不可变、`"".join()` 优于 `+=`、`str.translate`、`split()` 自动压缩空白。
- 加练：把 `clean_text` 改成用 `re.sub` 实现，比较可读性。

### Day 3 —— list / dict / set 与切片
- 读：`stage2_structures/README.md` 第 1~3 节。
- 做：`stage2_structures/exercises.py` 的 `word_freq`、`dedupe`。
- 验：`pytest stage2_structures -q -k "word or dedupe"`。
- 重点：dict 查找 O(1)、`Counter`、`sorted(key=...)`、切片 `[::-1]`、可变对象别名。
- 项目对照：`tools/` 里对 dict 的处理。

### Day 4 —— 推导式、解包、深层合并
- 读：`stage2_structures/README.md` 第 4~5 节。
- 做：`deep_merge`、`group_by`。
- 验：`pytest stage2_structures -q -k "merge or group"`。
- 重点：列表/字典推导式（对照 Java Stream）、`**` 解包、递归、不要修改入参。
- 坑：`dict.update` 是浅合并；`copy.deepcopy` 的性能代价。

### Day 5 —— 函数、闭包、生成器 + 周复盘
- 读：`stage2_structures/README.md` 第 6~8 节。
- 做：`chunked`、`make_counter`，跑完整 `pytest stage2_structures -q`。
- 重点：默认参数在定义时求值（可变默认值陷阱）、`nonlocal`、`yield` 惰性求值。
- 复盘：用 10 分钟不看资料，写出"Java Stream vs Python 推导式/生成器"的对照。
- 加练：LeetCode 1（两数之和），用 dict 一次遍历。

---

## 第 2 周：类、异常、文件、配置、日志

目标：能写出结构清晰、可配置、可观测的 Python 模块。

### Day 6 —— 类与对象模型
- 读：`stage3_oop_errors/README.md` 第 1~2 节。
- 做：`Claim` dataclass（含 `__post_init__`、`property`）。
- 重点：`self` 显式、无 overload、`__repr__` ≈ `toString()`、类属性 vs 实例属性。
- Java 对照：`@dataclass` ≈ Lombok `@Data`，但更透明。

### Day 7 —— 可变性、默认值、Enum、组合
- 读：`stage3_oop_errors/README.md` 第 3 节。
- 做：给 `Claim` 增加 `add_tag` + `to_dict`；用 `Enum` 约束状态（在 `solutions.py` 看写法）。
- 重点：`field(default_factory=list)` 的原因；组合优于继承；`frozen=True` 的不可变对象。
- 加练：把 `status` 改成 `StrEnum`，跑测试确认不破坏行为。

### Day 8 —— 异常体系
- 读：`stage3_oop_errors/README.md` 第 4 节。
- 做：`ClaimError` + `parse_amount`。
- 重点：EAFP、只捕获预期异常、`raise ... from e`、不要在 except 里 `pass`。
- 项目对照：`tools/` 里工具失败时返回错误还是抛异常？为什么？

### Day 9 —— 文件、pathlib、JSON / JSONL
- 读：`stage3_oop_errors/README.md` 第 5 节。
- 做：`load_json`、`read_jsonl`。
- 重点：`Path` 代替字符串拼接、`encoding="utf-8"` 必写、`ensure_ascii=False`、流式读大文件。
- 大数据对照：JSONL ≈ 按行处理的 DataFrame 输入；不要一次 `read()` 几个 G。

### Day 10 —— 上下文管理器、日志、配置 + 周复盘
- 读：`stage3_oop_errors/README.md` 第 6~7 节。
- 做：`Timer`、`setup_logger`，跑完整 `pytest stage3_oop_errors -q`。
- 重点：`with` ≈ try-with-resources；logger 幂等；`propagate`；日志别用 print。
- 项目对照：`monitoring.py` 的日志/指标写法。
- 复盘：写一页"Python 工程化与 Java 的差异"。

---

## 第 3 周：类型标注、pydantic、装饰器、测试

目标：从"能跑"升级到"可维护、可测试、可静态检查"。

### Day 11 —— typing 基础
- 读：`cheatsheet/java_vs_python.md` 类型标注一节；`stage4_typing_testing/README.md` 第 1 节。
- 做：把 `stage1~3` 里任意 3 个函数的参数/返回值补全类型；跑 `mypy stage1_basics`（允许有报错，先看懂）。
- 重点：`list[int]`、`dict[str, Any]`、`X | None`、`Literal`、`TypedDict`、`Callable`。
- 坑：类型标注**运行时不做检查**，只是给工具和同事看的。

### Day 12 —— Protocol / Generic / TypedDict
- 读：`stage4_typing_testing/README.md` 第 2 节。
- 做：`parse_tool_call`（TypedDict + 手写校验）。
- 重点：Protocol ≈ Java interface（结构化子类型）；TypeVar ≈ 泛型；TypedDict 描述 JSON 形状。
- 加练：给 `ToolRegistry` 写一个 Protocol（第 6 周会用到）。

### Day 13 —— pydantic v2 数据契约
- 读：`stage4_typing_testing/README.md` 第 3 节。
- 做：`ClaimInput` 模型（`Field` 约束、`field_validator`、`extra="forbid"`）。
- 重点：`model_validate` / `model_dump`、`ValidationError.errors()`、与 dataclass 的分工。
- 项目对照：`models/` 下所有 pydantic 模型的写法。

### Day 14 —— 装饰器与重试
- 读：`stage4_typing_testing/README.md` 第 4 节。
- 做：`retry` 装饰器（`functools.wraps`、指数退避）。
- 重点：函数是一等对象、闭包捕获、`*args/**kwargs` 透传。
- 加练：把 `retry` 改成"只重试指定异常 + 打印第几次重试"。

### Day 15 —— pytest 与工程化 + 周复盘
- 读：`stage4_typing_testing/README.md` 第 5 节；`RESOURCES.md` 里 pytest 部分。
- 做：`extract_json`；然后给 `stage3` 的 `parse_amount` 补 5 个测试用例（写在新文件里）。
- 验：`pytest stage4_typing_testing -q`；`ruff check .`；`mypy stage4_typing_testing`。
- 重点：`parametrize`、`fixture`、`raises`、`tmp_path`、`monkeypatch`、`caplog`。
- 复盘：总结"什么样的函数最容易测试"。

---

## 第 4 周：并发、asyncio、HTTP

目标：能并发调 20 个模型/接口，且不雪崩。

### Day 16 —— 并发模型与 GIL
- 读：`stage5_async_http/README.md` 第 1 节。
- 做：用 `concurrent.futures.ThreadPoolExecutor` 跑 10 个 `time.sleep(0.1)`，计时。
- 重点：IO 密集用线程/协程，CPU 密集用多进程；GIL 的真实影响。
- 大数据对照：Spark 是进程级并行，Python 协程是单线程 IO 并发，别混。

### Day 17 —— 协程基础
- 读：`stage5_async_http/README.md` 第 2 节。
- 做：写 3 个 `async def`，用 `asyncio.run` 串行 vs 并发各跑一次并计时。
- 重点：`async def` 调用不执行、`await` 让出控制权、事件循环只能有一个。
- 坑：在协程里调用阻塞函数（`requests`、`time.sleep`）会卡死整个循环。

### Day 18 —— gather / 信号量 / 超时
- 读：`stage5_async_http/README.md` 第 3~4 节。
- 做：`gather_with_limit`、`with_timeout`。
- 验：`pytest stage5_async_http -q -k "limit or timeout"`。
- 重点：结果顺序、`Semaphore` 限流、`wait_for` 会取消任务、取消要清理。

### Day 19 —— 异步重试与 httpx
- 读：`stage5_async_http/README.md` 第 5~6 节。
- 做：`retry_async`；跑 `demo_http.py`（可选，需要网络）。
- 重点：指数退避 + 抖动、只重试 429/5xx、连接超时 vs 读超时、`AsyncClient` 复用。
- 项目对照：项目里调用外部系统的超时/重试配置。

### Day 20 —— 流式输出与周复盘
- 读：`stage5_async_http/README.md` 第 7 节（SSE / stream）。
- 做：把 `demo_http.py` 改成流式打印（`stream=True` 或 SSE 逐行读）。
- 复盘：画出"一次请求从 FastAPI 到模型再到前端"的时序，标出超时点。
- 加练：给并发函数加"最大并发 5 + 总超时 10s"的组合。

---

## 第 5 周：Agent 核心机制

目标：不依赖框架，手写一个能跑的 Agent Loop；理解框架帮你做了什么。

### Day 21 —— LLM API 与 messages
- 读：`stage6_agent/README.md` 第 1 节。
- 做：跑 `stage6_agent/capstone_mini_agent.py --dry-run`（不花钱，打印请求结构）。
- 重点：`system/user/assistant/tool` 四种角色、`tool_call_id` 的配对、temperature 与结构化输出。
- 项目对照：`config.py` 的模型路由、`agents/` 里的 prompt。

### Day 22 —— 工具 schema 与分发
- 读：`stage6_agent/README.md` 第 2 节。
- 做：`build_tool_schema`、`dispatch_tool_call`。
- 验：`pytest stage6_agent -q -k "schema or dispatch"`。
- 重点：JSON Schema、参数错误必须变成"工具结果"而不是让整个流程崩。
- 坑：模型给的 `arguments` 是字符串，可能是空串/带 markdown 围栏。

### Day 23 —— Agent Loop
- 读：`stage6_agent/README.md` 第 3 节。
- 做：`run_agent_loop`（用假 LLM 测试）。
- 验：`pytest stage6_agent -q -k loop`。
- 重点：终止条件、最大步数、消息顺序、工具结果格式。
- 加练：在循环里加日志，打印每轮的工具名与参数（截断到 200 字符）。

### Day 24 —— 上下文裁剪与结构化输出
- 读：`stage6_agent/README.md` 第 4~5 节。
- 做：`truncate_messages`；用 pydantic 解析模型最终答案。
- 重点：token 预算、保留 system + 最近消息、不要拆散 tool_call/tool 配对。
- 项目对照：`memory.py` 的会话记忆策略。

### Day 25 —— 综合演练
- 做：跑通 `capstone_mini_agent.py`（真实调用，设置 `--real`），观察完整 trace。
- 验：`pytest -q` 全绿。
- 复盘：不看代码画出 Agent Loop 流程图，标出 3 个可能失败的点。

---

## 第 6 周：项目实战

目标：把学到的迁移到 `claims-ai-agent`，能独立加一个工具并写测试。

### Day 26 —— 读配置与工具层
- 读：`config.py`、`settings.py`、`tools/` 下任意 2 个文件。
- 任务：画出"配置 → 模型客户端 → 工具注册"的依赖图。
- 产出：在 `PROGRESS.md` 写 10 行摘要，标出看不懂的符号（第二天解决）。

### Day 27 —— 读 Agent 编排
- 读：`agents/claim_agent.py`，找到：状态定义、节点函数、条件边、HITL 中断点。
- 任务：把 LangGraph 的节点对应到第 5 周手写的 Loop，列出框架多做了什么。
- 产出：一张对照表（手写 Loop vs LangGraph）。

### Day 28 —— 加一个工具 + 测试
- 任务：仿照 `tools/` 里现有工具，新增一个只读工具（例如"按保单号查历史理赔次数"的 mock）。
- 要求：pydantic 参数模型 + 错误返回 + 至少 2 个 pytest 用例（成功/参数非法）。
- 验：`pytest tests -q`。

### Day 29 —— 加健壮性
- 任务：给新工具或一次模型调用加：超时、重试、结构化日志（trace_id）。
- 要求：失败时返回可读错误，不让整个请求 500。
- 验：人为制造异常（mock 抛错），确认降级行为。

### Day 30 —— 复盘与输出
- 任务：写一篇 800 字笔记《Java 工程师学 Python 做 Agent 的 10 个坑》。
- 自测：完成 `README.md` 第 6 节的 6 条毕业标准。
- 下一步：读 `Fluent Python` 第 1/2/3/5/6/9 章（选读），或直接进入 LangGraph 深入。

---

## 进度落后怎么办

- 某天没做完：不要顺延打乱整周，周末补，或砍掉"加练"。
- 连续两天卡住：跳过练习，先看 `solutions.py`，然后**合上答案重写一遍**。
- 时间只有 30 分钟：只做当天的练习题，不读讲义。
- 第 3 周开始觉得吃力：正常。类型标注和测试是 Java 程序员的舒适区，撑过去就好。
