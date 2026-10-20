# Java → Python 速查表（Agent 开发视角）

> 用法：第 1 周每天扫一遍，第 2 周起当字典查。
> 只收录"Java 程序员容易踩坑"和"Agent 开发天天用"的部分。

---

## 1. 运行与环境

| 场景 | Java | Python |
|---|---|---|
| 编译 | `javac Main.java` | 无编译，直接解释执行 |
| 运行 | `java Main` | `python main.py` |
| 入口 | `public static void main` | `if __name__ == "__main__":` |
| 依赖 | Maven `pom.xml` | `requirements.txt` / `pyproject.toml` |
| 虚拟环境 | 无（JVM 全局） | `python -m venv .venv` |
| 包管理 | `mvn install` | `pip install -r requirements.txt` |
| REPL | `jshell` | `python`（交互式） |
| 格式化 | Spotless / google-java-format | `ruff format` |
| 静态检查 | SpotBugs / Checkstyle | `ruff check` + `mypy` |
| 测试 | JUnit | `pytest` |

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest -q
```

---

## 2. 语法对照（最容易出错的部分）

| 主题 | Java | Python |
|---|---|---|
| 语句结束 | `;` | 换行（不需要分号） |
| 代码块 | `{}` | 缩进（4 空格，**混用 Tab 会报错**） |
| 变量声明 | `String name = "a";` | `name = "a"`（无类型、无声明） |
| 常量 | `final` | 约定全大写 `MAX_SIZE = 10`（语言不强制） |
| 空值 | `null` | `None` |
| 逻辑 | `&& \|\| !` | `and or not` |
| 三元 | `a > b ? a : b` | `a if a > b else b` |
| 自增 | `i++` | **没有** `++`，写 `i += 1` |
| 类型转换 | `(int) x` | `int(x)`（可能抛 `ValueError`） |
| 类型判断 | `x instanceof Foo` | `isinstance(x, Foo)` |
| 字符串转数字 | `Integer.parseInt(s)` | `int(s)` |
| 打印 | `System.out.println(x)` | `print(x)` |
| 注释 | `//` `/* */` | 相同，另有三引号文档字符串 `"""..."""` |

### `==` 的语义完全相反（重点）

```java
// Java
String a = new String("x");
String b = new String("x");
a == b        // false（比引用）
a.equals(b)   // true（比值）
```

```python
# Python
a = "x"
b = "".join(["x"])
a == b        # True（比值）
a is b        # 可能 False（比身份，等价于 Java 的 ==）
```

**规则**：比较值一律用 `==`；只有和 `None` / `True` / `False` 比较时用 `is`。

```python
if value is None:      # 正确
if value == None:      # 能跑，但不地道
```

---

## 3. 类型系统

| 主题 | Java | Python |
|---|---|---|
| 类型检查 | 编译期强制 | 运行时动态；标注**不强制** |
| 基本类型 | `int` `long` `double` `boolean` | 全是对象：`int` `float` `bool`（`int` 任意精度） |
| 泛型 | `List<String>` | `list[str]`（仅标注，运行时是 `list`） |
| 接口 | `interface` | `Protocol`（结构化子类型，不需要显式实现） |
| 联合类型 | `Object` / sealed | `str \| None` |
| 枚举 | `enum` | `enum.Enum` / `StrEnum` |
| 空安全 | `Optional<T>` | `X \| None`（同样只是标注） |
| 数据类 | Lombok `@Data` / record | `@dataclass` / `pydantic.BaseModel` |

```python
from typing import Any, Literal, TypedDict

def parse(amount: float, currency: Literal["CNY", "USD"] = "CNY") -> dict[str, Any]:
    ...

class ToolCall(TypedDict):
    id: str
    name: str
    arguments: dict[str, Any]
```

> 标注的价值：IDE 补全、mypy 检查、pydantic 运行时校验。**不要指望它阻止传错类型**。

---

## 4. 字符串

```java
String s = "  Hello  ";
s = s.trim().toLowerCase();
String[] parts = s.split(",");
String joined = String.join("-", list);
String msg = "用户 " + name + " 金额 " + amount;
```

```python
s = "  Hello  "
s = s.strip().lower()
parts = s.split(",")              # 返回 list
joined = "-".join(items)          # 注意是 str.join(iterable)
msg = f"用户 {name} 金额 {amount}"  # f-string，最常用
```

