# tests/test_llm_http_adapter.py

"""Tests for LLMHTTPAdapter logic (URL building, protocol detection, codec resolution)."""

from __future__ import annotations

import pytest

from commamatrix.builtin.llm_http_adapter.adapter import LLMHTTPAdapter
from commamatrix.builtin.llm_http_adapter.codec import ApiProtocol
from commamatrix.components.hook import BeforeLlmCallCtx, RunCtx
from commamatrix.components.config import Config, ConfigField
from commamatrix.core.classes.manager import ServiceInstanceRegistry
from tests.conftest import stub_agent, stub_origin


class TestJoinUrl:
    def test_simple(self):
        assert LLMHTTPAdapter._join_url("https://api.openai.com", "/v1/chat") == "https://api.openai.com/v1/chat"

    def test_trailing_slash(self):
        assert LLMHTTPAdapter._join_url("https://api.openai.com/", "/v1/chat") == "https://api.openai.com/v1/chat"

    def test_no_leading_slash(self):
        assert LLMHTTPAdapter._join_url("https://api.openai.com", "v1/chat") == "https://api.openai.com/v1/chat"

    def test_bare_hostname(self):
        result = LLMHTTPAdapter._join_url("api.openai.com", "/chat")
        assert result == "https://api.openai.com/chat"

    def test_path_dedup(self):
        result = LLMHTTPAdapter._join_url("https://proxy.example.com/v1", "/v1/chat/completions")
        assert result == "https://proxy.example.com/v1/chat/completions"


class TestDetectProtocol:
    def test_claude_model(self):
        agent = stub_agent()
        adapter = LLMHTTPAdapter(agent=agent)
        assert adapter._detect_protocol("claude-3-opus") == ApiProtocol.ANTHROPIC_MESSAGES

    def test_gpt_model(self):
        agent = stub_agent()
        adapter = LLMHTTPAdapter(agent=agent)
        assert adapter._detect_protocol("gpt-4o") == ApiProtocol.CHAT_COMPLETIONS

    def test_deepseek_model(self):
        agent = stub_agent()
        adapter = LLMHTTPAdapter(agent=agent)
        assert adapter._detect_protocol("deepseek-r1") == ApiProtocol.CHAT_COMPLETIONS


class TestBuildHeaders:
    def test_openai_headers(self):
        from commamatrix.builtin.llm_http_adapter.adapter import openai_api_key
        agent = stub_agent()
        agent.config = Config(overrides={openai_api_key: "sk-test"})
        adapter = LLMHTTPAdapter(agent=agent)
        headers = adapter._build_headers(ApiProtocol.CHAT_COMPLETIONS)
        assert headers["Authorization"] == "Bearer sk-test"

    def test_anthropic_headers(self):
        from commamatrix.builtin.llm_http_adapter.adapter import anthropic_api_key
        agent = stub_agent()
        agent.config = Config(overrides={anthropic_api_key: "ant-key"})
        adapter = LLMHTTPAdapter(agent=agent)
        headers = adapter._build_headers(ApiProtocol.ANTHROPIC_MESSAGES)
        assert headers["x-api-key"] == "ant-key"
        assert "anthropic-version" in headers


class TestResolveProtocol:
    def test_from_ctx(self):
        agent = stub_agent()
        adapter = LLMHTTPAdapter(agent=agent)
        origin = stub_origin()
        run = RunCtx(agent=agent, origin=origin, user="u")
        ctx = BeforeLlmCallCtx(run=run, dialog=[], tools=[], api_protocol="responses")
        assert adapter._resolve_protocol(ctx) == ApiProtocol.RESPONSES

    def test_from_model_heuristic(self):
        agent = stub_agent()
        adapter = LLMHTTPAdapter(agent=agent)
        origin = stub_origin()
        run = RunCtx(agent=agent, origin=origin, user="u")
        run.model = "claude-3"
        ctx = BeforeLlmCallCtx(run=run, dialog=[], tools=[])
        assert adapter._resolve_protocol(ctx) == ApiProtocol.ANTHROPIC_MESSAGES
