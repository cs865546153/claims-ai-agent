# Stage 3 · 类、异常、文件、配置、日志

> 目标：写出结构清晰、可配置、出错能排查的模块。
> 预计：5 天（PLAN.md Day 6~10）。

---

## 1. 类与对象

```python
class Claim:
    """理赔单。"""

    allowed_status = {"new", "reviewing", "approved", "rejected"}   # 类属性

    def __init__(self, claim_id: str, amount: float, status: str = "new") -> None:
        self.claim_id = claim_id        # 实例属性，必须带 self
        self.amount = amount
        self.status = status

    def __repr__(self) -> str:          # 调试用，≈ Java toString()
        return f"Claim(claim_id={self.claim_id!r}, amount={self.amount})"

    def to_dict(self) -> dict:
        return {"claim_id": self.claim_id, "amount": self.amount}
```

| Java | Python |
|---|---|
| `this` 隐式 | `self` 显式写在第一个参数 |
| `private String name;` | `self._name`（约定，不强制） |
| `getAmount()` | `@property def amount` |
| `toString()` | `__repr__` / `__str__` |
| 构造器重载 | 默认参数 / `@classmethod` 工厂 |
| `equals/hashCode` | `__eq__` / `__hash__` |
| `instanceof` | `isinstance` |

### 常用 dunder（双下划线方法）

| 方法 | 触发时机 | 用途 |
|---|---|---|
| `__init__` | `Claim(...)` | 初始化 |
| `__repr__` | `repr(x)`、打印、调试器 | 开发者可读 |
| `__str__` | `str(x)`、`print(x)` | 用户可读（缺省用 `__repr__`） |
| `__eq__` | `a == b` | 值相等 |
| `__hash__` | `hash(x)`、放进 set/dict | 可哈希 |
| `__len__` | `len(x)` | 长度 |
| `__iter__` | `for x in obj` | 可迭代 |
| `__enter__/__exit__` | `with obj:` | 上下文管理 |
| `__call__` | `obj()` | 让对象像函数 |

### property

```python
class Claim:
    def __init__(self, amount: float) -> None:
        self._amount = amount

    @property
    def amount(self) -> float:
        return self._amount

    @amount.setter
    def amount(self, value: float) -> None:
        if value < 0:
            raise ValueError("金额不能为负")
        self._amount = value
```

**Java 对照**：`@property` 让 `claim.amount` 像字段一样访问，但实际调用方法。适合"读多写少 + 需要校验/计算"的场景。

---

## 2. dataclass：数据类首选

```python
from dataclasses import dataclass, field

@dataclass
class Claim:
    claim_id: str
    amount: float
    status: str = "new"
    tags: list[str] = field(default_factory=list)   # 可变字段必须这样写
```

自动生成：`__init__`、`__repr__`、`__eq__`。

- `field(default_factory=list)`：每个实例创建**新的** list。直接写 `tags: list[str] = []` 会抛 `ValueError`（dataclass 会检测到）。
- `@dataclass(frozen=True)`：不可变（≈ Java `record`），可哈希，可做 dict 键。
- `__post_init__`：初始化后校验/派生字段。

### dataclass vs pydantic

| | dataclass | pydantic BaseModel |
|---|---|---|
| 运行时校验/类型转换 | 无 | 有 |
| 适用位置 | 内部数据、领域对象 | API 入参、配置、LLM 输出 |
| 性能 | 略高 | 略低（可接受） |
| 序列化 | `dataclasses.asdict` | `model_dump()` / `model_dump_json()` |

**经验**：边界（外部输入）用 pydantic，内部传参用 dataclass 或 pydantic 都行。

---

## 3. 继承、组合、Enum

```python
from enum import StrEnum

class ClaimStatus(StrEnum):
    NEW = "new"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    REJECTED = "rejected"
```

- `StrEnum` 的成员可以直接和字符串比较（`ClaimStatus.NEW == "new"`），也能被 JSON 序列化。
- 普通 `Enum` 更严格，适合纯内部状态。

**继承**：能用组合就别继承。Agent 项目里常见的是"策略/工具"用 `Protocol` 或函数注册表，而不是深层继承树。

```python
# 组合优于继承
class ClaimService:
    def __init__(self, repo: ClaimRepository, notifier: Notifier) -> None:
        self._repo = repo
        self._notifier = notifier
```

---

## 4. 异常

```python
class ClaimError(Exception):
    """业务异常基类。"""

class ClaimNotFound(ClaimError):
    pass

class ClaimValidationError(ClaimError):
    pass
```

```python
def parse_amount(raw: str | None) -> float:
    if not raw:
        raise ClaimValidationError("金额为空")
    try:
        value = float(raw.replace(",", ""))
    except ValueError as e:
        raise ClaimValidationError(f"非法金额: {raw!r}") from e   # 保留原始异常
    if value < 0:
        raise ClaimValidationError("金额不能为负")
    return value
```

| Java | Python |
|---|---|
| checked exception | 没有，全部 unchecked |
| `throw new X(msg, cause)` | `raise X(msg) from e` |
| `catch (A \| B e)` | `except (A, B) as e:` |
| `finally` | `finally` |
| try-with-resources | `with` |

**原则**