| 操作 | Java | Python |
|---|---|---|
| 长度 | `s.length()` | `len(s)` |
| 拼接 | `+` / `StringBuilder` | `+`（少量）/ `"".join(list)`（大量） |
| 格式化 | `String.format("%s", x)` | `f"{x}"` |
| 替换 | `s.replace(a, b)` | `s.replace(a, b)` |
| 包含 | `s.contains(x)` | `x in s` |
| 正则 | `Pattern.compile` | `re.findall` / `re.sub` |
| 多行 | 文本块 `"""` | 三引号 `"""..."""` |
| 反转 | `new StringBuilder(s).reverse()` | `s[::-1]` |

常用方法：`strip()`、`lower()`、`upper()`、`startswith()`、`endswith()`、`splitlines()`、`split()`（无参数按任意空白切分并去空串）。

---

## 5. 集合

| Java | Python | 说明 |
|---|---|---|
| `ArrayList<T>` | `list` | 有序、可变、可重复 |
| `HashMap<K,V>` | `dict` | 3.7+ 保持插入顺序 |
| `HashSet<T>` | `set` | 无序、去重、元素必须可哈希 |
| `ArrayDeque<T>` | `collections.deque` | 两端 O(1) |
| `PriorityQueue<T>` | `heapq` | 小顶堆 |
| `LinkedList` | 很少用；用 `list`/`deque` | |
| `Collections.frequency` | `collections.Counter` | 词频统计神器 |

```python
# 创建
nums = [1, 2, 3]
user = {"id": "C-1", "amount": 100}
tags = {"vip", "high-risk"}

# 访问
nums[0]          # 第一个
nums[-1]         # 最后一个（Java 没有）
user["id"]       # 键不存在 -> KeyError（不是返回 null）
user.get("x")    # 键不存在 -> None
user.get("x", 0) # 默认值

# 遍历
for i, x in enumerate(nums):
    print(i, x)

for key, value in user.items():
    print(key, value)
```

**关键差异**

| 坑 | 说明 |
|---|---|
| `dict[key]` 不存在 | 抛 `KeyError`，不是返回 `null`。用 `.get()` |
| 可变对象做默认参数 | `def f(x, acc=[])` 的 `acc` 在所有调用间共享（见第 6 节） |
| 赋值不是拷贝 | `b = a` 后改 `b` 会影响 `a` |
| 浅拷贝 | `b = a.copy()`：内层还是共享；用 `copy.deepcopy` 彻底隔离 |
| `list` 不能做 dict 的键 | 因为不可哈希；`tuple` 可以 |
| 遍历时增删元素 | 会跳元素/报错，先复制或倒序 |

---

## 6. 函数

```java
// Java
public static int add(int a, int b) { return a + b; }
list.stream().filter(x -> x > 0).map(x -> x * 2).collect(toList());
```

```python
# Python
def add(a: int, b: int = 0) -> int:
    return a + b

result = [x * 2 for x in nums if x > 0]     # 推导式
```

| 主题 | Java | Python |
|---|---|---|
| 默认参数 | 不支持（靠重载） | `def f(a, b=1)` |
| 可变参数 | `int... nums` | `*args` |
| 关键字参数 | 无 | `**kwargs`、调用时 `f(b=2, a=1)` |
| 仅关键字参数 | 无 | `def f(*, timeout: float)` |
| 仅位置参数 | 无 | `def f(a, /)` |
| 函数作为值 | 方法引用 / Lambda | 直接传函数名（一等对象） |
| 匿名函数 | `x -> x * 2` | `lambda x: x * 2` |
| 重载 | 支持 | **不支持**，用默认参数/`singledispatch` |
| 柯里化/闭包 | Lambda + effectively final | 原生闭包，用 `nonlocal` 修改外层变量 |

### 可变默认值陷阱（面试高频）

```python
def add_item(item, bucket=[]):   # 错误！bucket 在函数定义时创建一次
    bucket.append(item)
    return bucket

add_item(1)   # [1]
add_item(2)   # [1, 2]  ← 不是 [2]

def add_item(item, bucket=None):  # 正确
    if bucket is None:
        bucket = []
    bucket.append(item)
    return bucket
```

### 闭包

```python
def make_counter(start: int = 0):
    count = start
    def next_value() -> int:
        nonlocal count        # 没有 nonlocal 只能读，不能改
        count += 1
        return count
    return next_value

c = make_counter(10)
c()  # 11
c()  # 12
```

---

## 7. 类与对象

