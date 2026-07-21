# tests/test_codec.py

"""Tests for ApiCodec, ChatCompletionsCodec, ResponsesCodec, AnthropicMessagesCodec."""

from __future__ import annotations

import pytest

from commamatrix.builtin.llm_http_adapter.codec import ApiCodec, ApiProtocol
from commamatrix.builtin.llm_http_adapter.chat_completions import ChatCompletionsCodec
from commamatrix.builtin.llm_http_adapter.responses import ResponsesCodec
from commamatrix.builtin.llm_http_adapter.anthropic_messages import AnthropicMessagesCodec
from commamatrix.components.llm_adapter import (
    LLMResponse,
    LLMResponseTextBlock,
    LLMResponseToolCallBlock,
    LLMResponseReasoningBlock,
    StopReason,
    Usage,
)


class TestApiProtocol:
    def test_values(self):
        assert ApiProtocol.CHAT_COMPLETIONS == "chat_completions"
        assert ApiProtocol.RESPONSES == "responses"
        assert ApiProtocol.ANTHROPIC_MESSAGES == "anthropic_messages"


class TestCodecRegistry:
    def test_all_codecs_registered(self):
        assert "chat_completions" in ApiCodec.registry
        assert "responses" in ApiCodec.registry
        assert "anthropic_messages" in ApiCodec.registry

    def test_registry_instances(self):
        assert isinstance(ApiCodec.registry["chat_completions"], ChatCompletionsCodec)
        assert isinstance(ApiCodec.registry["responses"], ResponsesCodec)
        assert isinstance(ApiCodec.registry["anthropic_messages"], AnthropicMessagesCodec)


class TestChatCompletionsCodec:
    def test_parse_simple_response(self):
        codec = ChatCompletionsCodec()
        body = {
            "id": "resp1",
            "model": "gpt-4",
            "choices": [{
                "message": {"role": "assistant", "content": "Hello!"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        resp = codec.parse_response(body)
        assert resp.stop_reason == StopReason.END_TURN
        assert len(resp.content) == 1
        assert isinstance(resp.content[0], LLMResponseTextBlock)
        assert resp.content[0].content == "Hello!"
        assert resp.usage.input_tokens == 10
        assert resp.usage.output_tokens == 5
        assert resp.model == "gpt-4"

    def test_parse_tool_calls(self):
        codec = ChatCompletionsCodec()
        body = {
            "id": "resp2",
            "model": "gpt-4",
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "tc1",
                        "type": "function",
                        "function": {
                            "name": "my_fn",
                            "arguments": '{"x": 1}',
                        },
                    }],
                },
                "finish_reason": "tool_calls",
            }],
        }
        resp = codec.parse_response(body)
        assert resp.stop_reason == StopReason.TOOL_USE
        assert len(resp.content) == 1
        tc = resp.content[0]
        assert isinstance(tc, LLMResponseToolCallBlock)
        assert tc.tool_call_id == "tc1"
        assert tc.tool_name == "my_fn"
        assert tc.tool_args == {"x": 1}

    def test_parse_length_stop(self):
        codec = ChatCompletionsCodec()
        body = {
            "id": "resp3",
            "model": "gpt-4",
            "choices": [{
                "message": {"role": "assistant", "content": "truncated"},
                "finish_reason": "length",
            }],
        }
        resp = codec.parse_response(body)
        assert resp.stop_reason == StopReason.LENGTH

    def test_parse_reasoning_content(self):
        codec = ChatCompletionsCodec()
        body = {
            "id": "resp4",
            "model": "deepseek-r1",
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "Answer",
                    "reasoning_content": "Let me think...",
                },
                "finish_reason": "stop",
            }],
        }
        resp = codec.parse_response(body)
        assert len(resp.content) == 2
        assert isinstance(resp.content[0], LLMResponseReasoningBlock)
        assert resp.content[0].content == "Let me think..."
        assert isinstance(resp.content[1], LLMResponseTextBlock)
        assert resp.content[1].content == "Answer"


