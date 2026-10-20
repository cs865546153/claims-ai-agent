# Stage 1 · 语法地基

> 目标：脱离 Java 的写法，写出"像 Python"的 30 行脚本。
> 预计：2 天（PLAN.md Day 1~2）。

---

## 1. 程序结构与运行

Python 没有 `main` 方法，一个 `.py` 文件就是模块，从上到下执行。

```python
"""模块文档字符串：说明这个文件干什么。"""

import json              # 标准库
from pathlib import Path # 标准库里的常用类

def main() -> None:      # 函数用 def，缩进 4 空格
    print("hello")

if __name__ == "__main__":   # 只有直接运行本文件时才执行
    main()
```

- `python file.py`：`__name__ == "__main__"`。
- `import file`：`__name__ == "file"`，下面的 `main()` 不会执行。
- 不需要分号、不需要声明变量类型、没有 `public static void`。

**Java 对照**：一个文件可以有多个顶层函数/类，没有"文件名必须等于类名"的限制。

---

## 2. 变量、类型与真假值

```python
count = 3            # int（任意精度，不会溢出）
price = 9.9          # float（IEEE 754，和 Java double 一样有精度问题）
name = "张三"         # str（不可变）
enabled = True       # bool（首字母大写）
nothing = None       # 空值

count: int = 3       # 类型标注：只是提示，运行时不检查
```

**真假值（truthiness）**：Python 里很多值直接当布尔用。

| 为 False | 为 True |
|---|---|
| `False`、`None` | 其它对象 |
| `0`、`0.0` | 非零数字 |
| `""`（空串） | 非空字符串 |
| `[]`、`{}`、`set()` | 非空容器 |

```python
if not items:            # 比 if len(items) == 0 更 Python
    print("空")
```

### `is` vs `==`（重点）

```python
a = [1, 2]
b = [1, 2]
a == b      # True：值相等
a is b      # False：不是同一个对象

x = None
if x is None:      # 判空一律用 is None
    ...
```

- Java 的 `==` ≈ Python 的 `is`（比引用）。
- Java 的 `.equals()` ≈ Python 的 `==`（比值）。
- 小整数/短字符串有缓存，`is` 偶尔为 True，**不要依赖**。

---

## 3. 字符串与 f-string

```python
name = "张三"
amount = 1234.5

# f-string：最常用
msg = f"用户 {name} 金额 {amount:.2f}"
msg2 = f"{name=}, {amount=}"        # 调试神器：输出 name='张三', amount=1234.5

# 常用方法（都返回新字符串，原串不变）
s = "  Hello, World  "
s.strip()            # "Hello, World"
s.lower()            # "  hello, world  "
s.replace("l", "L")  # 全部替换
s.split(",")         # ["  Hello", " World  "]
",".join(["a", "b"]) # "a,b"
s.startswith("  H")  # True
```

**注意**

- 字符串不可变，`s.upper()` 不会改变 `s`，必须重新赋值。
- 大量拼接用 `"".join(parts)`，不要循环 `+=`（每次都会新建对象）。
- `split()` 不带参数会按"任意空白"切分并丢掉空串，`split(" ")` 不会。

### 正则入门（文本清洗够用）

```python
import re

re.findall(r"\w+", "订单 A-123, 金额 100")   # ['订单', 'A', '123', '金额', '100']
re.sub(r"\s+", " ", "a   b\tc")              # 'a b c'
re.match(r"^CLM-\d+$", "CLM-2024")           # 匹配返回 Match，否则 None
```

---

## 4. 控制流

```python
# if / elif / else
if amount >= 10000:
    level = "high"
elif amount >= 1000:
    level = "medium"
else:
    level = "low"

# 三元表达式（结果在前，条件在后）
level = "high" if amount >= 10000 else "low"

# for：迭代的是元素，不是下标
for tag in ["vip", "fraud"]:
    print(tag)

for i, tag in enumerate(["vip", "fraud"], start=1):
    print(i, tag)

for name, value in {"a": 1, "b": 2}.items():
    print(name, value)

# while
n = 3
while n > 0:
    n -= 1          # 没有 n-- 这种写法

# range：左闭右开
list(range(3))      # [0, 1, 2]

# break / continue 与 Java 相同
# for-else：循环没被 break 时执行 else（Java 没有）
for x in [1, 3, 5]:
    if x % 2 == 0:
        break
else:
    print("没有偶数")
```

**Java 对照**

| Java | Python |
|---|---|
| `for (int i = 0; i < n; i++)` | `for i in range(n)` |
| `for (String s : list)` | `for s in list` |
| `switch` | `match`（3.10+，可选学） |
| `i++` | `i += 1` |

---

## 5. 常用内置函数

```python
len(items)          # 长度
sum(nums)           # 求和
min(nums) / max(nums)
sorted(items)                 # 返回新 list
sorted(items, key=len, reverse=True)
abs(-3)
round(3.14159, 2)             # 3.14（银行家舍入，注意）
any([False, True])            # True
all([True, True])             # True
enumerate(items)              # (下标, 元素)
zip(a, b)                     # 并行迭代，长度取短的
isinstance(x, str)            # 类型判断
type(x)                       # 类型
```

---

## 6. 常见坑（本章必须记住）

1. **缩进错误**：混用 Tab 和空格会报 `TabError`。VSCode 设置成 4 空格。
2. **`is` 和 `==` 混用**：值比较用 `==`，判空用 `is None`。
3. **整除和取模对负数**：`-7 // 2 == -4`，`-7 % 2 == 1`（和 Java 不同）。
4. **浮点精度**：`0.1 + 0.2 == 0.3` 是 `False`；金额相关用 `Decimal` 或整数分。
5. **字符串不可变**：所有"修改"方法都返回新串。
6. **`input()` 永远返回字符串**：需要数字要 `int(...)`。
7. **`==` 对 `None`**：能跑但不地道，统一 `is None`。

---

## 7. 本阶段练习

文件：`exercises.py`（只改这个文件）

| 函数 | 练什么 | Agent 场景 |
|---|---|---|
| `fizzbuzz` | 循环、条件、列表 | 热身 |
| `clean_text` | 字符串、`translate`、空白处理 | 文本预处理 |
| `parse_env_flag` | 字符串规范化、异常 | 解析 `DEBUG=true` 这类配置 |
| `stats` | 聚合、空值处理、dict | 指标统计 |
| `is_palindrome` | 字符串过滤、切片 | 文本处理 |

验收：

```powershell
.\.venv\Scripts\python.exe -m pytest stage1_basics -q
```

全部通过后，把 `solutions.py` 和你的写法对比，重点看：

- 有没有用推导式/内置函数替代手写循环；
- 空输入、异常输入有没有处理；
- 变量命名是否清晰（Python 用 `snake_case`，类名 `PascalCase`，常量 `UPPER_CASE`）。
