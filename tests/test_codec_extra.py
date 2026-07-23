# tests/test_codec_extra.py

"""Additional tests for codecs: serialize_tools, flush_stream block emission, wire_meta."""

from __future__ import annotations

import pytest

from commamatrix.components.dialog import DialogItem, DialogItemType, DialogRole
from commamatrix.components.hook import BeforeLlmCallCtx, RunCtx
from commamatrix.components.llm_adapter import (
    LLMResponseTextBlock,
    LLMResponseReasoningBlock,
    LLMResponseToolCallBlock,
    StopReason,
    Usage,
)
from commamatrix.components.tool import ToolDescriptor, ToolManager
from commamatrix.core.classes.manager import ServiceInstanceRegistry
from commamatrix.builtin.llm_http_adapter.codec import wire_meta
from commamatrix.builtin.llm_http_adapter.chat_completions import ChatCompletionsCodec
from commamatrix.builtin.llm_http_adapter.responses import ResponsesCodec
from commamatrix.builtin.llm_http_adapter.anthropic_messages import (
    AnthropicMessagesCodec,
)
from tests.conftest import StubOrigin, stub_origin, make_tool_descriptor


# ── Helpers ──────────────────────────────────────────────────────────────────


class FakeAgent:
    def __init__(self):
        self.services = ServiceInstanceRegistry()
        from commamatrix.components.config import Config

        self.config = Config()
        self.tool_manager = ToolManager(agent=self)


def _make_ctx(tools=None):
    agent = FakeAgent()
    run = RunCtx(agent=agent, origin=stub_origin(), user="u")
    return BeforeLlmCallCtx(run=run, dialog=[], tools=tools or [])


# ── wire_meta ────────────────────────────────────────────────────────────────


class TestWireMeta:
    def test_basic_structure(self):
        result = wire_meta("test.kind", {"key": "value"})
        assert result == {
            "llm": {"wire": {"kind": "test.kind", "value": {"key": "value"}}}
        }

    def test_with_extra_kwargs(self):
        result = wire_meta("test.kind", "val", field="reasoning_content")
        assert result == {
            "llm": {
                "wire": {
                    "kind": "test.kind",
                    "value": "val",
                    "field": "reasoning_content",
                }
            }
        }


# ── ChatCompletionsCodec.serialize_tools ─────────────────────────────────────


