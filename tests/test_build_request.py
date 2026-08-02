# tests/test_build_request.py

"""Tests for codec build_request() — dialog-to-wire serialization for all 3 protocols."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from commamatrix.components.dialog import DialogItem, DialogItemType, DialogRole
from commamatrix.components.hook import BeforeLlmCallCtx, RunCtx
from commamatrix.components.tool import ToolDescriptor
from commamatrix.core.classes.manager import ServiceInstanceRegistry
from commamatrix.builtin.llm_http_adapter.chat_completions import ChatCompletionsCodec
from commamatrix.builtin.llm_http_adapter.responses import ResponsesCodec
from commamatrix.builtin.llm_http_adapter.anthropic_messages import AnthropicMessagesCodec
from tests.conftest import StubOrigin, stub_origin, make_dialog_item, make_tool_descriptor


# ── Helpers ──────────────────────────────────────────────────────────────────


class FakeAgent:
    def __init__(self):
        self.services = ServiceInstanceRegistry()
        from commamatrix.components.config import Config
        self.config = Config()
        from commamatrix.components.tool import ToolManager
        self.tool_manager = ToolManager(agent=self)


def _make_ctx(
    dialog: list[DialogItem],
    tools: list[ToolDescriptor] | None = None,
    llm_call_params: dict[str, Any] | None = None,
) -> BeforeLlmCallCtx:
    agent = FakeAgent()
    run = RunCtx(agent=agent, origin=stub_origin(), user="test_user")
    return BeforeLlmCallCtx(
        run=run,
        dialog=dialog,
        tools=tools or [],
        llm_call_params=llm_call_params or {},
    )


# ── ChatCompletionsCodec.build_request ───────────────────────────────────────


class TestChatCompletionsBuildRequest:
    @pytest.mark.asyncio
    async def test_input_message(self):
        codec = ChatCompletionsCodec()
        dialog = [make_dialog_item("Hello", role=DialogRole.USER)]
        ctx = _make_ctx(dialog)
        req = await codec.build_request(model="gpt-4", ctx=ctx)

        assert req["model"] == "gpt-4"
        assert len(req["messages"]) == 1
        assert req["messages"][0] == {"role": "user", "content": "Hello"}

    @pytest.mark.asyncio
    async def test_system_message(self):
        codec = ChatCompletionsCodec()
        dialog = [make_dialog_item("Be helpful", role=DialogRole.SYSTEM, item_type=DialogItemType.INPUT)]
        ctx = _make_ctx(dialog)
        req = await codec.build_request(model="gpt-4", ctx=ctx)

        assert req["messages"][0]["role"] == "system"

    @pytest.mark.asyncio
    async def test_assistant_output(self):
        codec = ChatCompletionsCodec()
        dialog = [
            make_dialog_item("Hi", role=DialogRole.USER),
            make_dialog_item("Hello!", role=DialogRole.ASSISTANT, item_type=DialogItemType.OUTPUT),
        ]
        ctx = _make_ctx(dialog)
        req = await codec.build_request(model="gpt-4", ctx=ctx)

        assert len(req["messages"]) == 2
        assert req["messages"][1] == {"role": "assistant", "content": "Hello!"}

    @pytest.mark.asyncio
    async def test_tool_call_block(self):
        codec = ChatCompletionsCodec()
        tool_content = '{"tool_call_id": "tc1", "tool_name": "add", "tool_args": {"a": 1}}'
        dialog = [
            make_dialog_item("Calculate", role=DialogRole.USER),
            make_dialog_item(tool_content, role=DialogRole.ASSISTANT, item_type=DialogItemType.TOOL_CALL),
        ]
        ctx = _make_ctx(dialog)
        req = await codec.build_request(model="gpt-4", ctx=ctx)

        assistant = req["messages"][1]
        assert assistant["role"] == "assistant"
        assert len(assistant["tool_calls"]) == 1
        assert assistant["tool_calls"][0]["id"] == "tc1"
        assert assistant["tool_calls"][0]["function"]["name"] == "add"

    @pytest.mark.asyncio
    async def test_tool_call_result(self):
        codec = ChatCompletionsCodec()
        result_content = '{"tool_call_id": "tc1", "content": 42}'
        dialog = [
            make_dialog_item("Calculate", role=DialogRole.USER),
            make_dialog_item(result_content, role=DialogRole.TOOL, item_type=DialogItemType.TOOL_CALL_RESULT),
        ]
        ctx = _make_ctx(dialog)
        req = await codec.build_request(model="gpt-4", ctx=ctx)

        assert req["messages"][1]["role"] == "tool"
        assert req["messages"][1]["tool_call_id"] == "tc1"
        assert req["messages"][1]["content"] == "42"

    @pytest.mark.asyncio
    async def test_reasoning_block_without_wire(self):
        codec = ChatCompletionsCodec()
        dialog = [
            make_dialog_item("Think", role=DialogRole.USER),
            make_dialog_item("reasoning text", role=DialogRole.ASSISTANT, item_type=DialogItemType.REASONING),
        ]
        ctx = _make_ctx(dialog)
        req = await codec.build_request(model="gpt-4", ctx=ctx)

        # Reasoning without wire metadata is skipped
        assert len(req["messages"]) == 1

    @pytest.mark.asyncio
    async def test_multiple_assistant_outputs_merged(self):
        codec = ChatCompletionsCodec()
        dialog = [
            make_dialog_item("Hi", role=DialogRole.USER),
            make_dialog_item("Part 1", role=DialogRole.ASSISTANT, item_type=DialogItemType.OUTPUT),
            make_dialog_item("Part 2", role=DialogRole.ASSISTANT, item_type=DialogItemType.OUTPUT),
        ]
        ctx = _make_ctx(dialog)
        req = await codec.build_request(model="gpt-4", ctx=ctx)

        # Two consecutive assistant outputs should be merged
        assistant = req["messages"][1]
        assert assistant["content"] == "Part 1Part 2"

    @pytest.mark.asyncio
    async def test_llm_call_params_included(self):
        codec = ChatCompletionsCodec()
        dialog = [make_dialog_item("Hi", role=DialogRole.USER)]
        ctx = _make_ctx(dialog, llm_call_params={"temperature": 0.5, "max_tokens": 100})
        req = await codec.build_request(model="gpt-4", ctx=ctx)

        assert req["temperature"] == 0.5
        assert req["max_tokens"] == 100

    @pytest.mark.asyncio
    async def test_with_tools(self):
        codec = ChatCompletionsCodec()
        dialog = [make_dialog_item("Hi", role=DialogRole.USER)]
        tool_desc = make_tool_descriptor(name="search", alias="web", doc="Search the web", schema={
            "type": "function",
            "description": "Search the web",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        })
        ctx = _make_ctx(dialog, tools=[tool_desc])
        req = await codec.build_request(model="gpt-4", ctx=ctx)

        assert "tools" in req
        assert len(req["tools"]) == 1
        assert req["tools"][0]["type"] == "function"
        assert req["tools"][0]["function"]["name"] == "web_search"

    @pytest.mark.asyncio
    async def test_empty_dialog(self):
        codec = ChatCompletionsCodec()
        ctx = _make_ctx([])
        req = await codec.build_request(model="gpt-4", ctx=ctx)

        assert req["messages"] == []


# ── ResponsesCodec.build_request ─────────────────────────────────────────────


class TestResponsesBuildRequest:
    @pytest.mark.asyncio
    async def test_input_message(self):
        codec = ResponsesCodec()
        dialog = [make_dialog_item("Hello", role=DialogRole.USER)]
        ctx = _make_ctx(dialog)
        req = await codec.build_request(model="o3", ctx=ctx)

        assert req["model"] == "o3"
        assert len(req["input"]) == 1
        assert req["input"][0] == {"role": "user", "content": "Hello"}

    @pytest.mark.asyncio
    async def test_assistant_output(self):
        codec = ResponsesCodec()
        dialog = [
            make_dialog_item("Hi", role=DialogRole.USER),
            make_dialog_item("Hello!", role=DialogRole.ASSISTANT, item_type=DialogItemType.OUTPUT),
        ]
        ctx = _make_ctx(dialog)
        req = await codec.build_request(model="o3", ctx=ctx)

        assert len(req["input"]) == 2
        assert req["input"][1] == {"role": "assistant", "content": "Hello!"}

    @pytest.mark.asyncio
    async def test_tool_call_result(self):
        codec = ResponsesCodec()
        result_content = '{"tool_call_id": "tc1", "content": 42}'
        dialog = [
            make_dialog_item(result_content, role=DialogRole.TOOL, item_type=DialogItemType.TOOL_CALL_RESULT),
        ]
        ctx = _make_ctx(dialog)
        req = await codec.build_request(model="o3", ctx=ctx)

        assert req["input"][0]["type"] == "function_call_output"
        assert req["input"][0]["call_id"] == "tc1"
        assert req["input"][0]["output"] == "42"

    @pytest.mark.asyncio
    async def test_tool_call_without_wire(self):
        codec = ResponsesCodec()
        tool_content = '{"tool_call_id": "tc1", "tool_name": "add", "tool_args": {"a": 1}}'
        dialog = [
            make_dialog_item(tool_content, role=DialogRole.ASSISTANT, item_type=DialogItemType.TOOL_CALL),
        ]
        ctx = _make_ctx(dialog)
        req = await codec.build_request(model="o3", ctx=ctx)

        assert req["input"][0]["type"] == "function_call"
        assert req["input"][0]["call_id"] == "tc1"
        assert req["input"][0]["name"] == "add"

    @pytest.mark.asyncio
    async def test_system_message(self):
        codec = ResponsesCodec()
        dialog = [make_dialog_item("Be helpful", role=DialogRole.SYSTEM, item_type=DialogItemType.INPUT)]
        ctx = _make_ctx(dialog)
        req = await codec.build_request(model="o3", ctx=ctx)

        assert req["input"][0]["role"] == "system"

    @pytest.mark.asyncio
    async def test_with_tools(self):
        codec = ResponsesCodec()
        dialog = [make_dialog_item("Hi", role=DialogRole.USER)]
        tool_desc = make_tool_descriptor(name="calc", alias="math", doc="Calculate", schema={
            "type": "function",
            "description": "Calculate",
            "parameters": {"type": "object", "properties": {"expr": {"type": "string"}}, "required": ["expr"]},
        })
        ctx = _make_ctx(dialog, tools=[tool_desc])
        req = await codec.build_request(model="o3", ctx=ctx)

        assert "tools" in req
        assert len(req["tools"]) == 1


# ── AnthropicMessagesCodec.build_request ─────────────────────────────────────


class TestAnthropicBuildRequest:
    @pytest.mark.asyncio
    async def test_input_message(self):
        codec = AnthropicMessagesCodec()
        dialog = [make_dialog_item("Hello", role=DialogRole.USER)]
        ctx = _make_ctx(dialog)
        req = await codec.build_request(model="claude-3", ctx=ctx)

        assert req["model"] == "claude-3"
        assert len(req["messages"]) == 1
        assert req["messages"][0] == {"role": "user", "content": "Hello"}

    @pytest.mark.asyncio
    async def test_system_message_extracted(self):
        codec = AnthropicMessagesCodec()
        dialog = [
            make_dialog_item("Be helpful", role=DialogRole.SYSTEM, item_type=DialogItemType.INPUT),
            make_dialog_item("Hi", role=DialogRole.USER),
        ]
        ctx = _make_ctx(dialog)
        req = await codec.build_request(model="claude-3", ctx=ctx)

        assert req["system"] == "Be helpful"
        assert len(req["messages"]) == 1
        assert req["messages"][0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_multiple_system_messages_joined(self):
        codec = AnthropicMessagesCodec()
        dialog = [
            make_dialog_item("Rule 1", role=DialogRole.SYSTEM, item_type=DialogItemType.INPUT),
            make_dialog_item("Rule 2", role=DialogRole.SYSTEM, item_type=DialogItemType.INPUT),
            make_dialog_item("Hi", role=DialogRole.USER),
        ]
        ctx = _make_ctx(dialog)
        req = await codec.build_request(model="claude-3", ctx=ctx)

        assert req["system"] == "Rule 1\n\nRule 2"

    @pytest.mark.asyncio
    async def test_assistant_output(self):
        codec = AnthropicMessagesCodec()
        dialog = [
            make_dialog_item("Hi", role=DialogRole.USER),
            make_dialog_item("Hello!", role=DialogRole.ASSISTANT, item_type=DialogItemType.OUTPUT),
        ]
        ctx = _make_ctx(dialog)
        req = await codec.build_request(model="claude-3", ctx=ctx)

        assert len(req["messages"]) == 2
        assert req["messages"][1]["role"] == "assistant"
        assert req["messages"][1]["content"] == {"type": "text", "text": "Hello!"}

    @pytest.mark.asyncio
    async def test_tool_call_without_wire(self):
        codec = AnthropicMessagesCodec()
        tool_content = '{"tool_call_id": "tc1", "tool_name": "search", "tool_args": {"q": "test"}}'
        dialog = [
            make_dialog_item("Search", role=DialogRole.USER),
            make_dialog_item(tool_content, role=DialogRole.ASSISTANT, item_type=DialogItemType.TOOL_CALL),
        ]
        ctx = _make_ctx(dialog)
        req = await codec.build_request(model="claude-3", ctx=ctx)

        assistant = req["messages"][1]
        assert assistant["role"] == "assistant"
        # Single tool_use content is a dict, not a list
        assert assistant["content"]["type"] == "tool_use"
        assert assistant["content"]["id"] == "tc1"
        assert assistant["content"]["name"] == "search"

    @pytest.mark.asyncio
    async def test_tool_call_result(self):
        codec = AnthropicMessagesCodec()
        result_content = '{"tool_call_id": "tc1", "content": "result_data"}'
        dialog = [
            make_dialog_item(result_content, role=DialogRole.USER, item_type=DialogItemType.TOOL_CALL_RESULT),
        ]
        ctx = _make_ctx(dialog)
        req = await codec.build_request(model="claude-3", ctx=ctx)

        assert req["messages"][0]["role"] == "user"
        assert req["messages"][0]["content"]["type"] == "tool_result"
        assert req["messages"][0]["content"]["tool_use_id"] == "tc1"

    @pytest.mark.asyncio
    async def test_reasoning_without_wire_skipped(self):
        codec = AnthropicMessagesCodec()
        dialog = [
            make_dialog_item("reasoning text", role=DialogRole.ASSISTANT, item_type=DialogItemType.REASONING),
        ]
        ctx = _make_ctx(dialog)
        req = await codec.build_request(model="claude-3", ctx=ctx)

        # Reasoning without wire is skipped
        assert len(req["messages"]) == 0

    @pytest.mark.asyncio
    async def test_consecutive_assistant_messages_merged(self):
        codec = AnthropicMessagesCodec()
        dialog = [
            make_dialog_item("Part 1", role=DialogRole.ASSISTANT, item_type=DialogItemType.OUTPUT),
            make_dialog_item("Part 2", role=DialogRole.ASSISTANT, item_type=DialogItemType.OUTPUT),
        ]
        ctx = _make_ctx(dialog)
        req = await codec.build_request(model="claude-3", ctx=ctx)

        # Should be merged into one message with list content
        assert len(req["messages"]) == 1
        assert req["messages"][0]["role"] == "assistant"
        assert isinstance(req["messages"][0]["content"], list)
        assert len(req["messages"][0]["content"]) == 2

    @pytest.mark.asyncio
    async def test_with_tools(self):
        codec = AnthropicMessagesCodec()
        dialog = [make_dialog_item("Hi", role=DialogRole.USER)]
        tool_desc = make_tool_descriptor(name="search", alias="web", doc="Search", schema={
            "type": "function",
            "description": "Search",
            "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
        })
        ctx = _make_ctx(dialog, tools=[tool_desc])
        req = await codec.build_request(model="claude-3", ctx=ctx)

        assert "tools" in req
        assert len(req["tools"]) == 1
        assert req["tools"][0]["name"] == "web_search"
        assert req["tools"][0]["input_schema"] == {"type": "object", "properties": {"q": {"type": "string"}}}

    @pytest.mark.asyncio
    async def test_no_system_key_when_empty(self):
        codec = AnthropicMessagesCodec()
        dialog = [make_dialog_item("Hi", role=DialogRole.USER)]
        ctx = _make_ctx(dialog)
        req = await codec.build_request(model="claude-3", ctx=ctx)

        assert "system" not in req

    @pytest.mark.asyncio
    async def test_llm_call_params(self):
        codec = AnthropicMessagesCodec()
        dialog = [make_dialog_item("Hi", role=DialogRole.USER)]
        ctx = _make_ctx(dialog, llm_call_params={"max_tokens": 1024, "temperature": 0.7})
        req = await codec.build_request(model="claude-3", ctx=ctx)

        assert req["max_tokens"] == 1024
        assert req["temperature"] == 0.7
