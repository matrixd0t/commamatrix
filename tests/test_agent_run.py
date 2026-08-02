# tests/test_agent_run.py

"""Integration tests for Agent.run() and Agent.handle() — the core orchestration loop."""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

import pytest

from commamatrix.components.config import Config
from commamatrix.components.dialog import DialogItem, DialogItemType, DialogOrigin, DialogRole
from commamatrix.components.hook import (
    AfterLlmCallCtx,
    AfterRunCtx,
    BeforeLlmCallCtx,
    BeforeRunCtx,
    BeforeToolCallCtx,
    BeforeSendCtx,
    HookEventType,
    OnErrorCtx,
    OnParsedCtx,
    RunCtx,
)
from commamatrix.components.llm_adapter import (
    LLM,
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
    ToolCall,
    ToolCallResult,
    Usage,
)
from commamatrix.components.connector import Connector
from commamatrix.components.storage import Storage
from commamatrix.components.file_storage import FileStorage
from commamatrix.components.tool import tool
from commamatrix.core.agent.agent import Agent
from commamatrix.core.classes.service import AbstractService
from tests.conftest import StubOrigin, stub_origin, make_dialog_item


# ── Helpers ──────────────────────────────────────────────────────────────────


_hook_sources: list = []


def _register_hook(agent, event, handler, priority=0, name=None):
    """Register a hook handler directly in the agent's hook manager."""
    import weakref
    from commamatrix.components.hook import HookDescriptor, PythonHookSource

    source = PythonHookSource()
    source._available = True
    _hook_sources.append(source)  # Keep source alive
    if name is None:
        name = handler.__name__
    d = HookDescriptor(
        id=f"hook://test/{name}",
        event=event,
        priority=priority,
        name=name,
        module="test",
        _source_ref=weakref.ref(source),
    )
    source._handlers[d.id] = handler
    agent.hook_manager._descriptors[d.id] = d
    agent.hook_manager._rebuild()
    return handler


def _hook(agent, event, priority=0):
    """Decorator to register a hook in the agent's hook manager."""

    def decorator(fn):
        _register_hook(agent, event, fn, priority=priority)
        return fn

    return decorator


class RecordingConnector(Connector[StubOrigin]):
    """Connector that records sent items and supports streaming."""

    supports_streaming = True

    def __init__(self, agent: Any) -> None:
        super().__init__(agent)
        self.sent: list[DialogItem] = []
        self.stream_chunks: list[StreamDelta] = []
        self._external_id_counter = 0

    async def parse(self, data: dict) -> OnParsedCtx | None:
        return None

    async def send(self, origin: StubOrigin, item: DialogItem) -> str:
        self._external_id_counter += 1
        ext_id = f"ext_{self._external_id_counter}"
        item.external_id = ext_id
        self.sent.append(item)
        return ext_id

    async def send_stream_chunk(self, origin: StubOrigin, delta: StreamDelta) -> None:
        self.stream_chunks.append(delta)


class MockLLMAdapter(LLMAdapter):
    """LLM adapter that yields pre-configured events."""

    def __init__(self, agent: Any, events: list[Any] | None = None) -> None:
        super().__init__(agent)
        self._events = events or []

    async def ask_llm(self, ctx: BeforeLlmCallCtx, *, stream: bool = False):
        for event in self._events:
            yield event


class InMemoryStorage(Storage):
    """Simple in-memory storage for testing."""

    def __init__(self, agent: Any) -> None:
        super().__init__(agent)
        self._items: dict[int, DialogItem] = {}
        self._next_id = 1
        self._by_external: dict[str, int] = {}

    async def save_event(self, entry: DialogItem) -> int | None:
        entry.item_id = self._next_id
        self._items[self._next_id] = entry
        if entry.external_id:
            self._by_external[entry.external_id] = self._next_id
        self._next_id += 1
        return entry.item_id

    async def get_branch(self, last_item_id: int) -> list[DialogItem]:
        result = []
        current_id: int | None = last_item_id
        while current_id is not None:
            item = self._items.get(current_id)
            if item is None:
                break
            result.append(item)
            current_id = item.previous_item_id
        result.reverse()
        return result

    async def find_item_id_by_external_id(self, external_id: str, origin: DialogOrigin) -> int | None:
        return self._by_external.get(external_id)

    async def get_history(self, *, origin_type: type[DialogOrigin] | None = None, origin_fields: dict[str, Any] | None = None) -> list[DialogItem]:
        """Return stored items matching the requested origin."""
        fields = origin_fields or {}
        return [item for item in self._items.values() if (origin_type is None or isinstance(item.origin, origin_type)) and all(getattr(item.origin, name, None) == value for name, value in fields.items())]


