"""Stage 3 · 类、异常、文件、配置、日志 —— 练习题。

运行：
    .\\.venv\\Scripts\\python.exe -m pytest stage3_oop_errors -q
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# 1. Claim：dataclass + 校验 + property
# ---------------------------------------------------------------------------
@dataclass
class Claim:
    """理赔单。

    要求：
        - 字段：claim_id: str, amount: float, status: str = "new",
                tags: list[str] 默认空列表（注意可变默认值）
        - __post_init__ 校验：
            * claim_id 去掉首尾空白后不能为空，并且保存去掉空白后的值
            * amount 不能为负
            * status 必须是 {"new", "reviewing", "approved", "rejected"} 之一
          校验失败一律抛 ValueError
        - property is_high_risk：amount >= 10000
        - add_tag(tag)：去掉首尾空白；空串忽略；已存在不重复添加
        - to_dict()：返回 {"claim_id", "amount", "status", "tags"}，
          tags 必须是副本（外部修改返回值不能影响对象）

    示例：
        c = Claim("  C-1  ", 20000)
        c.claim_id        # "C-1"
        c.is_high_risk    # True
        c.add_tag("vip"); c.add_tag("vip"); c.add_tag(" ")
        c.tags            # ["vip"]
    """

    claim_id: str
    amount: float
    status: str = "new"
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        raise NotImplementedError("TODO: 实现 __post_init__ 校验")

    @property
    def is_high_risk(self) -> bool:
        raise NotImplementedError("TODO: 实现 is_high_risk")

    def add_tag(self, tag: str) -> None:
        raise NotImplementedError("TODO: 实现 add_tag")

    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError("TODO: 实现 to_dict")


# ---------------------------------------------------------------------------
# 2. 自定义异常 + 金额解析
# ---------------------------------------------------------------------------
class ClaimError(Exception):
    """理赔业务异常基类。"""


def parse_amount(raw: str | int | float | None) -> float:
    """把各种写法的金额解析成 float。

    规则：
        - None、" "、"" -> 抛 ClaimError
        - int/float -> 直接转 float
        - str：去掉 ¥ ￥ $ , 和空格后再转（例如 "¥1,234.50" -> 1234.5）
        - 负数 -> 抛 ClaimError
        - 无法转换 -> 抛 ClaimError，并用 `raise ... from e` 保留原因

    示例：
        parse_amount("¥1,234.50") -> 1234.5
        parse_amount(" 12 ")      -> 12.0
        parse_amount(3)           -> 3.0
        parse_amount("abc")       -> ClaimError
    """
    raise NotImplementedError("TODO: 实现 parse_amount")


# ---------------------------------------------------------------------------
# 3. 读取 JSON 配置
# ---------------------------------------------------------------------------
def load_json(path: str | Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    """读取 UTF-8 JSON 文件并返回 dict。

    规则：
        - 文件不存在 -> 返回 default；default 为 None 时返回 {}
        - 内容不是合法 JSON -> 抛 ValueError，消息里带文件路径
        - 顶层不是 object（dict） -> 抛 ValueError

    示例：
        load_json("not-exists.json")        -> {}
        load_json("not-exists.json", {"a": 1}) -> {"a": 1}
    """
    raise NotImplementedError("TODO: 实现 load_json")


# ---------------------------------------------------------------------------
# 4. 逐行读取 JSONL
# ---------------------------------------------------------------------------
def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """读取 JSONL 文件（每行一个 JSON object）。

    规则：
        - 使用 UTF-8
        - 跳过空行和以 # 开头的注释行
        - 某行 JSON 非法 -> 抛 ValueError，消息里带**行号**和路径
        - 某行是合法 JSON 但不是 object -> 抛 ValueError
        - 返回所有记录组成的 list

    示例文件：
        {"id": 1}
        (空行)
        # 注释
        {"id": 2}
    """
    raise NotImplementedError("TODO: 实现 read_jsonl")


# ---------------------------------------------------------------------------
# 5. 上下文管理器
# ---------------------------------------------------------------------------
class Timer:
    """计时上下文管理器。

    用法：
        with Timer() as t:
            do_something()
        print(t.elapsed)      # 秒，float

    要求：
        - 进入 with 时开始计时（time.perf_counter）
        - 退出时把耗时写入 self.elapsed
        - 不能吞掉 with 块里的异常（__exit__ 返回 None）
    """

    def __init__(self) -> None:
        self.elapsed: float = 0.0

    def __enter__(self) -> Timer:
        raise NotImplementedError("TODO: 实现 __enter__")

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        raise NotImplementedError("TODO: 实现 __exit__")


# ---------------------------------------------------------------------------
# 6. 日志初始化
# ---------------------------------------------------------------------------
def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """创建/复用一个 logger。

    要求：
        - 同一个 name 多次调用，不能重复添加 handler（幂等）
        - handler 输出到 sys.stdout
        - 格式："%(levelname)s %(name)s: %(message)s"
        - logger.propagate = False
        - 返回 logger

    示例：
        logger = setup_logger("agent")
        logger.warning("timeout")
        # 控制台输出：WARNING agent: timeout
    """
    raise NotImplementedError("TODO: 实现 setup_logger")
