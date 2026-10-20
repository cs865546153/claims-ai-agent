"""Stage 3 自动判分。不要修改本文件。"""

from __future__ import annotations

import json
import logging

import pytest

from stage3_oop_errors.exercises import (
    Claim,
    ClaimError,
    Timer,
    load_json,
    parse_amount,
    read_jsonl,
    setup_logger,
)


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------
def test_claim_trims_claim_id() -> None:
    claim = Claim("  C-1  ", 100)
    assert claim.claim_id == "C-1"


def test_claim_default_tags_not_shared() -> None:
    first = Claim("C-1", 100)
    second = Claim("C-2", 100)
    first.add_tag("vip")
    assert first.tags == ["vip"]
    assert second.tags == []


@pytest.mark.parametrize(
    ("claim_id", "amount", "status"),
    [
        ("", 100, "new"),
        ("   ", 100, "new"),
        ("C-1", -0.01, "new"),
        ("C-1", 100, "unknown"),
    ],
)
def test_claim_validation(claim_id: str, amount: float, status: str) -> None:
    with pytest.raises(ValueError):
        Claim(claim_id, amount, status)


def test_claim_is_high_risk() -> None:
    assert Claim("C-1", 10_000).is_high_risk is True
    assert Claim("C-1", 9_999).is_high_risk is False


def test_claim_add_tag() -> None:
    claim = Claim("C-1", 100)
    claim.add_tag("  vip  ")
    claim.add_tag("vip")
    claim.add_tag("   ")
    assert claim.tags == ["vip"]


def test_claim_to_dict_returns_copy() -> None:
    claim = Claim("C-1", 100, tags=["vip"])
    data = claim.to_dict()
    assert data == {"claim_id": "C-1", "amount": 100, "status": "new", "tags": ["vip"]}
    data["tags"].append("fraud")
    assert claim.tags == ["vip"]


# ---------------------------------------------------------------------------
# parse_amount
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("¥1,234.50", 1234.5),
        ("￥ 12", 12.0),
        ("$3", 3.0),
        (" 12 ", 12.0),
        ("0", 0.0),
        (3, 3.0),
        (3.5, 3.5),
    ],
)
def test_parse_amount_ok(raw: str | int | float, expected: float) -> None:
    assert parse_amount(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", [None, "", "   ", "abc", "1.2.3", -1, -0.5, "¥-1"])
def test_parse_amount_invalid(raw: str | int | float | None) -> None:
    with pytest.raises(ClaimError):
        parse_amount(raw)


def test_parse_amount_keeps_cause() -> None:
    with pytest.raises(ClaimError) as exc_info:
        parse_amount("abc")
    assert exc_info.value.__cause__ is not None


# ---------------------------------------------------------------------------
# load_json
# ---------------------------------------------------------------------------
def test_load_json_ok(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"a": 1}, ensure_ascii=False), encoding="utf-8")
    assert load_json(path) == {"a": 1}


def test_load_json_missing_returns_default(tmp_path) -> None:
    missing = tmp_path / "nope.json"
    assert load_json(missing) == {}
    assert load_json(missing, {"a": 1}) == {"a": 1}


def test_load_json_invalid(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_json(path)


def test_load_json_top_level_not_object(tmp_path) -> None:
    path = tmp_path / "list.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError):
        load_json(path)


# ---------------------------------------------------------------------------
# read_jsonl
# ---------------------------------------------------------------------------
def test_read_jsonl_skips_blank_and_comments(tmp_path) -> None:
    path = tmp_path / "data.jsonl"
    path.write_text(
        '{"id": 1}\n\n# 注释\n{"id": 2}\n',
        encoding="utf-8",
    )
    assert read_jsonl(path) == [{"id": 1}, {"id": 2}]


def test_read_jsonl_invalid_line_reports_number(tmp_path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"id": 1}\n{oops}\n', encoding="utf-8")
    with pytest.raises(ValueError) as exc_info:
        read_jsonl(path)
    assert "2" in str(exc_info.value)


def test_read_jsonl_non_object(tmp_path) -> None:
    path = tmp_path / "array.jsonl"
    path.write_text("[1, 2]\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_jsonl(path)


# ---------------------------------------------------------------------------
# Timer
# ---------------------------------------------------------------------------
def test_timer_records_elapsed() -> None:
    with Timer() as timer:
        pass
    assert isinstance(timer.elapsed, float)
    assert timer.elapsed >= 0


def test_timer_does_not_swallow_exception() -> None:
    with pytest.raises(RuntimeError):
        with Timer() as timer:
            raise RuntimeError("boom")
    assert timer.elapsed >= 0


# ---------------------------------------------------------------------------
# setup_logger
# ---------------------------------------------------------------------------
def test_setup_logger_output(capsys) -> None:
    logger = setup_logger("stage3_test_output", logging.INFO)
    logger.warning("timeout")
    out = capsys.readouterr().out
    assert "WARNING stage3_test_output: timeout" in out


def test_setup_logger_is_idempotent() -> None:
    name = "stage3_test_idempotent"
    first = setup_logger(name)
    second = setup_logger(name)
    assert first is second
    assert len(first.handlers) == 1
    assert first.propagate is False