class NullFileStorage(FileStorage):
    async def save(self, data: bytes, ext: str | None = None) -> str:
        return "null"

    async def get(self, file_id: str) -> bytes | None:
        return None

    async def delete(self, file_id: str) -> bool:
        return False


def _make_run_ctx(agent: Agent, connector: RecordingConnector | None = None) -> RunCtx:
    return RunCtx(
        agent=agent,
        connector=connector,
        origin=stub_origin(),
        user="test_user",
        model=LLM(model_name="test-llm"),
    )


class _NullLifecycle:
    """Replaces AgentLifecycle to prevent refresh from wiping manually-registered hooks."""

    def set_scope(self, scope):
        pass

    async def refresh(self):
        pass

    async def start(self):
        pass

    async def stop(self):
        pass


async def _setup_agent(
    events: list[Any],
    connector_cls: type = RecordingConnector,
    hooks: dict[str, list] | None = None,
) -> tuple[Agent, RecordingConnector, InMemoryStorage]:
    """Create an agent with mock LLM, recording connector, and in-memory storage."""
    agent = Agent(config={}, auto_load_main=False, essentials=False)

    connector = connector_cls(agent=agent)
    llm = MockLLMAdapter(agent, events)
    storage = InMemoryStorage(agent)
    fs = NullFileStorage(agent)

    class _FixedLLMManager:
        def ask_llm(self, ctx, *, stream=False):
            return llm.ask_llm(ctx, stream=stream)

        def resolve(self):
            return []

        def set_scope(self, scope):
            pass

        async def refresh(self):
            pass

        async def start(self):
            pass

        async def stop(self):
            pass

    class _FixedStorageManager:
        def __getattr__(self, name):
            return getattr(storage, name)

        def set_scope(self, scope):
            pass

        async def refresh(self):
            pass

        async def start(self):
            pass

        async def stop(self):
            pass

    class _FixedFSManager:
        def __getattr__(self, name):
            return getattr(fs, name)

        def set_scope(self, scope):
            pass

        async def refresh(self):
            pass

        async def start(self):
            pass

        async def stop(self):
            pass

    class _FixedConnectorManager:
        def resolve(self):
            return [connector]

        def resolve_for_origin(self, origin):
            return connector

        def set_scope(self, scope):
            pass

        async def refresh(self):
            pass

        async def start(self):
            pass

        async def stop(self):
            pass

    agent.llm_adapter = _FixedLLMManager()
    agent.storage = _FixedStorageManager()
    agent.file_storage = _FixedFSManager()
    agent.connector_manager = _FixedConnectorManager()
    agent.manager = _NullLifecycle()
    agent._started = True

    return agent, connector, storage


# ── Agent.run() — text response ─────────────────────────────────────────────


class TestAgentRunTextResponse:
    @pytest.mark.asyncio
    async def test_simple_text_response(self):
        text_block = LLMResponseTextBlock(content="Hello!")
        events = [text_block, StreamEnd(stop_reason=StopReason.END_TURN)]
        agent, connector, storage = await _setup_agent(events)

        run = _make_run_ctx(agent, connector)
        result = await agent.run(run)

        assert result is not None
        assert result.response.stop_reason == StopReason.END_TURN
        assert len(result.response.content) == 1
        assert result.response.content[0].content == "Hello!"
        assert len(connector.sent) == 1
        assert connector.sent[0].content == "Hello!"
        assert connector.sent[0].item_type == DialogItemType.OUTPUT

    @pytest.mark.asyncio
    async def test_text_response_persisted_to_storage(self):
        text_block = LLMResponseTextBlock(content="Persisted")
        events = [text_block, StreamEnd(stop_reason=StopReason.END_TURN)]
        agent, connector, storage = await _setup_agent(events)

        run = _make_run_ctx(agent, connector)
        await agent.run(run)

        assert len(storage._items) == 1
        item = list(storage._items.values())[0]
        assert item.content == "Persisted"
        assert item.item_type == DialogItemType.OUTPUT

    @pytest.mark.asyncio
    async def test_response_with_reasoning_block(self):
        reasoning = LLMResponseReasoningBlock(content="Thinking...")
        text = LLMResponseTextBlock(content="Answer")
        events = [reasoning, text, StreamEnd(stop_reason=StopReason.END_TURN)]
        agent, connector, storage = await _setup_agent(events)

        run = _make_run_ctx(agent, connector)
        result = await agent.run(run)

        assert result is not None
        assert len(result.response.content) == 2
        assert connector.sent[0].item_type == DialogItemType.REASONING
        assert connector.sent[1].item_type == DialogItemType.OUTPUT
        assert len(storage._items) == 2


