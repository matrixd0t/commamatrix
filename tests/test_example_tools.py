# tests/test_example_tools.py

"""Tests for builtin example tools: calculator and web_search."""

from __future__ import annotations

import pytest

from commamatrix.components.tool import TOOL_ATTRIBUTE


class TestExampleTools:
    def test_calculator_has_tool_attribute(self):
        from commamatrix.builtin.example_tools import calculator
        assert hasattr(calculator, TOOL_ATTRIBUTE)
        meta = getattr(calculator, TOOL_ATTRIBUTE)
        assert meta["alias"] == "basic"

    def test_web_search_has_tool_attribute(self):
        from commamatrix.builtin.example_tools import web_search
        assert hasattr(web_search, TOOL_ATTRIBUTE)
        meta = getattr(web_search, TOOL_ATTRIBUTE)
        assert meta["alias"] == "advanced"
        assert meta["role"] == "admin"

    @pytest.mark.asyncio
    async def test_calculator_basic(self):
        from commamatrix.builtin.example_tools import calculator
        result = await calculator("2 + 2")
        assert result == 4

    @pytest.mark.asyncio
    async def test_calculator_error(self):
        from commamatrix.builtin.example_tools import calculator
        result = await calculator("1/0")
        assert "Error" in str(result)

    @pytest.mark.asyncio
    async def test_web_search(self):
        from commamatrix.builtin.example_tools import web_search
        result = await web_search()
        assert "San Francisco" in result or "cloudy" in result