class TestChatCompletionsSerializeTools:
    def test_serialize_single_tool(self):
        codec = ChatCompletionsCodec()
        tool_desc = make_tool_descriptor(
            name="search",
            alias="web",
            doc="Search",
            schema={
                "type": "function",
                "description": "Search the web",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        )
        ctx = _make_ctx(tools=[tool_desc])
        result = codec.serialize_tools(ctx)

        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert "type" not in result[0]["function"]
        assert result[0]["function"]["name"] == "web_search"
        assert result[0]["function"]["description"] == "Search the web"

    def test_serialize_multiple_tools(self):
        codec = ChatCompletionsCodec()
        t1 = make_tool_descriptor(name="a", alias="mod")
        t2 = make_tool_descriptor(name="b", alias="mod")
        ctx = _make_ctx(tools=[t1, t2])
        result = codec.serialize_tools(ctx)

        assert len(result) == 2
        assert result[0]["function"]["name"] == "mod_a"
        assert result[1]["function"]["name"] == "mod_b"


# ── ResponsesCodec.serialize_tools ───────────────────────────────────────────


class TestResponsesSerializeTools:
    def test_serialize_single_tool(self):
        codec = ResponsesCodec()
        tool_desc = make_tool_descriptor(
            name="calc",
            alias="math",
            doc="Calculate",
            schema={
                "type": "function",
                "description": "Calculate",
                "parameters": {
                    "type": "object",
                    "properties": {"expr": {"type": "string"}},
                },
            },
        )
        ctx = _make_ctx(tools=[tool_desc])
        result = codec.serialize_tools(ctx)

        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["name"] == "math_calc"


# ── AnthropicMessagesCodec.serialize_tools ───────────────────────────────────


class TestAnthropicSerializeTools:
    def test_serialize_single_tool(self):
        codec = AnthropicMessagesCodec()
        tool_desc = make_tool_descriptor(
            name="search",
            alias="web",
            doc="Search",
            schema={
                "type": "function",
                "description": "Search",
                "parameters": {
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                },
            },
        )
        ctx = _make_ctx(tools=[tool_desc])
        result = codec.serialize_tools(ctx)

        assert len(result) == 1
        assert result[0]["name"] == "web_search"
        assert result[0]["description"] == "Search"
        assert result[0]["input_schema"] == {
            "type": "object",
            "properties": {"q": {"type": "string"}},
        }

    def test_serialize_no_description(self):
        codec = AnthropicMessagesCodec()
        tool_desc = make_tool_descriptor(
            name="fn",
            alias="mod",
            doc="",
            schema={
                "type": "function",
                "parameters": {"type": "object", "properties": {}},
            },
        )
        ctx = _make_ctx(tools=[tool_desc])
        result = codec.serialize_tools(ctx)

        assert result[0]["description"] == ""


# ── ChatCompletionsCodec.flush_stream block emission ─────────────────────────


class TestChatCompletionsFlushStream:
    def test_flush_text_block(self):
        codec = ChatCompletionsCodec()
        acc = {"text_buf": "Hello world", "stop_reason": StopReason.END_TURN}
        blocks, end = codec.flush_stream(acc)

        assert len(blocks) == 1
        assert isinstance(blocks[0], LLMResponseTextBlock)
        assert blocks[0].content == "Hello world"

    def test_flush_reasoning_block(self):
        codec = ChatCompletionsCodec()
        acc = {
            "reasoning_buf": "Let me think...",
            "reasoning_field": "reasoning_content",
            "stop_reason": StopReason.END_TURN,
        }
        blocks, end = codec.flush_stream(acc)

        assert len(blocks) == 1
        assert isinstance(blocks[0], LLMResponseReasoningBlock)
        assert blocks[0].content == "Let me think..."

    def test_flush_text_and_reasoning(self):
        codec = ChatCompletionsCodec()
        acc = {
            "text_buf": "Answer",
            "reasoning_buf": "Thinking",
            "reasoning_field": "reasoning_content",
            "stop_reason": StopReason.END_TURN,
        }
        blocks, end = codec.flush_stream(acc)

        assert len(blocks) == 2
        assert isinstance(blocks[0], LLMResponseReasoningBlock)
        assert isinstance(blocks[1], LLMResponseTextBlock)

    def test_flush_tool_calls(self):
        codec = ChatCompletionsCodec()
        acc = {
            "tool_calls": {
                0: {"id": "tc1", "name": "search", "args_buf": '{"q":"test"}'},
            },
            "stop_reason": StopReason.TOOL_USE,
        }
        blocks, end = codec.flush_stream(acc)

        tool_blocks = [b for b in blocks if isinstance(b, LLMResponseToolCallBlock)]
        assert len(tool_blocks) == 1
        assert tool_blocks[0].tool_call_id == "tc1"
        assert tool_blocks[0].tool_name == "search"
        assert tool_blocks[0].tool_args == {"q": "test"}

    def test_flush_multiple_tool_calls(self):
        codec = ChatCompletionsCodec()
        acc = {
            "tool_calls": {
                0: {"id": "tc1", "name": "a", "args_buf": '{"x":1}'},
                1: {"id": "tc2", "name": "b", "args_buf": '{"y":2}'},
            },
            "stop_reason": StopReason.TOOL_USE,
        }
        blocks, end = codec.flush_stream(acc)

        tool_blocks = [b for b in blocks if isinstance(b, LLMResponseToolCallBlock)]
        assert len(tool_blocks) == 2
        assert tool_blocks[0].tool_name == "a"
        assert tool_blocks[1].tool_name == "b"

    def test_flush_empty_acc(self):
        codec = ChatCompletionsCodec()
        blocks, end = codec.flush_stream({})

        assert blocks == []
        assert end.stop_reason == StopReason.END_TURN

    def test_flush_tool_call_with_invalid_json(self):
        codec = ChatCompletionsCodec()
        acc = {
            "tool_calls": {
                0: {"id": "tc1", "name": "fn", "args_buf": "not json"},
            },
            "stop_reason": StopReason.TOOL_USE,
        }
        blocks, end = codec.flush_stream(acc)

        tool_blocks = [b for b in blocks if isinstance(b, LLMResponseToolCallBlock)]
        assert len(tool_blocks) == 1
        assert tool_blocks[0].tool_args == {}  # fallback to empty dict


# ── AnthropicMessagesCodec.flush_stream block emission ───────────────────────


class TestAnthropicFlushStream:
    def test_flush_text_from_completed_blocks(self):
        codec = AnthropicMessagesCodec()
        acc = {
            "completed_blocks": [
                {"type": "text", "text_buf": "Hello"},
            ],
            "stop_reason": StopReason.END_TURN,
        }
        blocks, end = codec.flush_stream(acc)

        text_blocks = [b for b in blocks if isinstance(b, LLMResponseTextBlock)]
        assert len(text_blocks) == 1
        assert text_blocks[0].content == "Hello"

    def test_flush_thinking_from_completed_blocks(self):
        codec = AnthropicMessagesCodec()
        acc = {
            "completed_blocks": [
                {"type": "thinking", "text_buf": "Let me reason..."},
            ],
            "stop_reason": StopReason.END_TURN,
        }
        blocks, end = codec.flush_stream(acc)

        reasoning_blocks = [
            b for b in blocks if isinstance(b, LLMResponseReasoningBlock)
        ]
        assert len(reasoning_blocks) == 1
        assert reasoning_blocks[0].content == "Let me reason..."

    def test_flush_mixed_completed_blocks(self):
        codec = AnthropicMessagesCodec()
        acc = {
            "completed_blocks": [
                {"type": "thinking", "text_buf": "Reasoning"},
                {"type": "text", "text_buf": "Answer"},
            ],
            "stop_reason": StopReason.END_TURN,
        }
        blocks, end = codec.flush_stream(acc)

        assert len(blocks) == 2
        assert isinstance(blocks[0], LLMResponseReasoningBlock)
        assert isinstance(blocks[1], LLMResponseTextBlock)

    def test_flush_empty(self):
        codec = AnthropicMessagesCodec()
        blocks, end = codec.flush_stream({})

        assert blocks == []
        assert end.stop_reason == StopReason.END_TURN


# ── ResponsesCodec.flush_stream block emission ───────────────────────────────


class TestResponsesFlushStream:
    def test_flush_with_response_completed_output(self):
        codec = ResponsesCodec()
        acc = {
            "response": {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Hello"}],
                    },
                ],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
            "stop_reason": StopReason.END_TURN,
        }
        blocks, end = codec.flush_stream(acc)

        text_blocks = [b for b in blocks if isinstance(b, LLMResponseTextBlock)]
        assert len(text_blocks) == 1
        assert text_blocks[0].content == "Hello"

    def test_flush_with_reasoning_output(self):
        codec = ResponsesCodec()
        acc = {
            "response": {
                "status": "completed",
                "output": [
                    {
                        "type": "reasoning",
                        "summary": [{"type": "summary_text", "text": "I think..."}],
                    },
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Answer"}],
                    },
                ],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
            "stop_reason": StopReason.END_TURN,
        }
        blocks, end = codec.flush_stream(acc)

        reasoning_blocks = [
            b for b in blocks if isinstance(b, LLMResponseReasoningBlock)
        ]
        text_blocks = [b for b in blocks if isinstance(b, LLMResponseTextBlock)]
        assert len(reasoning_blocks) == 1
        assert reasoning_blocks[0].content == "I think..."
        assert len(text_blocks) == 1

    def test_flush_with_function_call_output(self):
        codec = ResponsesCodec()
        # function_call tool calls are yielded mid-stream in parse_stream_event,
        # not in flush_stream. flush_stream only handles reasoning and message types.
        # So function_call in response.output is not expected here.
        # Instead, test that message output is handled.
        acc = {
            "response": {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Answer"}],
                    },
                ],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
            "stop_reason": StopReason.END_TURN,
        }
        blocks, end = codec.flush_stream(acc)

        text_blocks = [b for b in blocks if isinstance(b, LLMResponseTextBlock)]
        assert len(text_blocks) == 1
        assert text_blocks[0].content == "Answer"

    def test_flush_empty(self):
        codec = ResponsesCodec()
        blocks, end = codec.flush_stream({})

        assert blocks == []
        assert end.stop_reason == StopReason.END_TURN