# ── Agent.run() — streaming ─────────────────────────────────────────────────


class TestAgentRunStreaming:
    @pytest.mark.asyncio
    async def test_stream_deltas_sent_via_connector(self):
        text_block = LLMResponseTextBlock(content="Hello world")
        events = [
            StreamDelta(content="Hello", delta_type="text"),
            StreamDelta(content=" world", delta_type="text"),
            text_block,
            StreamEnd(stop_reason=StopReason.END_TURN),
        ]
        agent, connector, storage = await _setup_agent(events)

        run = _make_run_ctx(agent, connector)
        await agent.run(run)

        assert len(connector.stream_chunks) == 2
        assert connector.stream_chunks[0].content == "Hello"
        assert connector.stream_chunks[1].content == " world"

    @pytest.mark.asyncio
    async def test_reasoning_stream_deltas(self):
        reasoning_block = LLMResponseReasoningBlock(content="Let me think")
        text_block = LLMResponseTextBlock(content="Result")
        events = [
            StreamDelta(content="Let me", delta_type="reasoning"),
            StreamDelta(content=" think", delta_type="reasoning"),
            reasoning_block,
            text_block,
            StreamEnd(stop_reason=StopReason.END_TURN),
        ]
        agent, connector, storage = await _setup_agent(events)

        run = _make_run_ctx(agent, connector)
        await agent.run(run)

        assert len(connector.stream_chunks) == 2
        assert connector.stream_chunks[0].delta_type == "reasoning"


# ── Agent.run() — tool calls ────────────────────────────────────────────────


def _make_multi_call_agent(events_list, connector_cls=RecordingConnector):
    """Create an agent with a multi-call LLM adapter."""
    agent = Agent(config={}, auto_load_main=False, essentials=False)
    call_count = 0

    class MultiCallAdapter(LLMAdapter):
        async def ask_llm(self, ctx, *, stream=False):
            nonlocal call_count
            for event in events_list[call_count]:
                yield event
            call_count += 1

    connector = connector_cls(agent=agent)
    llm = MultiCallAdapter(agent)
    storage = InMemoryStorage(agent)
    fs = NullFileStorage(agent)

    class _FixedLLMManager:
        def ask_llm(self, ctx, *, stream=False):
            return llm.ask_llm(ctx, stream=stream)

        def resolve(self):
            return []

        def set_scope(self, scope):
            pass

        async def refresh(self):
            pass

        async def start(self):
            pass

        async def stop(self):
            pass

    class _FixedStorageManager:
        def __getattr__(self, name):
            return getattr(storage, name)

        def set_scope(self, scope):
            pass

        async def refresh(self):
            pass

        async def start(self):
            pass

        async def stop(self):
            pass

    class _FixedFSManager:
        def __getattr__(self, name):
            return getattr(fs, name)

        def set_scope(self, scope):
            pass

        async def refresh(self):
            pass

        async def start(self):
            pass

        async def stop(self):
            pass

    class _FixedConnectorManager:
        def resolve(self):
            return [connector]

        def resolve_for_origin(self, origin):
            return connector

        def set_scope(self, scope):
            pass

        async def refresh(self):
            pass

        async def start(self):
            pass

        async def stop(self):
            pass

    agent.llm_adapter = _FixedLLMManager()
    agent.storage = _FixedStorageManager()
    agent.file_storage = _FixedFSManager()
    agent.connector_manager = _FixedConnectorManager()
    agent.manager = _NullLifecycle()
    agent._started = True

    return agent, connector, storage


