# Stage 2 · 数据结构与函数

> 目标：能用 dict/list/生成器处理真实数据，理解 Python 的可变性与函数式写法。
> 预计：3 天（PLAN.md Day 3~5）。

---

## 1. list / tuple

```python
nums = [3, 1, 2]
nums.append(4)        # 尾部追加，均摊 O(1)
nums.insert(0, 0)     # 头部插入 O(n)，少用
nums.pop()            # 弹出尾部 O(1)
nums.pop(0)           # 弹出头部 O(n)
nums.sort()           # 原地排序，返回 None（坑！）
sorted(nums)          # 返回新列表

point = (1, 2)        # tuple：不可变，可做 dict 的键
x, y = point          # 解包
```

| 操作 | list | tuple |
|---|---|---|
| 可变 | 是 | 否 |
| 可哈希（能当 dict key） | 否 | 是（元素都可哈希时） |
| 用途 | 有序集合 | 固定结构、函数返回多值 |

**Java 对照**：`list` ≈ `ArrayList`，`tuple` ≈ 不可变的 `record` / `Pair`。

---

## 2. dict / set

```python
claim = {"id": "C-1", "amount": 100}
claim["status"] = "new"          # 新增/覆盖
claim.get("missing")             # None（不抛异常）
claim.get("missing", 0)          # 默认值
"id" in claim                    # 判断键
claim.keys() / .values() / .items()

for key, value in claim.items():
    ...

del claim["status"]
claim.pop("status", None)        # 安全删除
```

- 3.7+ **保持插入顺序**（Java 的 `HashMap` 不保证，`LinkedHashMap` 才保证）。
- 键必须可哈希：`str` / `int` / `tuple` 可以，`list` / `dict` 不行。
- 查找/插入平均 O(1)。

```python
tags = {"vip", "fraud"}
tags.add("manual-review")
tags.discard("vip")       # 不存在也不报错
a | b                     # 并集
a & b                     # 交集
a - b                     # 差集
```

**计数用 `Counter`**：

```python
from collections import Counter
Counter(["a", "b", "a"]).most_common(1)   # [('a', 2)]
```

---

## 3. 可变性与拷贝（最大的坑）

```python
a = [1, 2]
b = a            # 不是拷贝！b 和 a 指向同一个对象
b.append(3)
print(a)         # [1, 2, 3]

c = a.copy()     # 浅拷贝：只复制第一层
d = a[:]         # 同样浅拷贝
import copy
e = copy.deepcopy(a)   # 深拷贝：递归复制
```

```python
nested = {"a": [1, 2]}
shallow = nested.copy()
shallow["a"].append(3)
print(nested)    # {'a': [1, 2, 3]}  ← 内层还是共享
```

**规则**

- 函数**不要修改传入的 list/dict**，要么返回新对象，要么在文档里写清楚。
- 需要"合并配置"时用深拷贝，避免污染默认配置。
- 不可变对象（`int`、`str`、`tuple`、`frozenset`）随便传。

---

## 4. 切片与解包

```python
xs = [0, 1, 2, 3, 4]

xs[1:3]      # [1, 2]        左闭右开
xs[:2]       # [0, 1]
xs[2:]       # [2, 3, 4]
xs[-2:]      # [3, 4]        最后两个
xs[::-1]     # 反转
xs[::2]      # 步长 2
```

```python
first, *rest = [1, 2, 3]          # first=1, rest=[2, 3]
a, b = b, a                       # 交换，不需要临时变量

def f(**kwargs):
    print(kwargs)

config = {"timeout": 10}
f(**config)                       # 解包成关键字参数

merged = {**defaults, **overrides}    # 浅合并，后者优先（常用）
```

---

## 5. 推导式（对照 Java Stream）

```java
// Java
List<Integer> squares = nums.stream()
    .filter(x -> x % 2 == 0)
    .map(x -> x * x)
    .collect(Collectors.toList());
```

```python
# Python
squares = [x * x for x in nums if x % 2 == 0]
```

| 形式 | 写法 | 结果 |
|---|---|---|
| 列表推导 | `[f(x) for x in xs if cond]` | `list`（立即计算） |
| 字典推导 | `{k: v for k, v in pairs}` | `dict` |
| 集合推导 | `{f(x) for x in xs}` | `set`（自动去重） |
| 生成器表达式 | `(f(x) for x in xs)` | 惰性迭代器（省内存） |

