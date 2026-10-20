"""Stage 2 自动判分。不要修改本文件。"""

from __future__ import annotations

import pytest

from stage2_structures.exercises import (
    chunked,
    dedupe,
    deep_merge,
    group_by,
    make_counter,
    word_freq,
)


def test_word_freq_basic() -> None:
    result = word_freq("The cat and the dog. The end!", top_k=3)
    assert result == [("the", 3), ("and", 1), ("cat", 1)]


def test_word_freq_case_insensitive_and_digits() -> None:
    result = word_freq("A a A1 a1 a1", top_k=2)
    assert result == [("a1", 3), ("a", 2)]


def test_word_freq_chinese() -> None:
    result = word_freq("理赔 理赔 保单 理赔", top_k=2)
    assert result == [("理赔", 3), ("保单", 1)]


def test_word_freq_top_k_edge_cases() -> None:
    assert word_freq("a b", top_k=0) == []
    assert word_freq("a b", top_k=-1) == []
    assert word_freq("") == []


def test_word_freq_punctuation_split() -> None:
    result = word_freq("claim_id, claim_id; claim-id")
    assert ("claim_id", 2) in result
    assert ("claim", 1) in result


def test_chunked_basic() -> None:
    assert list(chunked([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]
    assert list(chunked([1, 2, 3], 3)) == [[1, 2, 3]]
    assert list(chunked([1, 2], 5)) == [[1, 2]]


def test_chunked_empty() -> None:
    assert list(chunked([], 3)) == []


def test_chunked_is_lazy_iterator() -> None:
    gen = chunked([1, 2, 3], 2)
    assert iter(gen) is gen
    assert next(gen) == [1, 2]
    assert next(gen) == [3]


def test_chunked_invalid_size() -> None:
    with pytest.raises(ValueError):
        list(chunked([1, 2], 0))


def test_chunked_accepts_tuple() -> None:
    assert list(chunked((1, 2, 3), 2)) == [[1, 2], [3]]


def test_deep_merge_basic() -> None:
    base = {"a": 1, "nested": {"x": 1, "y": 2}, "tags": ["a"]}
    patch = {"b": 2, "nested": {"y": 20}, "tags": ["b"]}
    assert deep_merge(base, patch) == {
        "a": 1,
        "b": 2,
        "nested": {"x": 1, "y": 20},
        "tags": ["b"],
    }


def test_deep_merge_does_not_mutate_inputs() -> None:
    base = {"nested": {"x": 1}, "tags": ["a"]}
    patch = {"nested": {"y": 2}, "extra": {"k": 1}}
    result = deep_merge(base, patch)

    result["nested"]["x"] = 999
    result["tags"].append("b")
    result["extra"]["k"] = 999

    assert base == {"nested": {"x": 1}, "tags": ["a"]}
    assert patch == {"nested": {"y": 2}, "extra": {"k": 1}}


def test_deep_merge_empty() -> None:
    assert deep_merge({}, {"a": 1}) == {"a": 1}
    assert deep_merge({"a": 1}, {}) == {"a": 1}
    assert deep_merge({}, {}) == {}


def test_dedupe_preserves_order() -> None:
    assert dedupe(["b", "a", "b", "c", "a"]) == ["b", "a", "c"]


def test_dedupe_accepts_generator() -> None:
    assert dedupe(x % 3 for x in range(10)) == [0, 1, 2]


def test_dedupe_empty() -> None:
    assert dedupe([]) == []


def test_dedupe_tuple_elements() -> None:
    assert dedupe([(1, 2), (1, 2), (3, 4)]) == [(1, 2), (3, 4)]


def test_make_counter_default_start() -> None:
    counter = make_counter()
    assert [counter(), counter(), counter()] == [1, 2, 3]


def test_make_counter_custom_start() -> None:
    counter = make_counter(10)
    assert [counter(), counter()] == [11, 12]


def test_make_counter_independent() -> None:
    a = make_counter()
    b = make_counter(100)
    assert a() == 1
    assert a() == 2
    assert b() == 101


def test_group_by_basic() -> None:
    records = [{"t": "a", "v": 1}, {"t": "b", "v": 2}, {"t": "a", "v": 3}]
    result = group_by(records, lambda r: str(r["t"]))
    assert type(result) is dict
    assert result == {
        "a": [{"t": "a", "v": 1}, {"t": "a", "v": 3}],
        "b": [{"t": "b", "v": 2}],
    }


def test_group_by_preserves_group_order() -> None:
    result = group_by(["bb", "a", "cc", "d"], key=lambda s: "short" if len(s) == 1 else "long")
    assert list(result) == ["long", "short"]


def test_group_by_empty() -> None:
    assert group_by([], key=lambda x: x) == {}
