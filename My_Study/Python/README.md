# Python 6 周学习计划（Java / 大数据 → AI Agent 应用开发）

> 目标不是"学完 Python"，而是 **6 周后能独立读写 `claims-ai-agent` 项目，并能从零手写一个带工具调用、异步并发、可测试的 Agent 应用**。
>
> 原则：不背语法书。每个知识点都必须落到 Agent 开发的真实场景里（JSON、工具调用、重试、超时、结构化输出、上下文裁剪）。

---

## 1. 你的起点与补齐路径

| 能力 | 你已经具备（Java / 大数据） | Python 需要补的重点 |
|---|---|---|
| 类型系统 | 静态类型、泛型、接口 | 动态类型 + 类型标注（typing / mypy），运行时校验（pydantic） |
| 集合 | List/Map/Set/Stream | list/dict/set、推导式、生成器（惰性、省内存） |
| 函数 | 方法、Lambda、函数式接口 | 一等函数、闭包、装饰器、`*args/**kwargs` |
| 面向对象 | class / interface / 继承 | 鸭子类型、dataclass、`__dunder__`、Protocol |
| 异常 | checked exception | 全部 unchecked、EAFP 风格、`raise ... from e` |
| 并发 | 线程池 / CompletableFuture | GIL、`asyncio`、`await`、`gather`、信号量 |
| 工程 | Maven/Gradle、JUnit | venv/pip、pyproject、pytest、ruff、mypy |
| 数据 | Spark DataFrame / SQL | dict/JSON、pydantic 模型、JSONL、文件流 |

**不用学的**：JVM 调优、Python 2 语法、GUI、爬虫工程师那套、算法题海。

---

## 2. 目录结构

```
My_Study/Python/
├── README.md                 ← 你在这里
├── PLAN.md                   ← 30 天逐日计划（每天 60~90 分钟）
├── RESOURCES.md              ← 精选学习资料（按优先级）
├── PROGRESS.md               ← 打卡表（做完打勾）
├── pyproject.toml            ← pytest / ruff 配置
├── requirements.txt
├── .gitignore
├── cheatsheet/
│   ├── java_vs_python.md     ← Java 程序员的语法对照表（先读这个）
│   └── agent_dev_snippets.md ← Agent 开发常用代码片段（当模板抄）
├── stage1_basics/            ← 语法地基：字符串、判断、循环、真假值
├── stage2_structures/        ← 数据结构与函数：dict/list、推导式、闭包、生成器
├── stage3_oop_errors/        ← 类、dataclass、异常、文件、配置、日志
├── stage4_typing_testing/    ← 类型标注、pydantic、装饰器、pytest
├── stage5_async_http/        ← 并发、asyncio、httpx、超时与重试
└── stage6_agent/             ← Agent 核心：工具 schema、工具分发、Agent Loop、上下文裁剪
```

每个 `stageN_*` 目录**至少**包含 4 个文件（stage5/stage6 还有演示脚本）：

| 文件 | 用途 |
|---|---|
| `README.md` | 讲义：知识点 + Java 对照 + 常见坑（**先读**） |
| `exercises.py` | 练习题：把 `raise NotImplementedError` 换成你的代码（**只改这个文件**） |
| `test_exercises.py` | 自动判分，不要改 |
| `solutions.py` | 参考答案，卡住 20 分钟再看 |

---

## 3. 环境准备（已为你创建好）

本目录下已经有一个独立虚拟环境 `.venv`（Python 3.15），并安装了
`pytest / pydantic / httpx / openai / python-dotenv / ruff / mypy / rich`。

### 方式 A：不激活，直接用解释器（推荐，最省事）

```powershell
cd G:\Workspace\claims-ai-agent\My_Study\Python
.\.venv\Scripts\python.exe -m pytest stage1_basics -q
.\.venv\Scripts\python.exe stage1_basics\exercises.py
```

### 方式 B：激活虚拟环境

```powershell
cd G:\Workspace\claims-ai-agent\My_Study\Python
.\.venv\Scripts\Activate.ps1
python -m pytest -q
```

如果提示"禁止运行脚本"，执行一次：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### 如果环境坏了，重建

