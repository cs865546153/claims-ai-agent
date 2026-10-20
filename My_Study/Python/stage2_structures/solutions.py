"""Stage 2 参考答案与讲解。"""

from __future__ import annotations

import copy
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from typing import Any, TypeVar

T = TypeVar("T")


# ---------------------------------------------------------------------------
# 1. word_freq：Counter + 多关键字排序
# ---------------------------------------------------------------------------
# 关键点：
#   - r"\w+" 在 Unicode 下能匹配中文、字母、数字、下划线，标点自然成为分隔符
#   - Counter 的 most_common 只按次数排序，次数相同顺序不保证；
#     用 sorted(key=( -count, word )) 才能得到稳定结果
#   - top_k <= 0 时切片 [::-1] 会变成"去掉最后一个"，属于经典坑，必须特判


def word_freq(text: str, top_k: int = 10) -> list[tuple[str, int]]:
    if top_k <= 0:
        return []
    words = re.findall(r"\w+", text.lower())
    counts = Counter(words)
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top_k]


# 如果不用 Counter：
# counts: dict[str, int] = {}
# for w in words:
#     counts[w] = counts.get(w, 0) + 1


# ---------------------------------------------------------------------------
# 2. chunked：生成器 + 切片
# ---------------------------------------------------------------------------
# 关键点：
#   - 函数体里出现 yield，调用时就不会执行任何代码，返回生成器
#   - 因此 size 校验也要等到第一次 next() 才触发（测试里用 list(...) 触发）
#   - range(start, stop, step) 每次跳过 size 个


def chunked(items: Sequence[T], size: int) -> Iterator[list[T]]:
    if size <= 0:
        raise ValueError(f"size 必须大于 0，当前为 {size}")
    for start in range(0, len(items), size):
        yield list(items[start : start + size])


# 流式版本（不要求 len，适合任意可迭代对象）：
# def chunked_stream(items: Iterable[T], size: int) -> Iterator[list[T]]:
#     if size <= 0:
#         raise ValueError("size 必须大于 0")
#     batch: list[T] = []
#     for item in items:
#         batch.append(item)
#         if len(batch) == size:
#             yield batch
#             batch = []
#     if batch:
#         yield batch


# ---------------------------------------------------------------------------
# 3. deep_merge：递归 + 深拷贝
# ---------------------------------------------------------------------------
# 关键点：
#   - 先 deepcopy(base)，之后所有修改都在副本上做，天然不污染入参
#   - 只有"两边都是 Mapping"才递归；list 直接替换（业务上通常也这样约定）
#   - 返回类型用 dict，避免调用方拿到 Mapping 代理


def deep_merge(base: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = copy.deepcopy(dict(base))
    for key, value in patch.items():
        current = result.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            result[key] = deep_merge(current, value)
        else:
            result[key] = copy.deepcopy(value)
    return result


# ---------------------------------------------------------------------------
# 4. dedupe：set 做已见集合
# ---------------------------------------------------------------------------
# 关键点：
#   - set 查找 O(1)，整体 O(n)
#   - 不能用 `list(set(items))`，那会丢顺序
#   - 元素不可哈希（list/dict）时会抛 TypeError，这是有意的：
#     需要去重 dict 时，先转成 tuple(sorted(d.items())) 或 json 字符串


def dedupe(items: Iterable[T]) -> list[T]:
    seen: set[T] = set()
    result: list[T] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


# ---------------------------------------------------------------------------
# 5. make_counter：闭包 + nonlocal
# ---------------------------------------------------------------------------
# 关键点：
#   - nonlocal 声明"我要改的是外层函数的变量"，否则 Python 会当成新局部变量
#   - 每次调用 make_counter 都会创建新的闭包环境，所以计数器互不影响


def make_counter(start: int = 0) -> Callable[[], int]:
    count = start

    def next_value() -> int:
        nonlocal count
        count += 1
        return count

    return next_value


# ---------------------------------------------------------------------------
# 6. group_by：defaultdict + 转回 dict
# ---------------------------------------------------------------------------
# 关键点：
#   - defaultdict(list) 让 `groups[k].append(v)` 不需要先判断键是否存在
#   - 题目要求返回普通 dict，最后 dict(groups)
#   - dict 保持插入顺序，所以组的顺序 = 第一次出现的顺序


def group_by(records: Iterable[T], key: Callable[[T], str]) -> dict[str, list[T]]:
    groups: defaultdict[str, list[T]] = defaultdict(list)
    for record in records:
        groups[key(record)].append(record)
    return dict(groups)
