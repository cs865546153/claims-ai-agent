"""Stage 1 · 语法地基 —— 练习题。

规则：
    1. 只改这个文件，把 `raise NotImplementedError` 换成你的实现。
    2. 在 My_Study/Python 目录运行：
           .\\.venv\\Scripts\\python.exe -m pytest stage1_basics -q
    3. 卡住 20 分钟再看 solutions.py。
    4. 类型标注已经写好，先照着理解，第 3 周会系统学。
"""

from __future__ import annotations


def fizzbuzz(n: int) -> list[str]:
    """返回 1..n 的 FizzBuzz 列表。

    规则：
        - 同时是 3 和 5 的倍数 -> "FizzBuzz"
        - 3 的倍数             -> "Fizz"
        - 5 的倍数             -> "Buzz"
        - 其它                 -> 数字的字符串形式
        - n <= 0               -> 返回空列表

    示例：
        fizzbuzz(5)  -> ["1", "2", "Fizz", "4", "Buzz"]
        fizzbuzz(15)[-1] -> "FizzBuzz"
    """
    raise NotImplementedError("TODO: 实现 fizzbuzz")


def clean_text(text: str) -> str:
    """清洗文本，用于后续分词/检索。

    步骤：
        1. 全部转小写
        2. 去掉这些标点：. , ! ? ; : " ' ( ) [ ] { }
           （替换成空格，不是直接删除，避免 "a,b" 变成 "ab"）
        3. 把连续空白压缩成一个空格，并去掉首尾空白

    示例：
        clean_text("  Hello,   World!! ") -> "hello world"
        clean_text("Claim-2024 (v2)")     -> "claim-2024 v2"
        clean_text("...!!!")              -> ""
    """
    raise NotImplementedError("TODO: 实现 clean_text")


def parse_env_flag(value: str | None, default: bool = False) -> bool:
    """解析环境变量里的布尔值。

    规则（忽略首尾空白和大小写）：
        - None                      -> 返回 default
        - "1" / "true" / "yes" / "on" / "y"   -> True
        - "0" / "false" / "no" / "off" / "n" / "" -> False
        - 其它值                    -> 抛 ValueError

    示例：
        parse_env_flag(" TRUE ")        -> True
        parse_env_flag(None)            -> False
        parse_env_flag(None, True)      -> True
        parse_env_flag("maybe")         -> ValueError
    """
    raise NotImplementedError("TODO: 实现 parse_env_flag")


def stats(numbers: list[float]) -> dict[str, float | int | None]:
    """统计一组数字。

    返回的 dict 必须包含且只包含这些键：
        count: 元素个数（int）
        min / max / sum / avg: float；空列表时为 None

    示例：
        stats([1, 2, 3]) -> {"count": 3, "min": 1.0, "max": 3.0, "sum": 6.0, "avg": 2.0}
        stats([])        -> {"count": 0, "min": None, "max": None, "sum": None, "avg": None}
    """
    raise NotImplementedError("TODO: 实现 stats")


def is_palindrome(text: str) -> bool:
    """判断回文：只保留字母和数字，忽略大小写。

    注意：
        - 空字符串、全是标点的字符串，按"不是回文"处理（返回 False）
        - 中文字符也算字母（str.isalnum() 对中文返回 True）

    示例：
        is_palindrome("A man, a plan, a canal: Panama") -> True
        is_palindrome("上海自来水来自海上")               -> True
        is_palindrome("hello")                          -> False
        is_palindrome("")                               -> False
    """
    raise NotImplementedError("TODO: 实现 is_palindrome")
