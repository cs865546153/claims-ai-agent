# Stage 4 · 类型标注、pydantic、装饰器、测试

> 目标：从"能跑"升级到"可维护、可测试、可静态检查"。
> 预计：5 天（PLAN.md Day 11~15）。

---

## 1. 类型标注（typing）

Python 的类型标注**运行时不检查**，价值在于：IDE 补全、mypy 静态检查、pydantic 运行时校验、给同事看。

```python
from typing import Any, Literal, TypedDict

def parse_amount(raw: str | None, *, strict: bool = False) -> float:
    ...

items: list[str] = []
mapping: dict[str, int] = {}
pair: tuple[str, int] = ("a", 1)
maybe: str | None = None
anything: Any = object()
mode: Literal["fast", "deep"] = "fast"
```

| 场景 | 写法 |
|---|---|
| 列表 | `list[int]` |
| 字典 | `dict[str, Any]` |
| 可空 | `str \| None` |
| 只读序列 | `Sequence[str]` |
| 可迭代 | `Iterable[str]` |
| 函数 | `Callable[[int], str]` |
| 任意键值 | `Mapping[str, object]` |
| 字面量 | `Literal["a", "b"]` |
| 固定键的 dict | `TypedDict` |
| 泛型 | `TypeVar` |

### TypedDict：描述 JSON 形状

```python
class ToolCall(TypedDict):
    id: str
    name: str
    arguments: dict[str, Any]
```

- 运行时就是普通 `dict`，没有校验。
- mypy 能检查键名和类型。
- 适合描述"外部传进来的 JSON"。

### Protocol：结构化接口

```python
from typing import Protocol

class LLMClient(Protocol):
    def chat(self, messages: list[dict]) -> dict:
        ...

def run(client: LLMClient) -> None:
    ...
```

任何有 `chat` 方法的对象都满足 `LLMClient`，**不需要显式继承**（≈ Java 的接口 + 鸭子类型）。这是 Agent 项目里做依赖注入/测试替身的关键。

### mypy

```powershell
.\.venv\Scripts\python.exe -m mypy stage4_typing_testing
```

- 先让新代码通过，不要一上来给整个项目加严格模式。
- `# type: ignore[code]` 要写具体错误码，不要裸 `# type: ignore`。

---

## 2. pydantic v2

边界数据（HTTP 入参、配置、LLM 输出、工具参数）一律用 pydantic。

```python
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

class ClaimInput(BaseModel):
    model_config = ConfigDict(extra="forbid")     # 多余字段直接报错

    claim_id: str
    amount: float = Field(gt=0, le=1_000_000)
    reason: str = ""
    tags: list[str] = Field(default_factory=list)

    @field_validator("claim_id")
    @classmethod
    def validate_claim_id(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("claim_id 至少 3 个字符")
        return value

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, tags: list[str]) -> list[str]:
        result: list[str] = []
        for tag in tags:
            tag = tag.strip()
            if tag and tag not in result:
                result.append(tag)
        if len(result) > 5:
            raise ValueError("tags 最多 5 个")
        return result
```

```python
try:
    claim = ClaimInput.model_validate(payload)
except ValidationError as e:
    print(e.errors(include_url=False))     # 结构化错误，可直接返回给前端
```

| 方法 | 用途 |
|---|---|
| `Model(**data)` / `model_validate(data)` | 校验并构造 |
| `model_dump()` | 转 dict |
| `model_dump_json()` | 转 JSON 字符串 |
| `model_json_schema()` | 生成 JSON Schema（可直接给 LLM 当工具参数） |
| `model_copy(update={...})` | 复制并改字段 |

**坑**

- v1 的 `@validator` / `.dict()` / `.json()` 在 v2 里改名了：`@field_validator` / `.model_dump()` / `.model_dump_json()`。
- 默认会做类型转换（`"123"` -> `123`），要严格用 `StrictInt` 等。
- `field_validator` 默认 `mode="after"`，拿到的是已转换的值。

---

## 3. 装饰器

装饰器 = 接收函数、返回新函数的高阶函数。

```python
import functools
import time

def timed(func):
    @functools.wraps(func)                 # 保留原函数名/文档，必须写
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            print(f"{func.__name__} took {time.perf_counter() - start:.3f}s")
    return wrapper

@timed
def slow() -> None:
    time.sleep(0.1)
```

带参数的装饰器 = 三层函数：

```python
def retry(times: int = 3, delay: float = 0.0):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            ...
        return wrapper
    return decorator

@retry(times=3, delay=0.5)
def call_llm() -> str:
    ...
```

**用途**：重试、计时、日志、鉴权、缓存、限流、注册工具。

---

## 4. pytest

```python
import pytest

def test_add() -> None:
    assert add(1, 2) == 3

@pytest.mark.parametrize(("raw", "expected"), [("1", 1), ("2", 2)])
def test_parse(raw: str, expected: int) -> None:
    assert parse(raw) == expected

def test_invalid() -> None:
    with pytest.raises(ValueError, match="非法"):
        parse("x")
```

### 常用 fixture

| fixture | 用途 |
|---|---|
| `tmp_path` | 临时目录（自动清理），测文件读写 |
| `monkeypatch` | 临时改环境变量/属性/函数 |
| `capsys` | 捕获 stdout/stderr |
| `caplog` | 捕获日志 |
| 自定义 `@pytest.fixture` | 共享测试数据/客户端 |

```python
def test_api_key(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    assert load_settings().api_key.get_secret_value() == "test-key"

@pytest.fixture
def claim() -> Claim:
    return Claim("C-1", 100)

def test_claim(claim: Claim) -> None:
    assert claim.status == "new"
```

### 测试原则

- 一个测试只验证一件事，名字写清楚"什么条件下应该怎样"。
- 不测实现细节，测**行为**。
- 不依赖网络/真实 LLM：注入假客户端（第 6 周重点）。
- 覆盖：正常值、边界值（0、空、最大）、异常值。

```powershell
python -m pytest -q
python -m pytest --cov=stage4_typing_testing --cov-report=term-missing
```

---

## 5. 工程化三件套

```powershell
ruff check .          # 静态检查（未使用 import、未定义变量、风格）
ruff format .         # 格式化
mypy stage4_typing_testing   # 类型检查
pytest -q             # 测试
```

`pyproject.toml` 已经配好，直接跑即可。

---

## 6. 本阶段练习

| 内容 | 练什么 | Agent 场景 |
|---|---|---|
| `extract_json` | 正则、JSON、自定义异常 | 解析 LLM 返回的 JSON |
| `retry` | 闭包、装饰器、异常 | 调模型/接口失败重试 |
| `parse_tool_call` | TypedDict、手写校验 | 解析模型返回的工具调用 |
| `ClaimInput` | pydantic 校验器 | 工具参数/API 入参 |

验收：

```powershell
.\.venv\Scripts\python.exe -m pytest stage4_typing_testing -q
.\.venv\Scripts\python.exe -m ruff check stage4_typing_testing
```

**自检问题**

1. 类型标注在运行时会检查吗？那它的价值是什么？
2. `TypedDict` 和 pydantic 模型分别用在哪？
3. 装饰器里为什么必须写 `functools.wraps`？
4. `field_validator` 抛 `ValueError` 后，调用方看到的是什么异常？
