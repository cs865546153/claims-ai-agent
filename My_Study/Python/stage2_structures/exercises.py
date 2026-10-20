"""Stage 2 · 数据结构与函数 —— 练习题。

运行：
    .\\.venv\\Scripts\\python.exe -m pytest stage2_structures -q
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from typing import Any, TypeVar

T = TypeVar("T")


def word_freq(text: str, top_k: int = 10) -> list[tuple[str, int]]:
    """统计词频，返回前 top_k 个 (单词, 次数)。

    规则：
        - 单词 = 连续的字/字母/数字/下划线，统一转小写
          （提示：re.findall(r"\\w+", text.lower())）
        - 排序：次数降序；次数相同按单词升序
        - top_k <= 0 -> 返回 []

    示例：
        word_freq("The cat and the dog. The end!", 3)
        -> [("the", 3), ("and", 1), ("cat", 1)]
    """
    raise NotImplementedError("TODO: 实现 word_freq")


def chunked(items: Sequence[T], size: int) -> Iterator[list[T]]:
    """把序列切成固定大小的块，返回**生成器**。

    规则：
        - size <= 0 -> 抛 ValueError
        - 空序列 -> 不产生任何块
        - 最后一块可以不足 size
        - 必须惰性求值（调用函数时不执行循环）

    示例：
        list(chunked([1, 2, 3, 4, 5], 2)) -> [[1, 2], [3, 4], [5]]
        list(chunked([], 3))              -> []
    """
    raise NotImplementedError("TODO: 实现 chunked（用 yield）")


def deep_merge(base: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    """递归合并两个 dict，返回新 dict。

    规则：
        - 两边都是 dict -> 递归合并
        - 其它情况 -> patch 的值覆盖 base
        - patch 有、base 没有的键 -> 直接加入
        - **不能修改 base 或 patch**（包括嵌套的 list/dict）

    示例：
        base  = {"a": 1, "nested": {"x": 1, "y": 2}, "tags": ["a"]}
        patch = {"b": 2, "nested": {"y": 20}, "tags": ["b"]}
        deep_merge(base, patch)
        -> {"a": 1, "b": 2, "nested": {"x": 1, "y": 20}, "tags": ["b"]}
    """
    raise NotImplementedError("TODO: 实现 deep_merge")


def dedupe(items: Iterable[T]) -> list[T]:
    """保序去重，返回 list。

    要求：
        - 保留元素第一次出现的位置
        - 元素必须可哈希（str/int/tuple 等）
        - 输入可以是任意可迭代对象（包括生成器）

    示例：
        dedupe(["b", "a", "b", "c", "a"]) -> ["b", "a", "c"]
        dedupe([])                        -> []
    """
    raise NotImplementedError("TODO: 实现 dedupe")


def make_counter(start: int = 0) -> Callable[[], int]:
    """返回一个计数器函数：每次调用把计数 +1 并返回新值。

    要求：
        - make_counter() 第一次调用返回 1
        - make_counter(10) 第一次调用返回 11
        - 多个计数器互不影响

    示例：
        c = make_counter(10)
        c()  # 11
        c()  # 12
    """
    raise NotImplementedError("TODO: 实现 make_counter（用闭包 + nonlocal）")


def group_by(records: Iterable[T], key: Callable[[T], str]) -> dict[str, list[T]]:
    """按 key 函数分组，保持原始顺序。

    规则：
        - 返回普通 dict（不要返回 defaultdict）
        - 每组的 list 内保持输入顺序
        - 组与组的顺序 = 该组第一次出现的顺序

    示例：
        records = [{"t": "a", "v": 1}, {"t": "b", "v": 2}, {"t": "a", "v": 3}]
        group_by(records, lambda r: r["t"])
        -> {"a": [{"t": "a", "v": 1}, {"t": "a", "v": 3}], "b": [{"t": "b", "v": 2}]}
    """
    raise NotImplementedError("TODO: 实现 group_by")
