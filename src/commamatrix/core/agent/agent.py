# core/agent/agent.py
"""Agent orchestrator — the top-level entry point for CommaMatrix.

Agent creates all native managers, wires them into AgentLifecycle for
lifecycle management, and provides the public API: start(), stop(),
handle(raw), and run(). Extensions are activated per-agent via
add_extensions() — no global auto-discovery.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import types
from dotenv import load_dotenv
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Any, Callable

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
    StreamDelta,
    StreamEnd,
    ToolCall,
    ToolCallResult,
)
from ...components.tool import ToolManager
from ...components.hook import HookManager
from ...components.instruction import InstructionManager
from ...components.connector import ConnectorManager, CONNECTOR_ATTRIBUTE as CONNECTOR_ATTR
from ...components.llm_adapter import LLMAdapterManager
from ...components.storage import StorageManager, STORAGE_ATTRIBUTE
from ...components.file_storage import FileStorageManager, FILE_STORAGE_ATTRIBUTE
from ..classes.manager import ServiceInstanceManager, ServiceInstanceRegistry
from ..classes.service import AbstractService
from .runner import AgentRunner
from .lifecycle import AgentLifecycle


def _http_deps_available() -> bool:
    """Check if starlette and uvicorn are installed."""
    try:
        import starlette  # noqa: F401
        import uvicorn  # noqa: F401
        return True
    except ImportError:
        return False


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

    def __init__(self, *, config: dict[ConfigField, Any] | Config = {}, auto_load_main: bool = True, auto_load_http: bool = True):
        load_dotenv()
        if isinstance(config, dict):
            config = Config(overrides=config)
        self.config: Config = config
        self._auto_load_main = auto_load_main
        if auto_load_http and not _http_deps_available():
            print("Warning: starlette and/or uvicorn not installed. HTTP server disabled. Install with: pip install commamatrix[http]")
            auto_load_http = False
        self._auto_load_http = auto_load_http

        self.services = ServiceInstanceRegistry()
        self.runner = AgentRunner()
        self._started = False
        self._start_lock = asyncio.Lock()
        self._extension_scope: list[str] = []

        self.tool_manager = ToolManager(agent=self)
        self.hook_manager = HookManager(agent=self)
        self.instruction_manager = InstructionManager(agent=self)
        self.llm_adapter = LLMAdapterManager(agent=self)
        self.storage = StorageManager(agent=self)
        self.file_storage = FileStorageManager(agent=self)
        self.service_manager: ServiceInstanceManager[AbstractService] = ServiceInstanceManager(agent=self)
        self.connector_manager = ConnectorManager(agent=self)

        children = [
            self.tool_manager,
            self.hook_manager,
            self.instruction_manager,
            self.llm_adapter,
            self.storage,
            self.file_storage,
            self.service_manager,
            self.connector_manager,
        ]
        self.manager = AgentLifecycle(children=children, registry=self.services)

    @staticmethod
    def _resolve_module_name(module_or_name: str | types.ModuleType) -> str | None:
        """Normalize extension specifier to a module name string, or None if invalid."""
        if isinstance(module_or_name, str):
            return module_or_name
        if isinstance(module_or_name, types.ModuleType):
            return module_or_name.__name__
        return None

    async def _apply_extensions(
        self,
        *module_or_name: str | types.ModuleType,
        handler: Callable[[str], bool],
    ) -> list[str]:
        """Iterate entries, resolve names, skip invalid, call *handler* per valid name.

        *handler* receives a resolved module name and returns ``True`` if the
        operation succeeded.  After all entries are processed the scope is
        propagated and managers are refreshed when the agent is started and
        at least one entry was handled.
        """
        handled: list[str] = []
        for entry in module_or_name:
            module_name = self._resolve_module_name(entry)
            if module_name is None:
                continue
            try:
                if handler(module_name):
                    handled.append(module_name)
            except Exception:
                continue
        if handled and self._started:
            self.manager.set_scope(self._extension_scope)
            await self.manager.refresh()
        return handled

    def _do_add(self, module_name: str) -> bool:
        if module_name not in self._extension_scope:
            self._extension_scope.append(module_name)
        if module_name not in sys.modules:
            importlib.import_module(module_name)
        prefix = module_name + "."
        for name in sorted(sys.modules):
            if name.startswith(prefix) and name not in self._extension_scope:
                self._extension_scope.append(name)
        return True

    def _do_remove(self, module_name: str) -> bool:
        prefix = module_name + "."
        before = len(self._extension_scope)
        self._extension_scope = [
            m for m in self._extension_scope
            if m != module_name and not m.startswith(prefix)
        ]
        return len(self._extension_scope) < before

    def _do_reload(self, module_name: str) -> bool:
        prefix = module_name + "."
        submodules = [n for n in self._extension_scope if n == module_name or n.startswith(prefix)]
        for name in submodules:
            sys.modules.pop(name, None)
        importlib.import_module(module_name)
        new_prefix_modules = [
            n for n in sorted(sys.modules)
            if n.startswith(prefix) and n not in self._extension_scope
        ]
        alive = {module_name, *new_prefix_modules}
        self._extension_scope = [
            n for n in self._extension_scope
            if n != module_name and not n.startswith(prefix)
        ]
        for name in sorted(alive):
            if name not in self._extension_scope:
                self._extension_scope.append(name)
        return True

    async def add_extensions(self, *module_or_name: str | types.ModuleType) -> list[str]:
        """Import modules and register them with submodules in this agent's scope.

        Returns names that were successfully imported. Invalid specifiers are silently skipped.
        """
        return await self._apply_extensions(*module_or_name, handler=self._do_add)

    async def remove_extensions(self, *module_or_name: str | types.ModuleType) -> list[str]:
        """Remove modules and their submodules from scope and deactivate.

        Returns names that were successfully removed. Invalid specifiers are silently skipped.
        """
        return await self._apply_extensions(*module_or_name, handler=self._do_remove)

    async def reload_extensions(self, *module_or_name: str | types.ModuleType) -> list[str]:
        """Reload modules from disk and refresh all managers.

        Purges each module and its submodules from sys.modules, re-imports them,
        updates the extension scope, and triggers a full manager refresh so descriptors pick up the new code.

        Returns names that were successfully reloaded. Invalid specifiers are silently skipped.
        """
        return await self._apply_extensions(*module_or_name, handler=self._do_reload)

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

    async def handle(self, raw: dict) -> list[asyncio.Task]:
        """Parse an incoming event, and spawn runs per origin.

        Returns the list of created run tasks so that transports that
        need synchronous completion (e.g. HTTP) can await them.
        """
        await self._ensure_started()
        parsed: OnParsedCtx | None = None
        connectors = self.connector_manager.resolve()
        for connector in connectors:
            parsed = await connector.parse(raw)
            if parsed is not None:
                break
        if parsed is None:
            return []

        await self._resolve_previous_item(parsed)
        await self.hook_manager.fire(HookEventType.ON_PARSED, parsed)

        tasks: list[asyncio.Task] = []
        for run, history in self._split_runs(parsed):
            task = await self.runner.submit(
                self.runner.make_key(run.origin, run.user),
                self.run(run, history=history),
            )
            tasks.append(task)
        return tasks

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

                    dialog = await self._load_dialog(last_item_id)
                    tools_list = list(self.tool_manager.descriptors)
                    before_llm_ctx = BeforeLlmCallCtx(run=run, dialog=dialog, tools=tools_list)
                    await self.hook_manager.fire(HookEventType.BEFORE_LLM_CALL, before_llm_ctx)

                    stream = run.connector.supports_streaming if run.connector else False
                    blocks: list[LLMResponseBlock] = []
                    tool_calls: list[LLMResponseToolCallBlock] = []
                    llm_response: LLMResponse | None = None

                    async for event in self.llm_adapter.ask_llm(before_llm_ctx, stream=stream):
                        if isinstance(event, StreamDelta):
                            if run.connector:
                                await run.connector.send_stream_chunk(run.origin, event)
                        elif isinstance(event, LLMResponseBlock):
                            blocks.append(event)
                            dialog_item = event.to_dialog_item(
                                role=DialogRole.ASSISTANT, user=run.user,
                                origin=run.origin, previous_item_id=last_item_id,
                            )
                            last_item_id = await self._send_and_store_item(run, dialog_item, last_item_id)
                            if isinstance(event, LLMResponseToolCallBlock):
                                tool_calls.append(event)
                        elif isinstance(event, StreamEnd):
                            llm_response = LLMResponse(
                                content=blocks,
                                stop_reason=event.stop_reason,
                                usage=event.usage,
                                meta=event.meta,
                            )

                    if llm_response is None:
                        raise LLMResponseError("Adapter yielded no StreamEnd event")
                    after_llm_ctx = AfterLlmCallCtx(run=run, response=llm_response)
                    await self.hook_manager.fire(HookEventType.AFTER_LLM_CALL, after_llm_ctx)
                    self._validate_response(after_llm_ctx.response, run)

                    for block in tool_calls:
                        tool_call = ToolCall(
                            tool_call_id=block.tool_call_id,
                            tool_name=block.tool_name,
                            tool_args=block.tool_args,
                        )
                        last_item_id, _ = await self._run_tool_lifecycle(run, tool_call, last_item_id)

                    if tool_calls:
                        continue

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
        """Lazy init: load .env, add defaults, start lifecycle, fire on_agent_start."""
        load_dotenv()
        async with self._start_lock:
            if not self._started:
                prefix = _framework_prefix()
                if self._auto_load_main:
                    await self.add_extensions("__main__")
                await self.add_extensions(prefix + '.components.instruction')
                if not self._scope_has_attribute(STORAGE_ATTRIBUTE):
                    await self.add_extensions(prefix + '.builtin.sqlite')
                if not self._scope_has_attribute(FILE_STORAGE_ATTRIBUTE):
                    await self.add_extensions(prefix + '.builtin.fs')
                if self._auto_load_http:
                    await self.add_extensions(prefix + '.builtin.http_connector')
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

    async def _run_tool_lifecycle(self, run: RunCtx, tool_call: ToolCall, last_item_id: int | None = None) -> tuple[int | None, ToolCallResult]:
        """Fire hooks, invoke a tool, then send and persist its result."""
        before_ctx = BeforeToolCallCtx(run=run, tool_call=tool_call)
        await self.hook_manager.fire(HookEventType.BEFORE_TOOL_CALL, before_ctx)

        effective_call = before_ctx.tool_call

        if before_ctx.abort_tool_call:
            result = ToolCallResult.aborted(effective_call.tool_call_id, before_ctx.abort_reason)
        else:
            result = await self.tool_manager.call(effective_call, ctx=before_ctx)

        after_ctx = AfterToolCallCtx(run=run, tool_call=effective_call, result=result)
        await self.hook_manager.fire(HookEventType.AFTER_TOOL_CALL, after_ctx)

        async with run.tool_output_lock:
            tail = run.tool_output_tail if run.tool_output_tail is not None else last_item_id
            result_item = DialogItem(
                content=after_ctx.result.dump_json(),
                item_type=DialogItemType.TOOL_CALL_RESULT,
                user=run.user,
                role=DialogRole.TOOL,
                origin=run.origin,
                previous_item_id=tail,
            )
            last_item_id = await self._send_and_store_item(run, result_item, tail)
            run.tool_output_tail = last_item_id

        return last_item_id, after_ctx.result

    async def _send_and_store_item(self, run: RunCtx, dialog_item: DialogItem, last_item_id: int | None) -> int | None:
        """Let the connector render an item, then persist it regardless of delivery."""
        before_send_ctx = BeforeSendCtx(run=run, dialog_item=dialog_item)
        await self.hook_manager.fire(HookEventType.BEFORE_SEND, before_send_ctx)

        if run.connector:
            external_id = await run.connector.send(run.origin, dialog_item)
            dialog_item.external_id = external_id or None

        saved_id = await self.storage.save_event(dialog_item)
        if saved_id is not None:
            dialog_item.item_id = saved_id
            return saved_id
        return last_item_id

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
        if response.stop_reason == StopReason.LENGTH:
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