| 主题 | Java | Python |
|---|---|---|
| 构造器 | `ClassName(...)` | `__init__(self, ...)` |
| this | 隐式 | 显式 `self`（第一个参数） |
| 私有 | `private` | 约定 `_name`（强私有 `__name` 会改名） |
| getter/setter | `getX()` / `setX()` | `@property` / `@x.setter` |
| toString | `toString()` | `__repr__`（调试）/ `__str__`（展示） |
| equals | `equals()` | `__eq__` |
| hashCode | `hashCode()` | `__hash__` |
| 接口 | `interface` | `abc.ABC` / `Protocol` |
| 继承 | `extends` | `class Child(Parent):` |
| 多继承 | 不支持 | 支持（MRO 解析顺序，慎用） |
| 数据类 | Lombok `@Data` | `@dataclass` |
| 不可变对象 | `record` / final 字段 | `@dataclass(frozen=True)` |

```python
from dataclasses import dataclass, field

@dataclass
class Claim:
    claim_id: str
    amount: float
    status: str = "new"
    tags: list[str] = field(default_factory=list)   # 可变字段必须这样写

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError("amount 不能为负")

    @property
    def is_high_risk(self) -> bool:
        return self.amount >= 10_000

    def __repr__(self) -> str:
        return f"Claim(id={self.claim_id!r}, amount={self.amount})"
```

**不要为了 OOP 而 OOP**：Agent 项目里大量代码是"函数 + 数据类"，不是层层继承。

---

## 8. 异常

| 主题 | Java | Python |
|---|---|---|
| 受检异常 | `throws IOException` | **不存在**，全部 unchecked |
| 捕获 | `catch (IOException e)` | `except ValueError as e:` |
| 多类型 | `catch (A \| B e)` | `except (A, B) as e:` |
| 兜底 | `catch (Exception e)` | `except Exception as e:` |
| 抛出 | `throw new X()` | `raise X()` |
| 异常链 | `new X(msg, cause)` | `raise X(msg) from e` |
| finally | `finally` | `finally`（或 `with`） |
| try-with-resources | `try (var f = ...)` | `with open(...) as f:` |
| 断言 | `assert` | `assert`（生产环境可能被 `-O` 关掉） |

```python
class ClaimError(Exception):
    """业务异常基类。"""

class ClaimNotFound(ClaimError):
    pass

def parse_amount(raw: str | None) -> float:
    if not raw:
        raise ClaimError("amount 为空")
    try:
        return float(raw.replace(",", ""))
    except ValueError as e:
        raise ClaimError(f"非法金额: {raw!r}") from e   # 保留原始堆栈
```

**原则**

- 只捕获你能处理的异常，不要 `except Exception: pass`。
- 业务异常定义自己的基类，方便上层统一处理。
- 工具函数失败时，很多时候**返回错误对象**比抛异常更合适（Agent Loop 需要继续跑）。

---

## 9. 文件 / JSON / 配置

| 操作 | Java | Python |
|---|---|---|
| 读文本 | `Files.readString(path)` | `Path(p).read_text(encoding="utf-8")` |
| 写文本 | `Files.writeString` | `Path(p).write_text(s, encoding="utf-8")` |
| 逐行读 | `BufferedReader` | `for line in f:`（自动按行，内存友好） |
| 路径 | `Paths.get` | `pathlib.Path` |
| JSON | Jackson / Gson | 内置 `json` |
| YAML | SnakeYAML | `PyYAML`（需安装） |
| 环境变量 | `System.getenv` | `os.environ` / `os.getenv` |
| 配置类 | Spring `@ConfigurationProperties` | `pydantic-settings` |

```python
import json
from pathlib import Path

path = Path("data/claims.jsonl")
for line in path.open(encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    record = json.loads(line)

payload = {"name": "张三", "amount": 100}
text = json.dumps(payload, ensure_ascii=False, indent=2)   # 中文不转义
```

**Agent 开发常做**：读 `.env` → pydantic settings → 注入模型客户端。

```python
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("DEEPSEEK_API_KEY")
if not api_key:
    raise RuntimeError("缺少 DEEPSEEK_API_KEY")
```

---

## 10. 并发

