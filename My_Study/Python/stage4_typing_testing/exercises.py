"""Stage 4 · 类型标注、pydantic、装饰器、测试 —— 练习题。

运行：
    .\\.venv\\Scripts\\python.exe -m pytest stage4_typing_testing -q
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ParamSpec, TypedDict, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

P = ParamSpec("P")
T = TypeVar("T")


# ---------------------------------------------------------------------------
# 1. 从模型的自由文本里提取 JSON
# ---------------------------------------------------------------------------
class JsonExtractError(ValueError):
    """无法从文本中提取出合法 JSON object。"""


def extract_json(text: str) -> dict[str, Any]:
    """从 LLM 输出里提取第一个 JSON object。

    规则：
        - 去掉首尾空白
        - 支持 markdown 围栏：```json ... ```
        - 允许 JSON 前后有解释性文字（截取第一个 { 到最后一个 }）
        - 解析失败 / 顶层不是 object -> 抛 JsonExtractError

    示例：
        extract_json('```json\\n{"a": 1}\\n```')       -> {"a": 1}
        extract_json('结果如下：{"a": 1} 完毕')        -> {"a": 1}
        extract_json('[1, 2]')                        -> JsonExtractError
    """
    raise NotImplementedError("TODO: 实现 extract_json")


# ---------------------------------------------------------------------------
# 2. 重试装饰器
# ---------------------------------------------------------------------------
def retry(
    times: int = 3,
    delay: float = 0.0,
    backoff: float = 2.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """重试装饰器。

    规则：
        - times 是**总尝试次数**，必须 >= 1，否则在装饰时抛 ValueError
        - 只捕获 exceptions 里指定的异常
        - 第 n 次失败后等待 delay * backoff ** (n - 1) 秒再重试
        - 全部失败 -> 抛出最后一次异常
        - 必须用 functools.wraps 保留原函数元信息

    示例：
        @retry(times=3, delay=0)
        def flaky():
            ...

        @retry(times=2, exceptions=(ValueError,))
        def only_value_error():
            ...
    """
    raise NotImplementedError("TODO: 实现 retry")


# ---------------------------------------------------------------------------
# 3. 解析工具调用（TypedDict）
# ---------------------------------------------------------------------------
class ToolCall(TypedDict):
    id: str
    name: str
    arguments: dict[str, Any]


class ToolCallError(ValueError):
    """工具调用格式非法。"""


def parse_tool_call(payload: dict[str, Any]) -> ToolCall:
    """把两种常见形状统一成 ToolCall。

    形状 A（OpenAI chat.completions）：
        {"id": "call_1", "type": "function",
         "function": {"name": "add", "arguments": '{"a": 1}'}}

    形状 B（简化/内部事件）：
        {"id": "call_2", "name": "add", "arguments": {"a": 1}}

    规则：
        - id、name 必须是非空字符串
        - arguments 为 None / 缺省 / 空串 -> {}
        - arguments 是 str -> json.loads，且结果必须是 dict
        - arguments 是 dict -> 原样使用
        - 其它情况 / 任何格式问题 -> 抛 ToolCallError

    示例：
        parse_tool_call({"id": "1", "name": "add", "arguments": '{"a": 1}'})
        -> {"id": "1", "name": "add", "arguments": {"a": 1}}
    """
    raise NotImplementedError("TODO: 实现 parse_tool_call")


# ---------------------------------------------------------------------------
# 4. pydantic 数据模型
# ---------------------------------------------------------------------------
class ClaimInput(BaseModel):
    """理赔请求入参。

    需要你补全两个 validator：
        - claim_id：去掉首尾空白后长度 >= 3，返回去空白后的值
        - tags：每个 tag 去空白、去空串、去重，最多 5 个
          超过 5 个（去重后）-> 抛 ValueError

    约束已经配好：
        - 多余字段 -> 报错（extra="forbid"）
        - amount: 0 < amount <= 1_000_000
    """

    model_config = ConfigDict(extra="forbid")

    claim_id: str
    amount: float = Field(gt=0, le=1_000_000)
    reason: str = ""
    tags: list[str] = Field(default_factory=list)

    @field_validator("claim_id")
    @classmethod
    def validate_claim_id(cls, value: str) -> str:
        raise NotImplementedError("TODO: 实现 claim_id validator")

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, tags: list[str]) -> list[str]:
        raise NotImplementedError("TODO: 实现 tags validator")