class TestAgentRunToolCalls:
    @pytest.mark.asyncio
    async def test_load_dialog_filters_orphan_tool_results(self):
        agent, connector, storage = await _setup_agent([])
        tool_call = make_dialog_item(
            content='{"tool_call_id":"tc1","tool_name":"tool","tool_args":{}}',
            item_type=DialogItemType.TOOL_CALL,
            role=DialogRole.ASSISTANT,
            item_id=1,
        )
        valid_result = make_dialog_item(
            content='{"tool_call_id":"tc1","content":"ok"}',
            item_type=DialogItemType.TOOL_CALL_RESULT,
            role=DialogRole.TOOL,
            item_id=2,
            previous_item_id=1,
        )
        orphan_result = make_dialog_item(
            content='{"tool_call_id":"missing","content":"stale"}',
            item_type=DialogItemType.TOOL_CALL_RESULT,
            role=DialogRole.TOOL,
            item_id=3,
            previous_item_id=2,
        )
        storage._items = {1: tool_call, 2: valid_result, 3: orphan_result}

        dialog = await agent._load_dialog(3)

        assert dialog == [tool_call, valid_result]

    @pytest.mark.asyncio
    async def test_single_tool_call(self):
        @tool
        async def add(a: int, b: int) -> int:
            return a + b

        add.__module__ = "__test_tools__"
        mod = types.ModuleType("__test_tools__")
        mod.add = add
        sys.modules["__test_tools__"] = mod
        try:
            tool_block = LLMResponseToolCallBlock(
                tool_call_id="tc1",
                tool_name="__test_tools___add",
                tool_args={"a": 1, "b": 2},
            )
            text_after_tool = LLMResponseTextBlock(content="Result: 3")
            events = [
                [tool_block, StreamEnd(stop_reason=StopReason.TOOL_USE)],
                [text_after_tool, StreamEnd(stop_reason=StopReason.END_TURN)],
            ]

            agent, connector, storage = _make_multi_call_agent(events)
            await agent.add_extensions("__test_tools__")

            run = _make_run_ctx(agent, connector)
            result = await agent.run(run)

            assert result is not None
            assert result.response.stop_reason == StopReason.END_TURN
            # tool call block + tool result + final text
            assert len(connector.sent) >= 3
        finally:
            del sys.modules["__test_tools__"]

    @pytest.mark.asyncio
    async def test_tool_result_follows_current_iteration_tool_call(self):
        @tool
        async def add(a: int, b: int) -> int:
            return a + b

        add.__module__ = "__test_chain_tools__"
        mod = types.ModuleType("__test_chain_tools__")
        mod.add = add
        sys.modules["__test_chain_tools__"] = mod
        try:
            events = [
                [
                    LLMResponseToolCallBlock(
                        tool_call_id="tc1",
                        tool_name="__test_chain_tools___add",
                        tool_args={"a": 1, "b": 2},
                    ),
                    StreamEnd(stop_reason=StopReason.TOOL_USE),
                ],
                [
                    LLMResponseToolCallBlock(
                        tool_call_id="tc2",
                        tool_name="__test_chain_tools___add",
                        tool_args={"a": 3, "b": 4},
                    ),
                    StreamEnd(stop_reason=StopReason.TOOL_USE),
                ],
                [
                    LLMResponseTextBlock(content="done"),
                    StreamEnd(stop_reason=StopReason.END_TURN),
                ],
            ]

            agent, connector, storage = _make_multi_call_agent(events)
            await agent.add_extensions("__test_chain_tools__")

            await agent.run(_make_run_ctx(agent, connector))

            calls = [
                item
                for item in storage._items.values()
                if item.item_type == DialogItemType.TOOL_CALL
            ]
            results = [
                item
                for item in storage._items.values()
                if item.item_type == DialogItemType.TOOL_CALL_RESULT
            ]
            assert len(calls) == 2
            assert len(results) == 2
            assert results[0].previous_item_id == calls[0].item_id
            assert results[1].previous_item_id == calls[1].item_id
        finally:
            del sys.modules["__test_chain_tools__"]

    @pytest.mark.asyncio
    async def test_tool_call_with_before_hook_mutation(self):
        @tool
        async def greet(name: str) -> str:
            return f"Hello {name}"

        greet.__module__ = "__test_mutate__"
        mod = types.ModuleType("__test_mutate__")
        mod.greet = greet
        sys.modules["__test_mutate__"] = mod
        try:
            tool_block = LLMResponseToolCallBlock(
                tool_call_id="tc1",
                tool_name="__test_mutate___greet",
                tool_args={"name": "World"},
            )
            text_block = LLMResponseTextBlock(content="Done")
            events = [
                [tool_block, StreamEnd(stop_reason=StopReason.TOOL_USE)],
                [text_block, StreamEnd(stop_reason=StopReason.END_TURN)],
            ]

            agent, connector, storage = _make_multi_call_agent(events)
            await agent.add_extensions("__test_mutate__")

            mutation_log: list[str] = []

            @_hook(agent, "before_tool_call", priority=10)
            async def mutate_args(ctx: BeforeToolCallCtx):
                mutation_log.append("before")
                ctx.tool_call = ToolCall(
                    tool_call_id=ctx.tool_call.tool_call_id,
                    tool_name=ctx.tool_call.tool_name,
                    tool_args={"name": "Mutated"},
                )

            run = _make_run_ctx(agent, connector)
            result = await agent.run(run)

            assert result is not None
            assert mutation_log == ["before"]
        finally:
            del sys.modules["__test_mutate__"]

    @pytest.mark.asyncio
    async def test_tool_call_aborted_by_hook(self):
        tool_block = LLMResponseToolCallBlock(
            tool_call_id="tc1",
            tool_name="some_tool",
            tool_args={},
        )
        text_block = LLMResponseTextBlock(content="OK")
        events = [
            [tool_block, StreamEnd(stop_reason=StopReason.TOOL_USE)],
            [text_block, StreamEnd(stop_reason=StopReason.END_TURN)],
        ]

        agent, connector, storage = _make_multi_call_agent(events)

        @_hook(agent, "before_tool_call", priority=10)
        async def abort_tool(ctx: BeforeToolCallCtx):
            ctx.abort_tool_call = True
            ctx.abort_reason = "not allowed"

        run = _make_run_ctx(agent, connector)
        result = await agent.run(run)

        assert result is not None
        # Tool result should contain abort message
        tool_result_items = [
            i for i in connector.sent if i.item_type == DialogItemType.TOOL_CALL_RESULT
        ]
        assert len(tool_result_items) == 1
        assert "aborted" in tool_result_items[0].content.lower()


