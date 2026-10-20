# 学习资料（按优先级，不要全看）

> 说明：资料在精不在多。每个阶段只挑 1 个主资料，其余当字典查。
> 标注：**必读** / 选读 / 查阅。

---

## 0. 先看这三份（本目录自带）

| 资料 | 说明 |
|---|---|
| [cheatsheet/java_vs_python.md](cheatsheet/java_vs_python.md) | **必读**。Java 视角的语法/惯用法对照，第 1 周反复看 |
| [cheatsheet/agent_dev_snippets.md](cheatsheet/agent_dev_snippets.md) | **必读**。Agent 开发常用片段，可直接抄进项目 |
| 各阶段 `stageN/README.md` | **必读**。只讲 Agent 开发用得到的部分，附常见坑 |

---

## 1. 官方文档（最权威，免费）

| 资料 | 用途 | 优先级 |
|---|---|---|
| [Python 官方中文教程](https://docs.python.org/zh-cn/3/tutorial/) | 第 1~2 周配套读物，语法查漏 | **必读**（挑第 3、4、5、7、8、9 章） |
| [Python 标准库参考](https://docs.python.org/zh-cn/3/library/index.html) | `pathlib` / `json` / `logging` / `asyncio` / `collections` | 查阅 |
| [PEP 8 风格指南](https://peps.python.org/pep-0008/) | 命名、缩进、import 顺序 | 选读（记住命名规范即可） |
| [PEP 484 类型提示](https://peps.python.org/pep-0484/) | 类型标注的由来 | 查阅 |
| [mypy 类型速查](https://mypy.readthedocs.io/en/stable/cheat_sheet_py3.html) | 一页看懂怎么写标注 | **必读**（第 3 周） |

---

## 2. 书（按需，不建议从头读到尾）

| 书 | 适合 | 怎么读 |
|---|---|---|
| **《Python Crash Course》**（Python 编程：从入门到实践） | 完全新手 | 只读第 1~11 章，2 周内翻完 |
| **《流畅的Python》第 2 版**（Fluent Python） | 有 Java 基础、想写地道 Python | **选读**第 1/2/3/5/6/9/17 章；第 4 周后当参考书 |
| **《Effective Python》第 2 版** | 想避免常见坑 | 每天读 2 条，重点看"可变默认值""闭包""生成器" |
| 《Python 工匠》 | 中文、工程实践 | 选读，讲可读性不错 |

> Java 程序员特别推荐 Fluent Python 的**第 6 章（一等函数）**和**第 17 章（迭代器/生成器）**，这两章是思维方式转换的关键。

---

## 3. 交互式练习 / 刷题

| 站点 | 用途 | 建议 |
|---|---|---|
| [Exercism Python Track](https://exercism.org/tracks/python) | 有导师点评的渐进练习 | 做完本目录 stage1~2 后，挑 10 道 easy |
| [Python Morsels](https://www.pythonmorsels.com/) | 每周小练习，讲得很细 | 选读，免费部分够用 |
| [LeetCode 中国站](https://leetcode.cn/problemset/) | 熟悉语法 | 每天最多 1 道，只做简单/中等 |
| [Codewars](https://www.codewars.com/) | 趣味小题 | 可选 |

**刷题原则**：目的是"把 Java 思维翻译成 Python"，不是准备面试。同一道题用 Java 和 Python 各写一遍，对比差异。

---

## 4. 分阶段专项资料

### 第 1~2 周：语言基础
- [Real Python: Python 3 入门](https://realpython.com/python-first-steps/)（英文，质量高）
- [廖雪峰 Python 教程](https://liaoxuefeng.com/books/python/introduction/index.html)（中文，适合快速过一遍）
- [Python Tutor](https://pythontutor.com/)：可视化执行，理解可变对象/引用非常有用

### 第 3 周：类型、pydantic、测试
- [pydantic v2 官方文档](https://docs.pydantic.dev/latest/) —— **必读** `Models`、`Fields`、`Validators`、`Conversion Table`
- [pytest 官方文档](https://docs.pytest.org/en/stable/) —— **必读** `fixtures`、`parametrize`、`monkeypatch`、`tmp_path`
- [Real Python: pytest 入门](https://realpython.com/pytest-python-testing/)
- [ruff 文档](https://docs.astral.sh/ruff/) —— 配置 `pyproject.toml` 即可
- [uv 文档](https://docs.astral.sh/uv/) —— 下一代包管理，可选（团队用再学）

### 第 4 周：异步与 HTTP
- [Python 官方 asyncio 教程](https://docs.python.org/zh-cn/3/library/asyncio.html) —— 看 `Task`、`gather`、`Semaphore`、`timeout`
- [Real Python: Async IO in Python](https://realpython.com/async-io-python/) —— 讲得最清楚的一篇
- [httpx 文档](https://www.python-httpx.org/async/) —— `AsyncClient`、`timeout`、`limits`
- [tenacity 文档](https://tenacity.readthedocs.io/) —— 生产级重试库（项目里可能已用）
- [HTTPX 超时说明](https://www.python-httpx.org/advanced/timeouts/)

### 第 5~6 周：Agent / LLM 应用
| 资料 | 说明 |
|---|---|
| [OpenAI Cookbook](https://cookbook.openai.com/) | **必读** Function calling、Structured outputs、Streaming 三篇 |
| [OpenAI Function Calling 指南](https://platform.openai.com/docs/guides/function-calling) | 工具 schema 的权威定义 |
| [DeepSeek API 文档](https://api-docs.deepseek.com/zh-cn/) | 本项目实际用的模型，看 `function calling` 和 `上下文缓存` |
| [Anthropic: Building Effective Agents](https://www.anthropic.com/research/building-effective-agents) | **必读**。讲清 workflow 与 agent 的边界，避免过度设计 |
| [LangGraph 文档](https://langchain-ai.github.io/langgraph/) | 项目在用。先看 `Graph API`、`Persistence`、`Human-in-the-loop` |
| [LangChain 文档](https://python.langchain.com/) | 当 API 字典查，不要从头学 |
| [FastAPI 教程](https://fastapi.tiangolo.com/zh/tutorial/) | 项目 Web 层，第 6 周按需查 |
| [12-Factor Agents](https://github.com/humanlayer/12-factor-agents) | 生产级 Agent 的设计原则，面试也能用 |
| [Prompt Engineering Guide](https://www.promptingguide.ai/zh) | 中文，prompt 基础 |

---

## 5. 视频（通勤/碎片时间）

- [Microsoft: Python for Beginners](https://www.youtube.com/playlist?list=PLlrxD0HtieHhS8VzuMCfQD4uJ9yne1mE6)（英文，48 集，每集 5 分钟）
- [Corey Schafer: Python Tutorials](https://www.youtube.com/playlist?list=PL-osiE80TeTt2d9bfVyTiXJA-UTHn6WwU)（英文，讲得系统）
- [莫烦 Python](https://mofanpy.com/)（中文，偏数据方向）
- B 站搜"Python 并发 asyncio"、"pydantic v2"（选播放量高的，注意版本）

---

## 6. 怎么用这些资料

1. **不要收藏吃灰**：每份资料只挑一个章节，当天用完就关。
2. **官方文档优先**：博客可能过时（尤其 pydantic v1/v2、LangChain 0.1/0.3 差异很大）。
3. **看不懂就先跳过**：第 1 周看不懂装饰器很正常，第 3 周回来看就懂了。
4. **以项目代码为准**：本项目锁定的版本在 `requirements.txt`，文档对不上时看源码。
5. **英文资料阅读技巧**：先看代码示例，再看段落；术语不用翻译（closure、decorator、coroutine 直接记）。
