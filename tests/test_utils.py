# tests/test_utils.py

"""Tests for core utility functions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pytest

from commamatrix.utils import await_if_needed, to_jsonable


class TestAwaitIfNeeded:
    @pytest.mark.asyncio
    async def test_await_coroutine(self):
        async def coro():
            return 42

        await await_if_needed(coro())

    @pytest.mark.asyncio
    async def test_await_none(self):
        await await_if_needed(None)

    @pytest.mark.asyncio
    async def test_await_sync_value(self):
        await await_if_needed(42)


class _E(Enum):
    A = "val_a"


@dataclass
class _D:
    x: int = 1


class _Obj:
    def __init__(self):
        self.x = 1
        self._private = 2


class TestToJsonable:
    def test_none(self):
        assert to_jsonable(None) is None

    def test_primitives(self):
        assert to_jsonable("str") == "str"
        assert to_jsonable(42) == 42
        assert to_jsonable(3.14) == 3.14
        assert to_jsonable(True) is True

    def test_dict(self):
        assert to_jsonable({"a": 1, "b": "two"}) == {"a": 1, "b": "two"}

    def test_list(self):
        assert to_jsonable([1, "two", 3]) == [1, "two", 3]

    def test_tuple_and_set(self):
        assert to_jsonable((1, 2)) == [1, 2]
        assert to_jsonable({3}) == [3]

    def test_enum(self):
        assert to_jsonable(_E.A) == "val_a"

    def test_pydantic_model(self):
        from pydantic import BaseModel

        class M(BaseModel):
            x: int = 1

        assert to_jsonable(M()) == {"x": 1}

    def test_dataclass(self):
        assert to_jsonable(_D()) == {"x": 1}

    def test_nested_dict(self):
        assert to_jsonable({"a": {"b": [1, 2]}}) == {"a": {"b": [1, 2]}}

    def test_object_with_dict(self):
        result = to_jsonable(_Obj())
        assert result == {"x": 1}
        assert "_private" not in result

    def test_fallback_to_str(self):
        obj = object()
        assert to_jsonable(obj) == str(obj)