# ── Agent.run() — hooks ─────────────────────────────────────────────────────


class TestAgentRunHooks:
    @pytest.mark.asyncio
    async def test_before_run_aborts(self):
        events = [LLMResponseTextBlock(content="Should not appear")]
        agent, connector, storage = await _setup_agent(events)

        @_hook(agent, "before_run", priority=10)
        async def abort_run(ctx: BeforeRunCtx):
            ctx.abort = True

        run = _make_run_ctx(agent, connector)
        result = await agent.run(run)

        assert result is None
        assert len(connector.sent) == 0

    @pytest.mark.asyncio
    async def test_after_llm_call_hook_receives_response(self):
        text_block = LLMResponseTextBlock(content="Test")
        events = [text_block, StreamEnd(stop_reason=StopReason.END_TURN)]
        agent, connector, storage = await _setup_agent(events)

        captured: list[AfterLlmCallCtx] = []

        @_hook(agent, "after_llm_call", priority=10)
        async def capture(ctx: AfterLlmCallCtx):
            captured.append(ctx)

        run = _make_run_ctx(agent, connector)
        await agent.run(run)

        assert len(captured) == 1
        assert captured[0].response.stop_reason == StopReason.END_TURN

    @pytest.mark.asyncio
    async def test_before_llm_call_hook_can_mutate_dialog(self):
        text_block = LLMResponseTextBlock(content="Reply")
        events = [text_block, StreamEnd(stop_reason=StopReason.END_TURN)]
        agent, connector, storage = await _setup_agent(events)

        @_hook(agent, "before_llm_call", priority=10)
        async def inject_system(ctx: BeforeLlmCallCtx):
            ctx.dialog.insert(
                0,
                DialogItem(
                    content="System instruction",
                    item_type=DialogItemType.INPUT,
                    role=DialogRole.SYSTEM,
                    origin=ctx.run.origin,
                    user=ctx.run.user,
                ),
            )

        run = _make_run_ctx(agent, connector)
        await agent.run(run)

        # The hook ran without error
        assert len(connector.sent) == 1

    @pytest.mark.asyncio
    async def test_on_error_hook_called(self):
        agent, connector, storage = await _setup_agent([])

        @_hook(agent, "before_run", priority=10)
        async def fail_run(ctx: BeforeRunCtx):
            raise ValueError("boom")

        errors: list[OnErrorCtx] = []

        @_hook(agent, "on_error", priority=10)
        async def capture_error(ctx: OnErrorCtx):
            errors.append(ctx)
            ctx.suppress = True

        run = _make_run_ctx(agent, connector)
        result = await agent.run(run)

        assert result is None
        assert len(errors) == 1
        assert isinstance(errors[0].error, ValueError)

    @pytest.mark.asyncio
    async def test_after_run_hook_called_on_success(self):
        text_block = LLMResponseTextBlock(content="OK")
        events = [text_block, StreamEnd(stop_reason=StopReason.END_TURN)]
        agent, connector, storage = await _setup_agent(events)

        after_runs: list[AfterRunCtx] = []

        @_hook(agent, "after_run", priority=10)
        async def capture_after(ctx: AfterRunCtx):
            after_runs.append(ctx)

        run = _make_run_ctx(agent, connector)
        await agent.run(run)

        assert len(after_runs) == 1
        assert after_runs[0].error is None

    @pytest.mark.asyncio
    async def test_after_run_hook_called_on_error(self):
        agent, connector, storage = await _setup_agent([])

        @_hook(agent, "before_run", priority=10)
        async def fail(ctx: BeforeRunCtx):
            raise RuntimeError("fail")

        after_runs: list[AfterRunCtx] = []

        @_hook(agent, "after_run", priority=10)
        async def capture_after2(ctx: AfterRunCtx):
            after_runs.append(ctx)

        @_hook(agent, "on_error", priority=10)
        async def suppress_error(ctx: OnErrorCtx):
            ctx.suppress = True

        run = _make_run_ctx(agent, connector)
        await agent.run(run)

        assert len(after_runs) == 1
        assert isinstance(after_runs[0].error, RuntimeError)


