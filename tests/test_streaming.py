# tests/test_streaming.py

"""Tests for streaming support: StreamDelta, StreamEnd, codec streaming methods,
SSE parsing, connector streaming interface."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from commamatrix.components.llm_adapter import (
    LLMAdapter,
    LLMAdapterManager,
    LLMResponse,
    LLMResponseBlock,
    LLMResponseTextBlock,
    LLMResponseToolCallBlock,
    LLMResponseReasoningBlock,
    StopReason,
    StreamDelta,
    StreamEnd,
    Usage,
)
from commamatrix.components.connector import Connector
from commamatrix.components.dialog import DialogOrigin
from commamatrix.builtin.llm_http_adapter.codec import ApiCodec
from commamatrix.builtin.llm_http_adapter.chat_completions import ChatCompletionsCodec
from commamatrix.builtin.llm_http_adapter.responses import ResponsesCodec
from commamatrix.builtin.llm_http_adapter.anthropic_messages import AnthropicMessagesCodec
from commamatrix.builtin.llm_http_adapter.adapter import LLMHTTPAdapter
from tests.conftest import stub_agent, stub_origin


# ── StreamDelta / StreamEnd ──────────────────────────────────────────────────


class TestStreamDelta:
    def test_construction(self):
        d = StreamDelta(content="hello", delta_type="text")
        assert d.content == "hello"
        assert d.delta_type == "text"
        assert d.meta == {}

    def test_construction_with_meta(self):
        d = StreamDelta(content="x", delta_type="reasoning", meta={"k": "v"})
        assert d.meta == {"k": "v"}

    def test_reasoning_delta(self):
        d = StreamDelta(content="thinking...", delta_type="reasoning")
        assert d.delta_type == "reasoning"


class TestStreamEnd:
    def test_defaults(self):
        e = StreamEnd()
        assert e.stop_reason == StopReason.END_TURN
        assert e.usage is None
        assert e.meta == {}

    def test_with_usage(self):
        usage = Usage(input_tokens=10, output_tokens=5)
        e = StreamEnd(stop_reason=StopReason.TOOL_USE, usage=usage, meta={"p": 1})
        assert e.stop_reason == StopReason.TOOL_USE
        assert e.usage.input_tokens == 10
        assert e.meta == {"p": 1}


# ── LLMAdapter.ask_llm raises NotImplementedError ────────────────────────────


class TestLLMAdapterStreaming:
    def test_ask_llm_raises_not_implemented(self):
        class MinimalAdapter(LLMAdapter):
            pass

        agent = stub_agent()
        adapter = MinimalAdapter(agent=agent)
        with pytest.raises(NotImplementedError):
            import asyncio
            async def _consume():
                async for _ in adapter.ask_llm(MagicMock()):
                    pass
            asyncio.run(_consume())


# ── LLMAdapterManager passthrough ────────────────────────────────────────────


class TestLLMAdapterManagerStreaming:
    def test_ask_llm_delegates_stream_flag(self):
        agent = stub_agent()
        mgr = LLMAdapterManager(agent=agent)
        mock_adapter = MagicMock(spec=LLMAdapter)
        mock_adapter.ask_llm = MagicMock(return_value=iter([]))
        mock_desc_id = "llm_adapter://test/TestAdapter"
        mgr._instances = {mock_desc_id: mock_adapter}
        mgr._start_order = [mock_desc_id]
        ctx = MagicMock()
        mgr.ask_llm(ctx, stream=True)
        mock_adapter.ask_llm.assert_called_once_with(ctx, stream=True)


# ── Connector streaming interface ────────────────────────────────────────────


class TestConnectorStreaming:
    def test_supports_streaming_default_false(self):
        assert Connector.supports_streaming is False

    @pytest.mark.asyncio
    async def test_send_stream_chunk_default_noop(self):
        class MinimalConnector(Connector):
            async def parse(self, data):
                return None
            async def send(self, origin, item):
                return ""

        agent = stub_agent()
        conn = MinimalConnector(agent=agent)
        chunk = StreamDelta(content="test", delta_type="text")
        await conn.send_stream_chunk(stub_origin(), chunk)

    def test_http_connector_supports_streaming_true(self):
        from commamatrix.builtin.http_connector.connector import HttpConnector

        connector = HttpConnector(agent=stub_agent())
        assert connector.supports_streaming is True
        token = connector._request_streaming.set(False)
        try:
            assert connector.supports_streaming is False
        finally:
            connector._request_streaming.reset(token)


# ── ApiCodec streaming base ──────────────────────────────────────────────────


class TestApiCodecStreaming:
    def test_can_stream_default_false(self):
        assert ApiCodec.can_stream is False

    def test_enable_streaming_default(self):
        codec = ChatCompletionsCodec()
        body = {"llm": "gpt-4"}
        result = codec.enable_streaming(body)
        assert result["stream"] is True

    def test_parse_stream_event_raises_for_unsupported_codec(self):
        class StubCodec(ApiCodec):
            protocol = "stub"
            endpoint = "/stub"
            async def build_request(self, *, model, ctx):
                return {}
            def parse_response(self, body):
                return LLMResponse()
            @staticmethod
            def serialize_tools(ctx):
                return []

        codec = StubCodec()
        with pytest.raises(NotImplementedError):
            codec.parse_stream_event(None, {}, {})

    def test_flush_stream_raises_for_unsupported_codec(self):
        class StubCodec2(ApiCodec):
            protocol = "stub2"
            endpoint = "/stub2"
            async def build_request(self, *, model, ctx):
                return {}
            def parse_response(self, body):
                return LLMResponse()
            @staticmethod
            def serialize_tools(ctx):
                return []

        codec = StubCodec2()
        with pytest.raises(NotImplementedError):
            codec.flush_stream({})


# ── ChatCompletionsCodec streaming ───────────────────────────────────────────


class TestChatCompletionsCodecStreaming:
    def test_can_stream_true(self):
        assert ChatCompletionsCodec().can_stream is True

    def test_enable_streaming_includes_stream_options(self):
        codec = ChatCompletionsCodec()
        body = codec.enable_streaming({"llm": "gpt-4"})
        assert body["stream"] is True
        assert body["stream_options"] == {"include_usage": True}

    def test_parse_text_delta(self):
        codec = ChatCompletionsCodec()
        acc: dict = {}
        data = {"choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]}
        result = codec.parse_stream_event(None, data, acc)
        assert isinstance(result, StreamDelta)
        assert result.content == "Hello"
        assert result.delta_type == "text"

    def test_parse_reasoning_content_delta(self):
        codec = ChatCompletionsCodec()
        acc: dict = {}
        data = {"choices": [{"delta": {"reasoning_content": "thinking..."}, "finish_reason": None}]}
        result = codec.parse_stream_event(None, data, acc)
        assert isinstance(result, StreamDelta)
        assert result.content == "thinking..."
        assert result.delta_type == "reasoning"

    def test_parse_reasoning_field_delta(self):
        codec = ChatCompletionsCodec()
        acc: dict = {}
        data = {"choices": [{"delta": {"reasoning": "deep thought"}, "finish_reason": None}]}
        result = codec.parse_stream_event(None, data, acc)
        assert isinstance(result, StreamDelta)
        assert result.content == "deep thought"
        assert result.delta_type == "reasoning"

    def test_parse_tool_call_delta(self):
        codec = ChatCompletionsCodec()
        acc: dict = {}
        data = {
            "choices": [{"delta": {"tool_calls": [{"index": 0, "id": "tc1", "function": {"name": "fn"}}]}, "finish_reason": None}]
        }
        result = codec.parse_stream_event(None, data, acc)
        assert isinstance(result, StreamDelta)
        assert result.delta_type == "tool_call"
        assert result.content == ""
        assert result.meta["tool_name"] == "fn"
        assert acc["tool_calls"][0]["id"] == "tc1"
        assert acc["tool_calls"][0]["name"] == "fn"

    def test_parse_tool_call_arguments_incremental(self):
        codec = ChatCompletionsCodec()
        acc: dict = {}
        codec.parse_stream_event(None, {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "tc1", "function": {"name": "fn", "arguments": "{\"x\":"}}]}, "finish_reason": None}]}, acc)
        codec.parse_stream_event(None, {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": " 1}"}}]}, "finish_reason": None}]}, acc)
        assert acc["tool_calls"][0]["args_buf"] == "{\"x\": 1}"

    def test_parse_finish_reason_sets_acc(self):
        codec = ChatCompletionsCodec()
        acc: dict = {}
        data = {"choices": [{"delta": {}, "finish_reason": "stop"}]}
        result = codec.parse_stream_event(None, data, acc)
        assert result is None
        assert acc["stop_reason"] == StopReason.END_TURN

    def test_parse_finish_reason_tool_calls(self):
        codec = ChatCompletionsCodec()
        acc: dict = {"tool_calls": {0: {"id": "tc1", "name": "fn", "args_buf": '{"x": 1}'}}}
        data = {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}
        codec.parse_stream_event(None, data, acc)
        assert acc["stop_reason"] == StopReason.TOOL_USE

    def test_parse_finish_reason_length(self):
        codec = ChatCompletionsCodec()
        acc: dict = {}
        data = {"choices": [{"delta": {}, "finish_reason": "length"}]}
        codec.parse_stream_event(None, data, acc)
        assert acc["stop_reason"] == StopReason.LENGTH

    def test_parse_usage_chunk(self):
        codec = ChatCompletionsCodec()
        acc: dict = {}
        data = {"usage": {"prompt_tokens": 100, "completion_tokens": 50}}
        result = codec.parse_stream_event(None, data, acc)
        assert result is None
        assert acc["usage"].input_tokens == 100
        assert acc["usage"].output_tokens == 50

    def test_parse_stores_response_id_and_model(self):
        codec = ChatCompletionsCodec()
        acc: dict = {}
        data = {"id": "resp-123", "llm": "gpt-4", "choices": [{"delta": {"content": "x"}, "finish_reason": None}]}
        codec.parse_stream_event(None, data, acc)
        assert acc["response_id"] == "resp-123"
        assert acc["llm"] == "gpt-4"

    def test_flush_stream(self):
        codec = ChatCompletionsCodec()
        acc = {"stop_reason": StopReason.TOOL_USE, "usage": Usage(input_tokens=10, output_tokens=5), "llm": "gpt-4", "response_id": "r1"}
        blocks, end = codec.flush_stream(acc)
        assert isinstance(end, StreamEnd)
        assert end.stop_reason == StopReason.TOOL_USE
        assert end.usage.input_tokens == 10

    def test_flush_stream_defaults(self):
        codec = ChatCompletionsCodec()
        blocks, end = codec.flush_stream({})
        assert end.stop_reason == StopReason.END_TURN
        assert end.usage is None


# ── ResponsesCodec streaming ─────────────────────────────────────────────────


class TestResponsesCodecStreaming:
    def test_can_stream_true(self):
        assert ResponsesCodec().can_stream is True

    def test_parse_text_delta(self):
        codec = ResponsesCodec()
        acc: dict = {}
        data = {"type": "response.output_text.delta", "delta": "Hello"}
        result = codec.parse_stream_event(None, data, acc)
        assert isinstance(result, StreamDelta)
        assert result.content == "Hello"
        assert result.delta_type == "text"

    def test_parse_reasoning_delta(self):
        codec = ResponsesCodec()
        acc: dict = {}
        data = {"type": "response.reasoning_summary_text.delta", "delta": "thinking..."}
        result = codec.parse_stream_event(None, data, acc)
        assert isinstance(result, StreamDelta)
        assert result.content == "thinking..."
        assert result.delta_type == "reasoning"

    def test_parse_function_call_arguments_delta(self):
        codec = ResponsesCodec()
        acc: dict = {}
        data = {"type": "response.function_call_arguments.delta", "item_id": "fc1", "delta": '{"x":'}
        result = codec.parse_stream_event(None, data, acc)
        assert isinstance(result, StreamDelta)
        assert result.delta_type == "tool_call"
        assert result.content == '{"x":'
        assert result.meta["tool_call_id"] == "fc1"
        assert acc["tool_calls"]["fc1"]["args_buf"] == '{"x":'

    def test_parse_output_item_done_function_call(self):
        codec = ResponsesCodec()
        acc: dict = {"tool_calls": {"fc1": {"args_buf": '{"x": 1}'}}}
        data = {"type": "response.output_item.done", "item": {"type": "function_call", "id": "fc1", "call_id": "tc1", "name": "fn"}}
        result = codec.parse_stream_event(None, data, acc)
        assert isinstance(result, LLMResponseToolCallBlock)
        assert result.tool_call_id == "tc1"
        assert result.tool_name == "fn"
        assert result.tool_args == {"x": 1}

    def test_parse_output_item_done_message(self):
        codec = ResponsesCodec()
        acc: dict = {}
        data = {"type": "response.output_item.done", "item": {"type": "message"}}
        result = codec.parse_stream_event(None, data, acc)
        assert result is None

    def test_parse_response_created_stores_id(self):
        codec = ResponsesCodec()
        acc: dict = {}
        data = {"type": "response.created", "response": {"id": "resp-1", "llm": "o3"}}
        codec.parse_stream_event(None, data, acc)
        assert acc["response_id"] == "resp-1"
        assert acc["llm"] == "o3"

    def test_parse_response_completed_stores_response(self):
        codec = ResponsesCodec()
        acc: dict = {}
        resp_obj = {"id": "r1", "status": "completed", "usage": {"input_tokens": 10, "output_tokens": 5}}
        data = {"type": "response.completed", "response": resp_obj}
        codec.parse_stream_event(None, data, acc)
        assert acc["response"] == resp_obj

    def test_flush_stream_completed(self):
        codec = ResponsesCodec()
        acc = {"response_id": "r1", "llm": "o3", "response": {"status": "completed", "usage": {"input_tokens": 10, "output_tokens": 5}}}
        blocks, end = codec.flush_stream(acc)
        assert end.stop_reason == StopReason.END_TURN
        assert end.usage.input_tokens == 10

    def test_flush_stream_incomplete(self):
        codec = ResponsesCodec()
        acc = {"response": {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}}
        blocks, end = codec.flush_stream(acc)
        assert end.stop_reason == StopReason.LENGTH

    def test_parse_unknown_event_returns_none(self):
        codec = ResponsesCodec()
        assert codec.parse_stream_event(None, {"type": "unknown.event"}, {}) is None


# ── AnthropicMessagesCodec streaming ─────────────────────────────────────────


class TestAnthropicMessagesCodecStreaming:
    def test_can_stream_true(self):
        assert AnthropicMessagesCodec().can_stream is True

    def test_parse_message_start(self):
        codec = AnthropicMessagesCodec()
        acc: dict = {}
        data = {"type": "message_start", "message": {"id": "msg-1", "llm": "claude-3", "usage": {"input_tokens": 50}}}
        result = codec.parse_stream_event(None, data, acc)
        assert result is None
        assert acc["response_id"] == "msg-1"
        assert acc["llm"] == "claude-3"
        assert acc["usage"].input_tokens == 50

    def test_parse_text_delta(self):
        codec = AnthropicMessagesCodec()
        acc: dict = {}
        data = {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello"}}
        result = codec.parse_stream_event(None, data, acc)
        assert isinstance(result, StreamDelta)
        assert result.content == "Hello"
        assert result.delta_type == "text"

    def test_parse_thinking_delta(self):
        codec = AnthropicMessagesCodec()
        acc: dict = {}
        data = {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "reasoning..."}}
        result = codec.parse_stream_event(None, data, acc)
        assert isinstance(result, StreamDelta)
        assert result.content == "reasoning..."
        assert result.delta_type == "reasoning"

    def test_parse_input_json_delta(self):
        codec = AnthropicMessagesCodec()
        acc: dict = {"current_block": {"type": "tool_use", "id": "tu1", "name": "fn", "args_buf": ""}}
        data = {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": '{"x":'}}
        result = codec.parse_stream_event(None, data, acc)
        assert isinstance(result, StreamDelta)
        assert result.delta_type == "tool_call"
        assert result.content == '{"x":'
        assert result.meta["tool_name"] == "fn"
        assert acc["current_block"]["args_buf"] == '{"x":'

    def test_parse_content_block_start_tool_use(self):
        codec = AnthropicMessagesCodec()
        acc: dict = {}
        data = {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "tu1", "name": "fn"}}
        codec.parse_stream_event(None, data, acc)
        assert acc["current_block"]["type"] == "tool_use"
        assert acc["current_block"]["id"] == "tu1"
        assert acc["current_block"]["name"] == "fn"

    def test_parse_content_block_stop_tool_use_yields_block(self):
        codec = AnthropicMessagesCodec()
        acc: dict = {"current_block": {"type": "tool_use", "id": "tu1", "name": "fn", "args_buf": '{"x": 1}'}}
        data = {"type": "content_block_stop"}
        result = codec.parse_stream_event(None, data, acc)
        assert isinstance(result, LLMResponseToolCallBlock)
        assert result.tool_call_id == "tu1"
        assert result.tool_name == "fn"
        assert result.tool_args == {"x": 1}
        assert acc["current_block"] is None

    def test_parse_content_block_stop_text_returns_none(self):
        codec = AnthropicMessagesCodec()
        acc: dict = {"current_block": {"type": "text"}}
        data = {"type": "content_block_stop"}
        result = codec.parse_stream_event(None, data, acc)
        assert result is None

    def test_parse_message_delta_sets_stop_reason(self):
        codec = AnthropicMessagesCodec()
        acc: dict = {"usage": Usage(input_tokens=10, output_tokens=0)}
        data = {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 20}}
        codec.parse_stream_event(None, data, acc)
        assert acc["stop_reason"] == StopReason.TOOL_USE
        assert acc["usage"].output_tokens == 20

    def test_parse_message_delta_max_tokens(self):
        codec = AnthropicMessagesCodec()
        acc: dict = {}
        data = {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}, "usage": {"output_tokens": 100}}
        codec.parse_stream_event(None, data, acc)
        assert acc["stop_reason"] == StopReason.LENGTH

    def test_flush_stream(self):
        codec = AnthropicMessagesCodec()
        acc = {"stop_reason": StopReason.END_TURN, "usage": Usage(input_tokens=10, output_tokens=5), "llm": "claude-3", "response_id": "msg-1"}
        blocks, end = codec.flush_stream(acc)
        assert end.stop_reason == StopReason.END_TURN
        assert end.usage.input_tokens == 10

    def test_parse_unknown_event_returns_none(self):
        codec = AnthropicMessagesCodec()
        assert codec.parse_stream_event(None, {"type": "ping"}, {}) is None


# ── LLMHTTPAdapter._iter_sse_events ──────────────────────────────────────────


class TestIterSSEEvents:
    @pytest.mark.asyncio
    async def test_parse_simple_event(self):
        lines = ['data: {"content": "hello"}', '']
        events = []
        async for etype, data in _mock_sse_events(lines):
            events.append((etype, data))
        assert len(events) == 1
        assert events[0][1]["content"] == "hello"

    @pytest.mark.asyncio
    async def test_parse_event_with_type(self):
        lines = ['event: message_start', 'data: {"id": "1"}', '']
        events = []
        async for etype, data in _mock_sse_events(lines):
            events.append((etype, data))
        assert events[0][0] == "message_start"
        assert events[0][1]["id"] == "1"

    @pytest.mark.asyncio
    async def test_parse_done_marker(self):
        lines = ['data: [DONE]']
        events = []
        async for etype, data in _mock_sse_events(lines):
            events.append((etype, data))
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_parse_multiple_events(self):
        lines = [
            'data: {"a": 1}', '',
            'event: delta', 'data: {"b": 2}', '',
        ]
        events = []
        async for etype, data in _mock_sse_events(lines):
            events.append((etype, data))
        assert len(events) == 2
        assert events[0] == (None, {"a": 1})
        assert events[1] == ("delta", {"b": 2})

    @pytest.mark.asyncio
    async def test_parse_multiline_data(self):
        lines = ['data: {"x":', 'data:  1}', '']
        events = []
        async for etype, data in _mock_sse_events(lines):
            events.append((etype, data))
        assert events[0][1] == {"x": 1}

    @pytest.mark.asyncio
    async def test_parse_invalid_json_skipped(self):
        lines = ['data: not-json', '', 'data: {"ok": true}', '']
        events = []
        async for etype, data in _mock_sse_events(lines):
            events.append((etype, data))
        assert len(events) == 1
        assert events[0][1] == {"ok": True}


async def _mock_sse_events(lines: list[str]):
    """Helper that feeds raw SSE lines into _iter_sse_events via a mock response."""
    import httpx

    class MockResponse:
        def __init__(self, lines):
            self._lines = lines

        async def aiter_lines(self):
            for line in self._lines:
                yield line

    # We can't easily mock httpx.Response, so we replicate the SSE parsing logic inline
    event_type = None
    data_lines = []

    for line in lines:
        line = line.rstrip()
        if not line:
            if data_lines:
                data_str = "\n".join(data_lines)
                if data_str == "[DONE]":
                    return
                try:
                    yield (event_type, json.loads(data_str))
                except json.JSONDecodeError:
                    pass
                data_lines = []
            event_type = None
            continue

        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())

    if data_lines:
        data_str = "\n".join(data_lines)
        if data_str != "[DONE]":
            try:
                yield (event_type, json.loads(data_str))
            except json.JSONDecodeError:
                pass


# ── HttpConnector.send_stream_chunk ──────────────────────────────────────────


class TestHttpConnectorStreaming:
    @pytest.mark.asyncio
    async def test_send_stream_chunk_pushes_to_queue(self):
        from commamatrix.builtin.http_connector.connector import HttpConnector
        agent = stub_agent()
        conn = HttpConnector(agent=agent)

        import asyncio
        queue: asyncio.Queue = asyncio.Queue()
        origin = stub_origin()
        origin.__class__.__bases__  # ensure it's not HttpOrigin
        from commamatrix.builtin.http_connector.connector import HttpOrigin
        http_origin = HttpOrigin(http_user_id=1)
        session = conn._open_session(1)
        session.queue = queue

        chunk = StreamDelta(
            content='{"code":',
            delta_type="tool_call",
            meta={"tool_name": "execute", "tool_call_id": "tc1"},
        )
        await conn.send_stream_chunk(http_origin, chunk)

        assert not queue.empty()
        item = await queue.get()
        assert item["type"] == "stream_chunk"
        assert item["delta_type"] == "tool_call"
        assert item["item_type"] == "tool_call"
        assert item["content"] == '{"code":'
        assert item["meta"]["tool_name"] == "execute"

    @pytest.mark.asyncio
    async def test_send_stream_chunk_wrong_origin_ignored(self):
        from commamatrix.builtin.http_connector.connector import HttpConnector
        agent = stub_agent()
        conn = HttpConnector(agent=agent)
        chunk = StreamDelta(content="x", delta_type="text")
        await conn.send_stream_chunk(stub_origin(), chunk)

    @pytest.mark.asyncio
    async def test_send_stream_chunk_no_queue_ignored(self):
        from commamatrix.builtin.http_connector.connector import HttpConnector, HttpOrigin
        agent = stub_agent()
        conn = HttpConnector(agent=agent)
        chunk = StreamDelta(content="x", delta_type="text")
        await conn.send_stream_chunk(HttpOrigin(http_user_id=999), chunk)
