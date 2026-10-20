"""Stage 1 自动判分。不要修改本文件。"""

from __future__ import annotations

import pytest

from stage1_basics.exercises import (
    clean_text,
    fizzbuzz,
    is_palindrome,
    parse_env_flag,
    stats,
)


def test_fizzbuzz_basic() -> None:
    assert fizzbuzz(5) == ["1", "2", "Fizz", "4", "Buzz"]


def test_fizzbuzz_full_cycle() -> None:
    result = fizzbuzz(15)
    assert len(result) == 15
    assert result[2] == "Fizz"
    assert result[4] == "Buzz"
    assert result[14] == "FizzBuzz"
    assert result[0] == "1"


@pytest.mark.parametrize("n", [0, -1, -100])
def test_fizzbuzz_non_positive(n: int) -> None:
    assert fizzbuzz(n) == []


def test_clean_text_basic() -> None:
    assert clean_text("  Hello,   World!! ") == "hello world"


def test_clean_text_keeps_hyphen_and_digits() -> None:
    assert clean_text("Claim-2024 (v2)") == "claim-2024 v2"


def test_clean_text_only_punctuation() -> None:
    assert clean_text("...!!!") == ""


def test_clean_text_whitespace() -> None:
    assert clean_text("A\tB\nC") == "a b c"
    assert clean_text("") == ""


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", " yes ", "on", "Y"])
def test_parse_env_flag_truthy(raw: str) -> None:
    assert parse_env_flag(raw) is True


@pytest.mark.parametrize("raw", ["0", "false", "off", "no", "n", "", "   "])
def test_parse_env_flag_falsey(raw: str) -> None:
    assert parse_env_flag(raw) is False


def test_parse_env_flag_none_uses_default() -> None:
    assert parse_env_flag(None) is False
    assert parse_env_flag(None, default=True) is True


@pytest.mark.parametrize("raw", ["maybe", "2", "enable"])
def test_parse_env_flag_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_env_flag(raw)


def test_stats_normal() -> None:
    result = stats([1, 2, 3])
    assert result["count"] == 3
    assert result["min"] == 1.0
    assert result["max"] == 3.0
    assert result["sum"] == pytest.approx(6.0)
    assert result["avg"] == pytest.approx(2.0)


def test_stats_empty() -> None:
    result = stats([])
    assert result == {"count": 0, "min": None, "max": None, "sum": None, "avg": None}


def test_stats_single_value() -> None:
    result = stats([2.5])
    assert result["count"] == 1
    assert result["avg"] == pytest.approx(2.5)


def test_stats_negative_values() -> None:
    result = stats([-2.0, 0.0, 2.0])
    assert result["min"] == -2.0
    assert result["max"] == 2.0
    assert result["avg"] == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("A man, a plan, a canal: Panama", True),
        ("racecar", True),
        ("上海自来水来自海上", True),
        ("No 'x' in Nixon", True),
        ("hello", False),
        ("", False),
        ("...!!!", False),
        ("ab", False),
    ],
)
def test_is_palindrome(text: str, expected: bool) -> None:
    assert is_palindrome(text) is expected