# ── Agent.run() — error handling ────────────────────────────────────────────


class TestAgentRunErrors:
    @pytest.mark.asyncio
    async def test_no_stream_end_raises(self):
        agent, connector, storage = await _setup_agent([])

        run = _make_run_ctx(agent, connector)
        # Empty events list -> no StreamEnd -> LLMResponseError
        errors: list[Exception] = []

        @_hook(agent, "on_error", priority=10)
        async def capture(ctx: OnErrorCtx):
            errors.append(ctx.error)
            ctx.suppress = True

        await agent.run(run)
        assert len(errors) == 1
        assert "no StreamEnd" in str(errors[0])

    @pytest.mark.asyncio
    async def test_error_stop_reason_raises(self):
        events = [StreamEnd(stop_reason=StopReason.ERROR)]
        agent, connector, storage = await _setup_agent(events)

        errors: list[Exception] = []

        @_hook(agent, "on_error", priority=10)
        async def capture2(ctx: OnErrorCtx):
            errors.append(ctx.error)
            ctx.suppress = True

        run = _make_run_ctx(agent, connector)
        await agent.run(run)

        assert len(errors) == 1
        assert "error" in str(errors[0]).lower()

    @pytest.mark.asyncio
    async def test_length_stop_reason_raises(self):
        events = [
            LLMResponseTextBlock(content="truncated"),
            StreamEnd(stop_reason=StopReason.LENGTH),
        ]
        agent, connector, storage = await _setup_agent(events)

        errors: list[Exception] = []

        @_hook(agent, "on_error", priority=10)
        async def capture3(ctx: OnErrorCtx):
            errors.append(ctx.error)
            ctx.suppress = True

        run = _make_run_ctx(agent, connector)
        await agent.run(run)

        assert len(errors) == 1
        assert "truncated" in str(errors[0]).lower()