```powershell
cd G:\Workspace\claims-ai-agent\My_Study\Python
Remove-Item -Recurse -Force .venv
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

> 不要复用项目根目录的 `.venv-py314` / `.venv-deep`：它们指向已不存在的 Python 3.14，已经损坏。

---

## 4. 每天怎么练（核心循环）

1. **读**：`stageN/README.md` 对应小节（15~20 分钟，不要逐字背）。
2. **做**：打开 `exercises.py`，逐个实现。先写"能跑通"的版本，再想优化。
3. **验**：`python -m pytest stageN -q`，红了看断言信息，不要立刻看答案。
4. **对**：卡住 20 分钟再看 `solutions.py`，重点看"为什么这样写"，不是"抄一遍"。
5. **记**：在 `PROGRESS.md` 写 3 行：今天学了什么 / 踩了什么坑 / Java 里对应什么。
6. **回项目**：按 `PLAN.md` 当天的"项目对照"去 `claims-ai-agent` 里找真实用法。

判分命令速查：

```powershell
python -m pytest -q                      # 全部
python -m pytest stage1_basics -q        # 单个阶段
python -m pytest stage1_basics -q -x     # 第一个失败就停
python -m pytest stage1_basics -q -k fizzbuzz   # 只跑某个函数
python -m pytest --cov=stage6_agent --cov-report=term-missing   # 覆盖率（第 4 周）
```

---

## 5. 六周路线（详细日程见 PLAN.md）

| 周 | 主题 | 学完能做什么 | 对应项目代码 |
|---|---|---|---|
| 1 | 语法地基 + 数据结构/函数 | 读写普通 Python 脚本、处理 JSON 数据 | `config.py`、`tools/` 里的纯函数 |
| 2 | 类 / 异常 / 文件 / 配置 / 日志 | 写可维护的模块、解析配置文件、打日志 | `settings.py`、`monitoring.py` |
| 3 | 类型标注 / pydantic / 装饰器 / pytest | 定义数据契约、写单元测试、做静态检查 | `models/`、`tests/` |
| 4 | 并发 / asyncio / httpx | 并发调模型/接口、超时、重试、限流 | `tools/` 中的外部调用 |
| 5 | Agent 核心机制 | 手写 tool schema、工具分发、Agent Loop | `agents/claim_agent.py`、`claims_agent.py` |
| 6 | 项目实战 | 读懂并改造真实项目、加工具、加测试 | `app.py`、`agents/`、`tools/` |

---

## 6. 毕业验收标准（6 周后自测）

不看资料，能做到以下 6 条，就可以开始做业务 Agent 了：

- [ ] 能解释 `list` / `dict` / `set` 的底层结构与适用场景，能说清可变对象作为默认参数的坑。
- [ ] 能写出带类型标注的函数，并用 `pydantic` 定义请求/响应模型和校验规则。
- [ ] 能写 `try/except/finally` + 自定义异常，并用 `logging` 记录带上下文的日志。
- [ ] 能用 `asyncio.gather` + `Semaphore` + 超时，并发调用 20 个接口而不打爆下游。
- [ ] 能手写一个 Agent Loop：模型返回 `tool_calls` → 执行工具 → 把结果塞回 messages → 直到模型给出最终答案。
- [ ] 能给上面的 Loop 写 pytest 测试（用假 LLM，不花钱、不联网）。

---

## 7. 与 `claims-ai-agent` 项目的对接顺序

第 5~6 周按这个顺序读代码（先看结构，不抠细节）：

1. `config.py` / `settings.py` —— 配置、环境变量、模型路由。
2. `tools/` —— 工具如何定义、参数如何校验、错误如何返回。
3. `agents/claim_agent.py` —— 状态机 / 图编排、节点职责。
4. `claims_agent.py` —— 对外入口、流式输出、会话管理。
5. `app.py` —— FastAPI 路由、依赖注入、异常处理。
6. `tests/` —— 看别人怎么用假对象替代真实 LLM。

> 读的时候只问三个问题：**状态在哪？边界在哪？失败会怎样？**

> 你之前写的 `My_Study/day1_hello.py` ~ `day6_parallel_hitl.py` 不要删。第 5 周学完 Agent Loop 后回头重读，会发现它们分别对应：模型调用、JSON、工具、循环、图编排、并行与人工介入。

---

## 8. 常见问题

**Q：中文输出乱码？**
源码统一用 UTF-8。Python 3.15 默认就是 UTF-8 模式，直接运行时通常正常；
如果通过管道/重定向输出乱码（例如 `python x.py | more`），在 PowerShell 里执行：

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
```

或者直接开 Windows Terminal（默认 UTF-8）。

**Q：pip 太慢？**
本环境已配清华镜像安装。以后自己装包可以加：

```powershell
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple 包名
```

**Q：要不要学完 Python 再学 Agent？**
不要。第 5 周就开始写 Agent Loop，语法不够用再回头补，效率最高。

**Q：要不要刷算法题？**
每天最多 1 道（LeetCode 简单/中等），目的是熟悉语法，不是准备面试。优先做字符串、哈希表、双指针。

**Q：`solutions.py` 和我的写法不一样，谁对？**
能过测试、可读、符合团队风格就是对。Python 讲究"一种显然的做法"，但不必强求一致。

---

## 9. 学习资料

见 [RESOURCES.md](RESOURCES.md)。优先顺序：
**官方教程 → 本目录讲义/速查表 → Fluent Python（选读）→ 项目源码**。
