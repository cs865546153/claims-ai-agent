"""Stage 1 参考答案。

看答案的正确方式：
    1. 先看思路注释，自己合上文件重写一遍；
    2. 再对比"边界处理"和"命名"；
    3. 不要背代码，背模式。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 1. fizzbuzz：循环 + 条件
# ---------------------------------------------------------------------------
# 关键点：先判断 15（3 和 5 的公倍数），否则会被 3 或 5 的分支提前命中。
# range(1, n + 1) 是左闭右开；n <= 0 时自然是空循环，不用特判。


def fizzbuzz(n: int) -> list[str]:
    result: list[str] = []
    for i in range(1, n + 1):
        if i % 15 == 0:
            result.append("FizzBuzz")
        elif i % 3 == 0:
            result.append("Fizz")
        elif i % 5 == 0:
            result.append("Buzz")
        else:
            result.append(str(i))
    return result


# 一行流（可以了解，但业务代码优先可读性）：
# def fizzbuzz(n: int) -> list[str]:
#     return [
#         "FizzBuzz" if i % 15 == 0 else "Fizz" if i % 3 == 0 else "Buzz" if i % 5 == 0 else str(i)
#         for i in range(1, n + 1)
#     ]


# ---------------------------------------------------------------------------
# 2. clean_text：字符串不可变 + translate
# ---------------------------------------------------------------------------
# 两种写法：
#   A. str.translate：把标点映射成空格，性能好，适合大批量文本。
#   B. re.sub：更直观，适合规则复杂时。
# 这里用 A，顺便认识 str.maketrans。

_PUNCTUATION = set(".,!?;:\"'()[]{}")
_TRANSLATION = str.maketrans({ch: " " for ch in _PUNCTUATION})


def clean_text(text: str) -> str:
    # translate 返回新字符串，原字符串不变
    cleaned = text.lower().translate(_TRANSLATION)
    # split() 不带参数：按任意空白切分，并自动丢掉空串
    return " ".join(cleaned.split())


# 等价的 re 写法：
# import re
# def clean_text(text: str) -> str:
#     cleaned = re.sub(r"[.,!?;:\"'()\[\]{}]", " ", text.lower())
#     return " ".join(cleaned.split())


# ---------------------------------------------------------------------------
# 3. parse_env_flag：规范化 + 显式异常
# ---------------------------------------------------------------------------
# 关键点：
#   - None 要单独处理，不能直接 .strip()
#   - 用字典做映射，比一长串 if 清晰
#   - 未知值必须报错，不要默默当成 False（配置写错很难排查）

_TRUE_VALUES = {"1", "true", "yes", "on", "y"}
_FALSE_VALUES = {"0", "false", "no", "off", "n", ""}


def parse_env_flag(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False

    raise ValueError(f"无法解析为布尔值: {value!r}")


# ---------------------------------------------------------------------------
# 4. stats：聚合 + 空值语义
# ---------------------------------------------------------------------------
# 关键点：
#   - 空列表时 min()/max() 会抛 ValueError，必须先判断
#   - 返回 int/float 混用，类型标注写成 float | int | None
#   - "sum" 是内置函数名，局部变量改用 total，避免遮蔽


def stats(numbers: list[float]) -> dict[str, float | int | None]:
    if not numbers:
        return {"count": 0, "min": None, "max": None, "sum": None, "avg": None}

    total = sum(numbers)
    return {
        "count": len(numbers),
        "min": float(min(numbers)),
        "max": float(max(numbers)),
        "sum": float(total),
        "avg": total / len(numbers),
    }


# ---------------------------------------------------------------------------
# 5. is_palindrome：过滤 + 切片
# ---------------------------------------------------------------------------
# 关键点：
#   - 用 isalnum() 统一处理中英文和数字
#   - chars[::-1] 是切片反转，等价于 Java 的 StringBuilder.reverse()
#   - 空序列会被判成回文，需要显式排除


def is_palindrome(text: str) -> bool:
    chars = [ch.lower() for ch in text if ch.isalnum()]
    if not chars:
        return False
    return chars == chars[::-1]


# 节省内存的写法（大数据量时）：
# def is_palindrome(text: str) -> bool:
#     chars = [ch.lower() for ch in text if ch.isalnum()]
#     left, right = 0, len(chars) - 1
#     while left < right:
#         if chars[left] != chars[right]:
#             return False
#         left += 1
#         right -= 1
#     return bool(chars)