# ── LLMResponseFileBlock ─────────────────────────────────────────────────────


class TestLLMResponseFileBlock:
    def test_content_str(self):
        from commamatrix.components.llm_adapter import LLMResponseFileBlock

        block = LLMResponseFileBlock(ref="file_123", ext=".pdf")
        content = block.content_str()
        assert "file_123" in content
        assert ".pdf" in content

    def test_item_type(self):
        from commamatrix.components.llm_adapter import LLMResponseFileBlock

        block = LLMResponseFileBlock(ref="file_123", ext=".pdf")
        assert block.item_type() == DialogItemType.FILE_OUTPUT

    def test_to_dialog_item(self):
        from commamatrix.components.llm_adapter import LLMResponseFileBlock

        block = LLMResponseFileBlock(ref="file_123", ext=".pdf", meta={"key": "val"})
        item = block.to_dialog_item(
            role=DialogRole.ASSISTANT,
            user="u",
            origin=stub_origin(),
        )
        assert item.item_type == DialogItemType.FILE_OUTPUT
        assert item.meta == {"key": "val"}


# ── LLMResponseImageBlock ────────────────────────────────────────────────────


class TestLLMResponseImageBlock:
    def test_content_str(self):
        from commamatrix.components.llm_adapter import LLMResponseImageBlock

        block = LLMResponseImageBlock(ref="img_123", ext=".png")
        content = block.content_str()
        assert "img_123" in content
        assert ".png" in content

    def test_item_type(self):
        from commamatrix.components.llm_adapter import LLMResponseImageBlock

        block = LLMResponseImageBlock(ref="img_123", ext=".png")
        assert block.item_type() == DialogItemType.IMAGE_OUTPUT


# ── ToolCallResult ───────────────────────────────────────────────────────────


class TestToolCallResult:
    def test_aborted_factory(self):
        from commamatrix.components.llm_adapter import ToolCallResult

        result = ToolCallResult.aborted("tc1", "not allowed")
        assert result.tool_call_id == "tc1"
        assert result.abort is True
        assert "aborted" in result.content.lower()

    def test_dump_json(self):
        from commamatrix.components.llm_adapter import ToolCallResult

        result = ToolCallResult(tool_call_id="tc1", content=42)
        json_str = result.dump_json()
        assert '"tool_call_id": "tc1"' in json_str
        assert '"content": 42' in json_str