- 不要 `except Exception: pass`（吞异常 = 线上无法排查）。
- 只捕获你能处理的异常；捕获后要么恢复，要么加上下文再抛。
- 业务异常定义基类，Web 层统一映射成 HTTP 状态码。
- **工具函数**（Agent 的 tool）失败时，优先返回结构化错误而不是抛异常，让模型能继续决策。

---

## 5. 文件与 JSON

```python
from pathlib import Path

path = Path("data") / "claims.jsonl"     # / 运算符拼接路径
text = path.read_text(encoding="utf-8")  # 一次读完（小文件）
path.write_text("{}", encoding="utf-8")

with path.open(encoding="utf-8") as f:   # 逐行读（大文件）
    for line in f:
        ...
```

- **永远显式写 `encoding="utf-8"`**，否则 Windows 默认 GBK，跨平台必炸。
- `Path` 自带 `exists()`、`suffix`、`stem`、`parent`、`mkdir(parents=True, exist_ok=True)`。

```python
import json

data = json.loads(text)                          # str -> dict
text = json.dumps(data, ensure_ascii=False, indent=2)   # dict -> str，中文不转义

with path.open(encoding="utf-8") as f:
    data = json.load(f)                          # 从文件读
```

**JSONL**（每行一个 JSON）：大数据/日志/模型数据集常用格式。逐行处理，内存 O(1)。

```python
for line in path.open(encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    record = json.loads(line)
```

---

## 6. 上下文管理器（with）

```python
class Timer:
    def __init__(self) -> None:
        self.elapsed = 0.0

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.elapsed = time.perf_counter() - self._start
```

```python
with Timer() as t:
    do_something()
print(t.elapsed)
```

更简单的写法：

```python
from contextlib import contextmanager

@contextmanager
def timer():
    start = time.perf_counter()
    yield
    print(time.perf_counter() - start)
```

**用途**：文件、数据库连接、锁、临时目录、trace span、计时。

---

## 7. 日志

```python
import logging
import sys

logger = logging.getLogger(__name__)

def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    log = logging.getLogger(name)
    log.setLevel(level)
    log.propagate = False
    if not log.handlers:                     # 幂等，避免重复输出
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        log.addHandler(handler)
    return log
```

| 级别 | 用途 |
|---|---|
| DEBUG | 开发细节、prompt 全文（注意脱敏） |
| INFO | 关键流程、模型调用耗时/token |
| WARNING | 可恢复的异常、降级 |
| ERROR | 请求失败、需要人工介入 |
| CRITICAL | 服务不可用 |

**不要用 print 调试**：无法分级、无法关闭、无法采集、没有时间戳。

**日志纪律**

- 不打印密钥、完整身份证/手机号、完整 prompt（截断 + 脱敏）。
- 每条关键日志带 `trace_id`。
- 异常日志用 `logger.exception("...")` 自动带堆栈。

---

## 8. 配置

优先级：**环境变量 > `.env` 文件 > 代码默认值**。

```python
import os
from dotenv import load_dotenv

load_dotenv()                     # 只影响当前进程
api_key = os.getenv("DEEPSEEK_API_KEY")
if not api_key:
    raise RuntimeError("缺少 DEEPSEEK_API_KEY")
```

生产项目用 `pydantic-settings`（第 3 周会看到），好处是启动即校验、类型转换、IDE 补全。

> `.env` 永远加入 `.gitignore`；提交 `.env.example` 说明需要哪些变量。

---

## 9. 常见坑

1. **可变默认值**：`def f(tags=[])` / dataclass 里 `tags: list = []`。
2. **类属性被所有实例共享**：`class A: items = []`，改 `a.items` 会影响所有实例。
3. **`except` 顺序**：子类异常必须写在父类前面，否则永远进不去。
4. **`finally` 里有 return**：会吞掉异常/覆盖返回值，别这么写。
5. **JSON 中文转义**：`json.dumps` 默认 `ensure_ascii=True`，中文会变成 `\uXXXX`。
6. **文件编码**：不写 `encoding` 在 Windows 上默认 GBK。
7. **`logging` 重复输出**：多次 `addHandler` 或 `propagate=True`。
8. **`datetime` 时区**：用 `datetime.now(timezone.utc)`，不要用无时区的 `now()`。

---

## 10. 本阶段练习

| 内容 | 练什么 | Agent 场景 |
|---|---|---|
| `Claim` dataclass | 类、property、`__post_init__` | 领域对象 |
| `parse_amount` | 自定义异常、异常链 | 工具参数校验 |
| `load_json` | pathlib、json、默认值 | 读取配置 |
| `read_jsonl` | 逐行读、错误定位 | 批量评测数据 |
| `Timer` | 上下文管理器 | 记录模型耗时 |
| `setup_logger` | logging、幂等 | 可观测性 |

验收：

```powershell
.\.venv\Scripts\python.exe -m pytest stage3_oop_errors -q
```

**自检问题**

1. `field(default_factory=list)` 解决了什么问题？
2. `raise X from e` 和 `raise X` 有什么区别？
3. `with` 的 `__exit__` 返回 `True` 会发生什么？
4. 为什么日志不要用 print？生产环境需要哪些字段？