class TestResponsesCodec:
    def test_parse_simple_message(self):
        codec = ResponsesCodec()
        body = {
            "id": "resp1",
            "model": "gpt-4",
            "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": "Hi!"}],
            }],
            "usage": {"input_tokens": 5, "output_tokens": 3},
        }
        resp = codec.parse_response(body)
        assert resp.stop_reason == StopReason.END_TURN
        assert len(resp.content) == 1
        assert resp.content[0].content == "Hi!"

    def test_parse_function_call(self):
        codec = ResponsesCodec()
        body = {
            "id": "resp2",
            "model": "gpt-4",
            "output": [{
                "type": "function_call",
                "call_id": "tc1",
                "name": "fn",
                "arguments": '{"a": 1}',
            }],
        }
        resp = codec.parse_response(body)
        assert resp.stop_reason == StopReason.TOOL_USE
        assert len(resp.content) == 1
        tc = resp.content[0]
        assert isinstance(tc, LLMResponseToolCallBlock)
        assert tc.tool_name == "fn"

    def test_parse_reasoning(self):
        codec = ResponsesCodec()
        body = {
            "id": "resp3",
            "model": "o3",
            "output": [{
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "thinking..."}],
            }, {
                "type": "message",
                "content": [{"type": "output_text", "text": "result"}],
            }],
        }
        resp = codec.parse_response(body)
        assert len(resp.content) == 2
        assert isinstance(resp.content[0], LLMResponseReasoningBlock)
        assert resp.content[0].content == "thinking..."

    def test_parse_incomplete(self):
        codec = ResponsesCodec()
        body = {
            "id": "resp4",
            "model": "gpt-4",
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [],
        }
        resp = codec.parse_response(body)
        assert resp.stop_reason == StopReason.LENGTH


class TestAnthropicMessagesCodec:
    def test_parse_simple_text(self):
        codec = AnthropicMessagesCodec()
        body = {
            "id": "msg1",
            "model": "claude-3",
            "content": [{"type": "text", "text": "Hello!"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        resp = codec.parse_response(body)
        assert resp.stop_reason == StopReason.END_TURN
        assert len(resp.content) == 1
        assert resp.content[0].content == "Hello!"
        assert resp.usage.input_tokens == 10

    def test_parse_tool_use(self):
        codec = AnthropicMessagesCodec()
        body = {
            "id": "msg2",
            "model": "claude-3",
            "content": [{
                "type": "tool_use",
                "id": "tc1",
                "name": "fn",
                "input": {"x": 1},
            }],
            "stop_reason": "tool_use",
        }
        resp = codec.parse_response(body)
        assert resp.stop_reason == StopReason.TOOL_USE
        tc = resp.content[0]
        assert isinstance(tc, LLMResponseToolCallBlock)
        assert tc.tool_name == "fn"
        assert tc.tool_args == {"x": 1}

    def test_parse_thinking(self):
        codec = AnthropicMessagesCodec()
        body = {
            "id": "msg3",
            "model": "claude-3",
            "content": [
                {"type": "thinking", "thinking": "reasoning..."},
                {"type": "text", "text": "answer"},
            ],
            "stop_reason": "end_turn",
        }
        resp = codec.parse_response(body)
        assert len(resp.content) == 2
        assert isinstance(resp.content[0], LLMResponseReasoningBlock)
        assert resp.content[0].content == "reasoning..."

    def test_parse_max_tokens(self):
        codec = AnthropicMessagesCodec()
        body = {
            "id": "msg4",
            "model": "claude-3",
            "content": [],
            "stop_reason": "max_tokens",
        }
        resp = codec.parse_response(body)
        assert resp.stop_reason == StopReason.LENGTH

    def test_endpoint(self):
        assert AnthropicMessagesCodec().endpoint == "/v1/messages"
        assert ChatCompletionsCodec().endpoint == "/chat/completions"
        assert ResponsesCodec().endpoint == "/responses"
