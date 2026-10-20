"""Stage 3 参考答案与讲解。"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_ALLOWED_STATUS = {"new", "reviewing", "approved", "rejected"}


class ClaimError(Exception):
    """理赔业务异常基类。"""


# ---------------------------------------------------------------------------
# 1. Claim
# ---------------------------------------------------------------------------
# 关键点：
#   - __post_init__ 在自动生成的 __init__ 之后执行，适合做校验和字段规范化
#   - tags 用 default_factory=list，保证每个实例一个独立 list
#   - property 不能有同名实例属性，否则会递归/覆盖
#   - to_dict 返回副本，避免调用方改到内部状态


@dataclass
class Claim:
    claim_id: str
    amount: float
    status: str = "new"
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.claim_id = self.claim_id.strip()
        if not self.claim_id:
            raise ValueError("claim_id 不能为空")
        if self.amount < 0:
            raise ValueError(f"amount 不能为负: {self.amount}")
        if self.status not in _ALLOWED_STATUS:
            raise ValueError(f"非法状态: {self.status!r}")

    @property
    def is_high_risk(self) -> bool:
        return self.amount >= 10_000

    def add_tag(self, tag: str) -> None:
        normalized = tag.strip()
        if normalized and normalized not in self.tags:
            self.tags.append(normalized)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "amount": self.amount,
            "status": self.status,
            "tags": list(self.tags),
        }


# ---------------------------------------------------------------------------
# 2. parse_amount
# ---------------------------------------------------------------------------
# 关键点：
#   - 先处理 None/空串，避免后续 .strip() 报 AttributeError
#   - 支持货币符号和千分位，这是真实账单/表单里最常见的格式
#   - 用 raise ... from e 保留底层 ValueError，排查时能看到真实原因
#   - 拒绝 NaN/inf，否则后续金额比较和 JSON 序列化会出问题


def parse_amount(raw: str | int | float | None) -> float:
    if raw is None:
        raise ClaimError("金额为空")

    if isinstance(raw, bool):  # bool 是 int 的子类，单独拒绝
        raise ClaimError(f"非法金额: {raw!r}")

    if isinstance(raw, int | float):
        value = float(raw)
    else:
        cleaned = raw.strip()
        for symbol in ("¥", "￥", "$", ",", " "):
            cleaned = cleaned.replace(symbol, "")
        if not cleaned:
            raise ClaimError("金额为空")
        try:
            value = float(cleaned)
        except ValueError as e:
            raise ClaimError(f"非法金额: {raw!r}") from e

    if not math.isfinite(value):
        raise ClaimError(f"金额必须是有限数字: {raw!r}")
    if value < 0:
        raise ClaimError(f"金额不能为负: {raw!r}")
    return value


# ---------------------------------------------------------------------------
# 3. load_json
# ---------------------------------------------------------------------------
# 关键点：
#   - Path 比字符串拼接安全（自动处理分隔符）
#   - 文件不存在是"正常情况"（首次启动），返回默认值即可
#   - JSON 错误要带路径，否则配置多的时候根本不知道读的哪个文件
#   - 显式 encoding="utf-8"，跨平台稳定


def load_json(path: str | Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        return {} if default is None else default

    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"配置文件不是合法 JSON: {file_path}") from e

    if not isinstance(data, dict):
        raise ValueError(f"配置顶层必须是 JSON object: {file_path}")
    return data


# ---------------------------------------------------------------------------
# 4. read_jsonl
# ---------------------------------------------------------------------------
# 关键点：
#   - 逐行处理，内存 O(1)，几个 G 的文件也能读
#   - enumerate(f, start=1) 让行号从 1 开始，和编辑器一致
#   - 注释/空行跳过，是数据文件的常见约定
#   - 错误信息带行号，否则几百万行里根本定位不到


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    file_path = Path(path)
    records: list[dict[str, Any]] = []

    with file_path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            try:
                record = json.loads(text)
            except json.JSONDecodeError as e:
                raise ValueError(f"第 {lineno} 行不是合法 JSON: {file_path}") from e
            if not isinstance(record, dict):
                raise ValueError(f"第 {lineno} 行不是 JSON object: {file_path}")
            records.append(record)
    return records


# ---------------------------------------------------------------------------
# 5. Timer
# ---------------------------------------------------------------------------
# 关键点：
#   - perf_counter 单调递增，不受系统时间调整影响，适合计时
#   - 返回 None 表示"不吞异常"；返回 True 会静默吞掉 with 块里的所有异常，是危险操作


class Timer:
    def __init__(self) -> None:
        self.elapsed: float = 0.0
        self._start: float = 0.0

    def __enter__(self) -> Timer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.elapsed = time.perf_counter() - self._start


# 更简洁的 contextlib 写法（项目里推荐）：
# from contextlib import contextmanager
#
# @contextmanager
# def timer():
#     start = time.perf_counter()
#     try:
#         yield
#     finally:
#         print(time.perf_counter() - start)


# ---------------------------------------------------------------------------
# 6. setup_logger
# ---------------------------------------------------------------------------
# 关键点：
#   - logger 是全局单例（按 name 缓存），重复 addHandler 会导致日志打印 N 遍
#   - 先 setLevel，再挂 handler；handler 自己也有 level（默认 NOTSET，继承）
#   - propagate=False：不要同时输出到 root logger
#   - 输出到 stdout 便于容器采集；错误日志可以另加 stderr handler


def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    import sys

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
    return logger