# ── Agent.run() — history ───────────────────────────────────────────────────


class TestAgentRunHistory:
    @pytest.mark.asyncio
    async def test_history_items_stored(self):
        text_block = LLMResponseTextBlock(content="Reply")
        events = [text_block, StreamEnd(stop_reason=StopReason.END_TURN)]
        agent, connector, storage = await _setup_agent(events)

        history = [
            make_dialog_item("user msg", role=DialogRole.USER),
        ]

        run = _make_run_ctx(agent, connector)
        await agent.run(run, history=history)

        # history item + response item
        assert len(storage._items) == 2

    @pytest.mark.asyncio
    async def test_history_with_existing_item_id(self):
        text_block = LLMResponseTextBlock(content="Reply")
        events = [text_block, StreamEnd(stop_reason=StopReason.END_TURN)]
        agent, connector, storage = await _setup_agent(events)

        history = [
            make_dialog_item("existing", item_id=42, role=DialogRole.USER),
        ]

        run = _make_run_ctx(agent, connector)
        await agent.run(run, history=history)

        # Only the response should be stored (history item already has id)
        assert len(storage._items) == 1


# ── Agent.run() — iteration counter ─────────────────────────────────────────


class TestAgentRunIteration:
    @pytest.mark.asyncio
    async def test_iteration_increments(self):
        text_block = LLMResponseTextBlock(content="OK")
        events = [text_block, StreamEnd(stop_reason=StopReason.END_TURN)]
        agent, connector, storage = await _setup_agent(events)

        run = _make_run_ctx(agent, connector)
        assert run.iteration == 0
        await agent.run(run)
        assert run.iteration == 1

    @pytest.mark.asyncio
    async def test_iteration_increments_per_tool_loop(self):
        tool_block = LLMResponseToolCallBlock(
            tool_call_id="tc1",
            tool_name="missing",
            tool_args={},
        )
        text_block = LLMResponseTextBlock(content="Done")
        events = [
            [tool_block, StreamEnd(stop_reason=StopReason.TOOL_USE)],
            [text_block, StreamEnd(stop_reason=StopReason.END_TURN)],
        ]

        agent, connector, storage = _make_multi_call_agent(events)

        run = _make_run_ctx(agent, connector)
        await agent.run(run)

        assert run.iteration == 2


# ── Agent._send_and_store_item ──────────────────────────────────────────────


class TestAgentSendAndStore:
    @pytest.mark.asyncio
    async def test_send_and_store_fires_before_send(self):
        text_block = LLMResponseTextBlock(content="Test")
        events = [text_block, StreamEnd(stop_reason=StopReason.END_TURN)]
        agent, connector, storage = await _setup_agent(events)

        sent_items: list[DialogItem] = []

        @_hook(agent, "before_send", priority=10)
        async def capture_send(ctx: BeforeSendCtx):
            sent_items.append(ctx.dialog_item)

        run = _make_run_ctx(agent, connector)
        await agent.run(run)

        assert len(sent_items) == 1
        assert sent_items[0].content == "Test"


# ── Agent._run_tool_lifecycle ───────────────────────────────────────────────


class TestAgentToolLifecycle:
    @pytest.mark.asyncio
    async def test_tool_lifecycle_fires_hooks(self):
        @tool
        async def my_tool(x: int) -> int:
            return x * 2

        my_tool.__module__ = "__test_lifecycle__"
        mod = types.ModuleType("__test_lifecycle__")
        mod.my_tool = my_tool
        sys.modules["__test_lifecycle__"] = mod
        try:
            tool_block = LLMResponseToolCallBlock(
                tool_call_id="tc1",
                tool_name="__test_lifecycle___my_tool",
                tool_args={"x": 5},
            )
            text_block = LLMResponseTextBlock(content="Done")
            events = [
                [tool_block, StreamEnd(stop_reason=StopReason.TOOL_USE)],
                [text_block, StreamEnd(stop_reason=StopReason.END_TURN)],
            ]

            agent, connector, storage = _make_multi_call_agent(events)
            await agent.add_extensions("__test_lifecycle__")

            before_calls: list[BeforeToolCallCtx] = []
            after_calls: list = []

            @_hook(agent, "before_tool_call", priority=10)
            async def before(ctx: BeforeToolCallCtx):
                before_calls.append(ctx)

            @_hook(agent, "after_tool_call", priority=10)
            async def after(ctx):
                after_calls.append(ctx)

            run = _make_run_ctx(agent, connector)
            result = await agent.run(run)

            assert result is not None
            assert len(before_calls) == 1
            assert before_calls[0].tool_call.tool_name == "__test_lifecycle___my_tool"
            assert len(after_calls) == 1
        finally:
            del sys.modules["__test_lifecycle__"]