| 场景 | Java | Python |
|---|---|---|
| 线程 | `Thread` / `ExecutorService` | `threading` / `ThreadPoolExecutor` |
| 线程安全 | `synchronized` / `Lock` | `threading.Lock`（但优先用队列/不可变数据） |
| 异步 | `CompletableFuture` | `asyncio` + `async/await` |
| 并行流 | `parallelStream()` | `multiprocessing`（CPU 密集） |
| 定时 | `ScheduledExecutorService` | `asyncio.sleep` / `loop.call_later` |
| 超时 | `future.get(timeout)` | `asyncio.wait_for` / `httpx.Timeout` |

```python
import asyncio

async def fetch(client, url: str) -> dict:
    resp = await client.get(url)
    resp.raise_for_status()
    return resp.json()

async def main(urls: list[str]) -> list[dict]:
    sem = asyncio.Semaphore(5)          # 最多 5 个并发
    async with httpx.AsyncClient(timeout=10) as client:
        async def one(url: str) -> dict:
            async with sem:
                return await fetch(client, url)
        return await asyncio.gather(*(one(u) for u in urls))

asyncio.run(main(urls))
```

**关键认知**

- Python 有 GIL：多线程适合 IO，不适合 CPU 计算。CPU 密集用 `multiprocessing`。
- `asyncio` 是**单线程事件循环**：一个协程里写 `time.sleep()` 或 `requests.get()` 会阻塞所有协程。
- 同步库里没有 `async` 版本时，用 `await asyncio.to_thread(func, ...)`。
- `gather` 默认"一个失败就整体失败"，需要 `return_exceptions=True` 收集全部结果。

---

## 11. 工程与测试

| 主题 | Java | Python |
|---|---|---|
| 测试框架 | JUnit 5 | pytest |
| 断言 | `assertEquals(a, b)` | `assert a == b` |
| 异常断言 | `assertThrows` | `with pytest.raises(ValueError):` |
| 参数化 | `@ParameterizedTest` | `@pytest.mark.parametrize` |
| 前置/后置 | `@BeforeEach` | `@pytest.fixture` / `yield` |
| Mock | Mockito | `unittest.mock` / `monkeypatch` |
| 覆盖率 | JaCoCo | `pytest --cov` |
| 测试文件 | `*Test.java` | `test_*.py` 或 `*_test.py` |
| 测试函数 | `void shouldX()` | `def test_x():` |

```python
import pytest

@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1,234.5", 1234.5), ("¥ 12", 12.0)],
)
def test_parse_amount(raw: str, expected: float) -> None:
    assert parse_amount(raw) == expected

def test_parse_amount_invalid() -> None:
    with pytest.raises(ClaimError):
        parse_amount("abc")

def test_load_json_missing(tmp_path):
    assert load_json(tmp_path / "nope.json") == {}
```

---

## 12. 十条"像 Python 程序员"的惯用法

1. **用 `for x in items`，不要 `for i in range(len(items))`**；需要下标用 `enumerate`。
2. **用推导式代替手写循环 append**：`[f(x) for x in xs if cond(x)]`。
3. **用 `dict.get(k, default)` 代替 `if k in d`**。
4. **用 `with` 管理资源**，不要手动 `close()`。
5. **用 `f-string` 拼字符串**，不要 `+` 或 `%`。
6. **用 `pathlib.Path`**，不要字符串拼 `"a/" + name`。
7. **函数短小、参数用关键字**：`call_model(prompt, temperature=0)` 比位置参数可读。
8. **异常优先于返回错误码**；但工具层可以把异常转成结构化错误返回。
9. **不要用 `print` 调试**，用 `logging`（可级别、可格式化、可采集）。
10. **类型标注 + pydantic**：边界（API、配置、LLM 输出）一定要校验。

---

## 13. 一页速记

```python
# 变量与类型
x: int = 1
name = "agent"
items: list[str] = []
mapping: dict[str, int] = {}
maybe: str | None = None

# 条件 / 循环
if x > 0 and name:
    ...
elif x == 0:
    ...
else:
    ...

for i, item in enumerate(items):
    ...

for key, value in mapping.items():
    ...

# 推导式
squares = [n * n for n in range(10) if n % 2 == 0]
by_id = {c.claim_id: c for c in claims}
unique = {tag for c in claims for tag in c.tags}

# 函数
def f(a: int, b: int = 0, *args, **kwargs) -> int:
    return a + b

# 类
@dataclass
class A:
    x: int = 0

# 异常
try:
    ...
except ValueError as e:
    ...
finally:
    ...

# 文件
Path("a.json").write_text("{}", encoding="utf-8")

# 异步
async def f() -> None:
    await asyncio.sleep(1)
```
