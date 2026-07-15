# core/agent/agent.py
"""Agent orchestrator — the top-level entry point for CommaMatrix.

Agent creates all native managers, wires them into AgentLifecycle for
lifecycle management, and provides the public API: start(), stop(),
handle(raw), and run(). Extensions are activated per-agent via
add_extension() — no global auto-discovery.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import types
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Any

from ...components.config import Config, ConfigField
from ...components.dialog import DialogItem, DialogItemType, DialogRole
from ...components.hook import (
    AfterLlmCallCtx,
    AfterRunCtx,
    AfterToolCallCtx,
    BeforeLlmCallCtx,
    BeforeRunCtx,
    BeforeSendCtx,
    BeforeToolCallCtx,
    HookEventType,
    OnAgentStartCtx,
    OnErrorCtx,
    OnParsedCtx,
    RunCtx,
)
from ...components.llm_adapter import (
    LLMResponse,
    LLMResponseBlock,
    LLMResponseToolCallBlock,
    LLMResponseError,
    LLMTruncatedError,
    StopReason,
    ToolCall,
    ToolCallResult,
)
from ...components.tool import ToolManager
from ...components.hook import HookManager
from ...components.connector import ConnectorManager
from ...components.llm_adapter import LLMAdapterManager
from ...components.storage import StorageManager, STORAGE_ATTRIBUTE
from ...components.file_storage import FileStorageManager, FILE_STORAGE_ATTRIBUTE
from ..base.manager import ServiceInstanceManager
from .runner import AgentRunner
from .lifecycle import AgentLifecycle


def _framework_prefix() -> str:
    """Package prefix for this framework installation (e.g. 'commamatrix'
    or 'src.commamatrix').  Derived from the Agent module path to avoid
    double-import issues with the src/ layout."""
    parts = __name__.split('.')
    return '.'.join(parts[:parts.index('commamatrix') + 1])


class Agent:
    """Orchestrates the agent lifecycle: parse -> LLM -> tools -> send.

    Creates all native managers during __init__, wires them into
    AgentLifecycle, and exposes convenience properties for direct access.
    """

    def __init__(self, *, config: dict[ConfigField, Any] | Config = {}, auto_load_main: bool = True):
        if isinstance(config, dict):
            config = Config(overrides=config)
        self.config = config
        self._auto_load_main = auto_load_main

        self.services = ServiceIпомнnstanceRegistry()
        self.runner = AgentRunner()
        self._started = False
        self._start_lock = asyncio.Lock()
        self._extension_scope: list[str] = []

        self.tool_manager = ToolManager(agent=self)
        self.hook_manager = HookManager(agent=self)
        self.llm_adapter = LLMAdapterManager(agent=self)
        self.storage = StorageManager(agent=self)
        self.file_storage = FileStorageManager(agent=self)
        self.service_manager = ServiceInstanceManager(agent=self)
        self.connector_manager = ConnectorManager(agent=self)

        children = [
            self.tool_manager,
            self.hook_manager,
            self.llm_adapter,
            self.storage,
            self.file_storage,
            self.service_manager,
            self.connector_manager,
        ]
        self.manager = AgentLifecycle(children=children, registry=self.services)

    @staticmethod
    def _resolve_module_name(module_or_name: str | types.ModuleType) -> str:
        """Normalise extension specifier to a module name string."""
        if isinstance(module_or_name, str):
            return module_or_name
        if isinstance(module_or_name, types.ModuleType):
            return module_or_name.__name__
        raise TypeError(f"Expected str or module, got {type(module_or_name).__name__}")

    def add_extension(self, module_or_name: str | types.ModuleType) -> None:
        """Import a module and register it with all its submodules in this agent's scope."""
        module_name = self._resolve_module_name(module_or_name)
        if module_name not in self._extension_scope:
            self._extension_scope.append(module_name)
        if module_name not in sys.modules:
            importlib.import_module(module_name)

        prefix = module_name + "."
        for name in sorted(sys.modules):
            if name.startswith(prefix) and name not in self._extension_scope:
                self._extension_scope.append(name)

    async def remove_extension(self, module_or_name: str | types.ModuleType) -> None:
        """Remove a module and its submodules from this agent's scope and deactivate."""
        module_name = self._resolve_module_name(module_or_name)
        prefix = module_name + "."
        self._extension_scope = [
            m for m in self._extension_scope
            if m != module_name and not m.startswith(prefix)
        ]
        if self._started:
            self.manager.set_scope(self._extension_scope)
            await self.manager.refresh()

    async def refresh_extensions(self) -> None:
        """Propagate scope and refresh all services."""
        self.manager.set_scope(self._extension_scope)
        await self.manager.refresh()

    async def start(self) -> None:
        """Discover extensions, resolve connectors, and start listener tasks."""
        await self._ensure_started()

    async def stop(self) -> None:
        """Stop listeners, cancel active runs, and close agent-owned services."""
        await self.runner.stop()
        await self.manager.stop()
        self._started = False

    async def __aenter__(self) -> Agent:
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.stop()

    async def handle(self, raw: dict) -> None:
        """Parse an incoming event, and spawn runs per origin."""
        await self._ensure_started()
        parsed: OnParsedCtx | None = None
        connectors = self.connector_manager.resolve()
        for connector in connectors:
            parsed = await connector.parse(raw)
            if parsed is not None:
                break
        if parsed is None:
            return

        await self._resolve_previous_item(parsed)
        await self.hook_manager.fire(HookEventType.ON_PARSED, parsed)

        for run, history in self._split_runs(parsed):
            await self.runner.submit(
                self.runner.make_key(run.origin, run.user),
                self.run(run, history=history),
            )

    @asynccontextmanager
    async def _typing(self, run: RunCtx):
        """Wrap the run in connector.typing() if a connector is attached."""
        if run.connector:
            async with run.connector.typing(run.origin):
                yield
        else:
            yield

    async def run(self, run: RunCtx, history: list[DialogItem] | None = None) -> AfterLlmCallCtx | None:
        """Run: LLM call -> tools -> send until no calls remain."""
        await self._ensure_started()
        error: Exception | None = None

        try:
            if (await self._before_run(run)).abort:
                return None

            async with self._typing(run):

                last_item_id = await self._store_history(history)

                while True:
                    run.iteration += 1

                    after_llm_ctx = await self._call_llm(run, last_item_id)

                    last_item_id, used_tools = await self._execute_tools(run, after_llm_ctx.response, last_item_id)

                    if used_tools:
                        continue

                    await self._send_blocks(run, after_llm_ctx.response.content, last_item_id)

                    return after_llm_ctx

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            error = exc
            await self._handle_error(run, exc)

        finally:
            await self.hook_manager.fire(
                HookEventType.AFTER_RUN,
                AfterRunCtx(run=run, error=error)
            )

    async def _ensure_started(self) -> None:
        """Lazy init: add defaults, start lifecycle, fire on_agent_start."""
        async with self._start_lock:
            if not self._started:
                prefix = _framework_prefix()
                if self._auto_load_main:
                    self.add_extension("__main__")
                if not self._scope_has_attribute(STORAGE_ATTRIBUTE):
                    self.add_extension(prefix + '.builtin.sqlite')
                if not self._scope_has_attribute(FILE_STORAGE_ATTRIBUTE):
                    self.add_extension(prefix + '.builtin.fs')
                self.manager.set_scope(self._extension_scope)
                await self.manager.start()
                await self.hook_manager.fire(
                    HookEventType.ON_AGENT_START,
                    OnAgentStartCtx(agent=self),
                )
                self._started = True
            await self.refresh_extensions()

    async def _before_run(self, run: RunCtx) -> BeforeRunCtx:
        """Fire before_run hook and return the (possibly aborted) context."""
        ctx = BeforeRunCtx(run=run)
        await self.hook_manager.fire(HookEventType.BEFORE_RUN, ctx)
        return ctx

    async def _store_history(self, history: list[DialogItem] | None) -> int | None:
        """Persist items in a history batch and return the last item_id."""
        last_item_id: int | None = None
        if history is not None:
            for item in history:
                if item.item_id is None:
                    last_item_id = await self.storage.save_event(item)
                    if last_item_id is not None:
                        item.item_id = last_item_id
                else:
                    last_item_id = item.item_id
        return last_item_id

    async def _resolve_previous_item(self, parsed: OnParsedCtx) -> None:
        """Link the first dialog item to its replied-to message by external_id."""
        if parsed.previous_external_id and parsed.dialog_items:
            replied_item_id = await self.storage.find_item_id_by_external_id(
                parsed.previous_external_id,
                parsed.dialog_items[0].origin,
            )
            if replied_item_id is not None:
                parsed.dialog_items[0].previous_item_id = replied_item_id

    async def _load_dialog(self, last_item_id: int | None) -> list[DialogItem]:
        """Fetch the conversation branch starting from last_item_id."""
        if last_item_id is None:
            return []
        return await self.storage.get_branch(last_item_id)

    async def _call_llm(self, run: RunCtx, last_item_id: int | None) -> AfterLlmCallCtx:
        """Load dialog, fire before_llm, call adapter, fire after_llm, validate."""
        dialog = await self._load_dialog(last_item_id)

        tools_list = list(self.tool_manager.descriptors)
        before_llm_ctx = BeforeLlmCallCtx(run=run, dialog=dialog, tools=tools_list)

        await self.hook_manager.fire(HookEventType.BEFORE_LLM_CALL, before_llm_ctx)

        llm_response = await self.llm_adapter.ask_llm(before_llm_ctx)
        after_llm_ctx = AfterLlmCallCtx(run=run, response=llm_response)

        await self.hook_manager.fire(HookEventType.AFTER_LLM_CALL, after_llm_ctx)

        self._validate_response(after_llm_ctx.response, run)
        return after_llm_ctx

    async def _execute_tools(self, run: RunCtx, response: LLMResponse, last_item_id: int | None) -> tuple[int | None, bool]:
        """Persist tool call blocks and run full lifecycle for each."""
        tool_calls = [b for b in response.content if isinstance(b, LLMResponseToolCallBlock)]
        if not tool_calls:
            return last_item_id, False

        for block in tool_calls:
            call_item = DialogItem(
                content=block.content_str(),
                item_type=DialogItemType.TOOL_CALL,
                user=run.user,
                role=DialogRole.ASSISTANT,
                origin=run.origin,
                previous_item_id=last_item_id,
            )
            saved_id = await self.storage.save_event(call_item)
            if saved_id is not None:
                call_item.item_id = saved_id
                last_item_id = saved_id

            tool_call = ToolCall(
                tool_call_id=block.tool_call_id,
                tool_name=block.tool_name,
                tool_args=block.tool_args,
            )
            last_item_id, _ = await self._run_tool_lifecycle(run, tool_call, last_item_id)

        return last_item_id, True

    async def _run_tool_lifecycle(self, run: RunCtx, tool_call: ToolCall, last_item_id: int | None = None) -> tuple[int | None, ToolCallResult]:
        """Fire before/after_tool_call hooks, invoke tool, persist result."""
        before_ctx = BeforeToolCallCtx(run=run, tool_call=tool_call)
        await self.hook_manager.fire(HookEventType.BEFORE_TOOL_CALL, before_ctx)

        effective_call = before_ctx.tool_call

        if before_ctx.abort_tool_call:
            result = ToolCallResult.aborted(effective_call.tool_call_id, before_ctx.abort_reason)
        else:
            result = await self.tool_manager.call(effective_call, ctx=before_ctx)

        after_ctx = AfterToolCallCtx(run=run, tool_call=effective_call, result=result)
        await self.hook_manager.fire(HookEventType.AFTER_TOOL_CALL, after_ctx)

        final_result = after_ctx.result

        result_item = DialogItem(
            content=final_result.dump_json(),
            item_type=DialogItemType.TOOL_CALL_RESULT,
            user=run.user,
            role=DialogRole.TOOL,
            origin=run.origin,
            previous_item_id=last_item_id,
        )
        saved_id = await self.storage.save_event(result_item)
        if saved_id is not None:
            result_item.item_id = saved_id
            last_item_id = saved_id

        return last_item_id, final_result

    async def _send_blocks(
        self, run: RunCtx, blocks: list[LLMResponseBlock], last_item_id: int | None
    ) -> None:
        """Send non-tool-call blocks via connector and persist each one."""
        for block in blocks:
            if isinstance(block, LLMResponseToolCallBlock):
                continue

            dialog_item = block.to_dialog_item(
                role=DialogRole.ASSISTANT,
                user=run.user,
                origin=run.origin,
                previous_item_id=last_item_id,
            )

            before_send_ctx = BeforeSendCtx(run=run, dialog_item=dialog_item)
            await self.hook_manager.fire(HookEventType.BEFORE_SEND, before_send_ctx)

            if run.connector:
                external_id = await run.connector.send(run.origin, dialog_item)
                dialog_item.external_id = external_id

            saved_id = await self.storage.save_event(dialog_item)
            if saved_id is not None:
                dialog_item.item_id = saved_id
                last_item_id = saved_id

    async def _handle_error(self, run: RunCtx, error: Exception) -> None:
        """Fire on_error hook; re-raise unless suppressed."""
        ctx = OnErrorCtx(run=run, error=error)
        await self.hook_manager.fire(HookEventType.ON_ERROR, ctx)
        if not ctx.suppress:
            raise error

    def _validate_response(self, response: LLMResponse, run: RunCtx) -> None:
        """Raise if the LLM stopped with error or max_tokens."""
        if response.stop_reason == StopReason.ERROR:
            raise LLMResponseError("LLM returned error stop reason")
        if response.stop_reason == StopReason.MAX_TOKENS:
            raise LLMTruncatedError("LLM response truncated (max_tokens)")

    def _scope_has_attribute(self, attribute: str) -> bool:
        """Check whether any extension in the scope stamps the given marker."""
        for mod_name in self._extension_scope:
            mod = sys.modules.get(mod_name)
            if mod is None:
                continue
            for obj in vars(mod).values():
                if isinstance(obj, type) and getattr(obj, attribute, False):
                    return True
        return False

    def _split_runs(self, parsed: OnParsedCtx) -> list[tuple[RunCtx, list[DialogItem]]]:
        """Group parsed dialog items by origin; each group becomes one run."""
        by_origin: dict[str, list[DialogItem]] = defaultdict(list)
        for item in parsed.dialog_items:
            key = json.dumps(
                item.origin.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            )
            by_origin[key].append(item)

        result: list[tuple[RunCtx, list[DialogItem]]] = []
        for items in by_origin.values():
            first = items[0]
            run = RunCtx(
                agent=parsed.agent,
                connector=parsed.connector,
                origin=first.origin,
                user=first.user,
            )
            result.append((run, items))
        return result