# ── Agent._resolve_previous_item ────────────────────────────────────────────


class TestAgentResolvePrevious:
    @pytest.mark.asyncio
    async def test_resolves_previous_by_external_id(self):
        text_block = LLMResponseTextBlock(content="Reply")
        events = [text_block, StreamEnd(stop_reason=StopReason.END_TURN)]
        agent, connector, storage = await _setup_agent(events)

        # Pre-populate storage with an item
        existing = DialogItem(
            content="original",
            item_type=DialogItemType.INPUT,
            role=DialogRole.USER,
            origin=stub_origin(),
            user="test_user",
            external_id="ext_original",
        )
        await storage.save_event(existing)

        parsed = OnParsedCtx(
            agent=agent,
            connector=connector,
            raw={},
            dialog_items=[make_dialog_item("reply")],
            previous_external_id="ext_original",
        )

        await agent._resolve_previous_item(parsed)

        assert parsed.dialog_items[0].previous_item_id == existing.item_id

    @pytest.mark.asyncio
    async def test_no_previous_external_id(self):
        text_block = LLMResponseTextBlock(content="Reply")
        events = [text_block, StreamEnd(stop_reason=StopReason.END_TURN)]
        agent, connector, storage = await _setup_agent(events)

        parsed = OnParsedCtx(
            agent=agent,
            connector=connector,
            raw={},
            dialog_items=[make_dialog_item("reply")],
        )

        await agent._resolve_previous_item(parsed)
        assert parsed.dialog_items[0].previous_item_id is None


# ── Agent._store_history ────────────────────────────────────────────────────


class TestAgentStoreHistory:
    @pytest.mark.asyncio
    async def test_store_history_returns_last_id(self):
        agent, _, storage = await _setup_agent([])
        run = _make_run_ctx(agent)

        items = [
            make_dialog_item("a"),
            make_dialog_item("b"),
        ]

        last_id = await agent._store_history(run, items)
        assert last_id == 2
        assert items[0].item_id == 1
        assert items[1].item_id == 2

    @pytest.mark.asyncio
    async def test_store_history_none_returns_none(self):
        agent, _, storage = await _setup_agent([])
        run = _make_run_ctx(agent)

        last_id = await agent._store_history(run, None)
        assert last_id is None

    @pytest.mark.asyncio
    async def test_store_history_preserves_existing_ids(self):
        agent, _, storage = await _setup_agent([])
        run = _make_run_ctx(agent)

        items = [
            make_dialog_item("existing", item_id=99),
        ]

        last_id = await agent._store_history(run, items)
        assert last_id == 99
        # Should not be stored again
        assert len(storage._items) == 0


# ── Agent._handle_error ─────────────────────────────────────────────────────


class TestAgentHandleError:
    @pytest.mark.asyncio
    async def test_handle_error_fires_on_error(self):
        agent, _, _ = await _setup_agent([])

        errors: list[Exception] = []

        @_hook(agent, "on_error", priority=10)
        async def capture(ctx: OnErrorCtx):
            errors.append(ctx.error)
            ctx.suppress = True

        run = _make_run_ctx(agent)
        await agent._handle_error(run, ValueError("test"))

        assert len(errors) == 1
        assert isinstance(errors[0], ValueError)

    @pytest.mark.asyncio
    async def test_handle_error_re_raises_if_not_suppressed(self):
        agent, _, _ = await _setup_agent([])

        run = _make_run_ctx(agent)
        with pytest.raises(ValueError, match="test"):
            await agent._handle_error(run, ValueError("test"))