```python
by_id = {c["id"]: c for c in claims}
tags = {tag for c in claims for tag in c["tags"]}       # 嵌套
```

**注意**：推导式只适合简单逻辑。超过两层或带复杂条件，写成普通循环更可读。

---

## 6. 排序

```python
nums.sort()                              # 原地
sorted(nums, reverse=True)               # 新列表

claims = [{"id": "C-1", "amount": 300}, {"id": "C-2", "amount": 100}]
claims.sort(key=lambda c: c["amount"])             # 按金额升序
claims.sort(key=lambda c: (-c["amount"], c["id"])) # 金额降序，再按 id 升序
```

- `key` 函数返回什么，就按什么排序。
- 多关键字用元组：`(-amount, id)`，负号表示降序（数字）。
- Python 的排序是稳定的，可以先按次要关键字排一次，再按主要关键字排。
- 字符串排序是字典序（Unicode 码点），中文排序需要 `locale` 或 `pypinyin`。

---

## 7. 函数进阶

```python
def call_model(prompt: str, *, model: str = "deepseek-chat", temperature: float = 0.2) -> str:
    ...

call_model("hi", model="deepseek-reasoner")   # 关键字参数，可读性高
```

- `*` 后面的参数只能按关键字传（Agent 项目很常用，防止参数传错位）。
- `*args` 收集多余位置参数（tuple），`**kwargs` 收集多余关键字参数（dict）。
- 参数默认值在**函数定义时**求值一次（见 stage1 的可变默认值坑）。

### 作用域与闭包

```python
x = "global"

def outer():
    x = "outer"

    def inner():
        nonlocal x      # 修改外层变量必须声明
        x = "inner"

    inner()
    return x

outer()   # "inner"
```

```python
def make_multiplier(n: int):
    def multiply(x: int) -> int:
        return x * n
    return multiply

double = make_multiplier(2)
double(10)   # 20
```

闭包是装饰器的基础（第 3 周）。

---

## 8. 迭代器与生成器（重点）

```python
def read_lines(path):
    with open(path, encoding="utf-8") as f:
        for line in f:          # 一次只读一行，不会把整个文件读进内存
            yield line.strip()

for line in read_lines("big.jsonl"):
    ...
```

- `yield` 让函数变成生成器：**调用时不执行**，迭代时才算。
- 生成器只能迭代一次，但内存占用是 O(1)。
- 大数据/AI 场景：读大文件、流式响应、分批调用模型都用它。

```python
def chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]
```

**Java 对照**：生成器 ≈ `Iterator` + 惰性求值，但不用写 `hasNext()/next()`。

```python
# 生成器表达式（注意是圆括号）
total = sum(x * x for x in range(1_000_000))   # 不会创建百万元素的 list
```

---

## 9. 常用 collections

| 类 | 用途 |
|---|---|
| `Counter` | 计数、Top-K |
| `defaultdict` | 分组时免去 `if key not in d` |
| `deque` | 双端队列、滑动窗口 |
| `namedtuple` | 轻量不可变记录（现在多用 dataclass） |
| `OrderedDict` | 需要显式有序语义时（普通 dict 已有序） |

```python
from collections import defaultdict

groups = defaultdict(list)
for item in items:
    groups[item["type"]].append(item)
```

---

## 10. 本阶段练习

| 函数 | 练什么 | Agent 场景 |
|---|---|---|
| `word_freq` | Counter、排序、正则 | 关键词提取 |
| `chunked` | 生成器、切片 | 长文本分批、批量调模型 |
| `deep_merge` | 递归、深拷贝 | 合并默认配置与用户配置 |
| `dedupe` | set、保序 | 工具结果去重 |
| `make_counter` | 闭包、`nonlocal` | 调用次数统计 |
| `group_by` | defaultdict、函数作为参数 | 按类型归类工具/日志 |

验收：

```powershell
.\.venv\Scripts\python.exe -m pytest stage2_structures -q
```

**自检问题**（能答上来才算过）：

1. `b = a` 和 `b = a.copy()` 有什么区别？嵌套 dict 呢？
2. 为什么 `def f(x, acc=[])` 是错的？
3. 生成器和列表推导式在内存上差多少？
4. `sorted(claims, key=lambda c: -c["amount"])` 里负号的作用？
