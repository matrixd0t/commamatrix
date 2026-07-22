# tests/test_llm_adapter.py

"""Tests for LLMAdapter, LLMAdapterManager, LLMResponse blocks, ToolCall, ToolCallResult."""

from __future__ import annotations

import pytest

from commamatrix.components.llm_adapter import (
    LLM_ADAPTER_ATTRIBUTE,
    LLMAdapter,
    LLMAdapterManager,
    LLMResponse,
    LLMResponseError,
    LLMResponseImageBlock,
    LLMResponseReasoningBlock,
    LLMResponseTextBlock,
    LLMResponseToolCallBlock,
    LLMTruncatedError,
    StopReason,
    ToolCall,
    ToolCallResult,
    Usage,
)
from commamatrix.components.dialog import DialogItemType, DialogRole
from commamatrix.core.classes.manager import ServiceInstanceRegistry
from tests.conftest import stub_agent, stub_origin


class TestToolCall:
    def test_dump_json(self):
        tc = ToolCall(tool_call_id="tc1", tool_name="fn", tool_args={"x": 1})
        j = tc.dump_json()
        assert '"tool_call_id": "tc1"' in j
        assert '"tool_name": "fn"' in j


class TestToolCallResult:
    def test_aborted(self):
        r = ToolCallResult.aborted("tc1", "denied")
        assert r.abort is True
        assert "denied" in r.content

    def test_dump_json(self):
        r = ToolCallResult(tool_call_id="tc1", content="ok")
        j = r.dump_json()
        assert '"tool_call_id": "tc1"' in j
        assert '"content": "ok"' in j


class TestStopReason:
    def test_values(self):
        assert StopReason.END_TURN == "end_turn"
        assert StopReason.TOOL_USE == "tool_use"
        assert StopReason.LENGTH == "length"
        assert StopReason.ERROR == "error"


class TestUsage:
    def test_defaults(self):
        u = Usage(input_tokens=10, output_tokens=5)
        assert u.cache_read_tokens == 0
        assert u.cache_write_tokens == 0
        assert u.reasoning_tokens == 0


class TestLLMResponseBlocks:
    def test_text_block(self):
        block = LLMResponseTextBlock(content="hello")
        assert block.content_str() == "hello"
        assert block.item_type() == DialogItemType.OUTPUT

    def test_reasoning_block(self):
        block = LLMResponseReasoningBlock(content="thinking...")
        assert block.content_str() == "thinking..."
        assert block.item_type() == DialogItemType.REASONING

    def test_image_block(self):
        block = LLMResponseImageBlock(ref="img1", ext="png")
        s = block.content_str()
        assert "img1" in s
        assert block.item_type() == DialogItemType.IMAGE_OUTPUT

    def test_tool_call_block(self):
        block = LLMResponseToolCallBlock(
            tool_call_id="tc1", tool_name="fn", tool_args={"a": 1}
        )
        s = block.content_str()
        assert "tc1" in s
        assert block.item_type() == DialogItemType.TOOL_CALL

    def test_to_dialog_item(self):
        origin = stub_origin()
        block = LLMResponseTextBlock(content="hi", meta={"k": "v"})
        item = block.to_dialog_item(
            role=DialogRole.ASSISTANT,
            user="u1",
            origin=origin,
            previous_item_id=42,
        )
        assert item.content == "hi"
        assert item.role == DialogRole.ASSISTANT
        assert item.user == "u1"
        assert item.origin == origin
        assert item.previous_item_id == 42
        assert item.meta == {"k": "v"}


class TestLLMResponse:
    def test_defaults(self):
        r = LLMResponse()
        assert r.stop_reason == StopReason.END_TURN
        assert r.content == []
        assert r.usage is None

    def test_with_content(self):
        r = LLMResponse(
            content=[LLMResponseTextBlock(content="ok")],
            stop_reason=StopReason.END_TURN,
        )
        assert len(r.content) == 1


class TestLLMAdapterSubclass:
    def test_stamps_attribute(self):
        class MyAdapter(LLMAdapter):
            async def ask_llm(self, ctx):
                return LLMResponse()
        assert getattr(MyAdapter, LLM_ADAPTER_ATTRIBUTE, False) is True

    def test_abstract_not_stamped(self):
        assert getattr(LLMAdapter, LLM_ADAPTER_ATTRIBUTE, False) is False


class TestLLMAdapterManager:
    def test_no_adapters_raises(self):
        agent = stub_agent()
        mgr = LLMAdapterManager(agent=agent)
        with pytest.raises(RuntimeError, match="No LLM adapters"):
            _ = mgr._active
