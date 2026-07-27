# core/agent/agent.py
"""Agent orchestrator — the top-level entry point for CommaMatrix.

Agent creates all native managers, wires them into AgentLifecycle for lifecycle management,
and provides the public API: start(), stop(), handle(raw), and run().
Extensions are activated per-agent via add_extensions(), with optional workspace plugin auto-discovery.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from httpx import AsyncClient
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
    StreamDelta,
    StreamEnd,
    ToolCall,
    ToolCallResult,
)
from ...components.tool import ToolManager
from ...components.hook import HookManager
from ...components.instruction import InstructionManager
from ...components.connector import ConnectorManager
from ...components.llm_adapter import LLMAdapterManager
from ...components.storage import StorageManager, STORAGE_ATTRIBUTE
from ...components.file_storage import FileStorageManager, FILE_STORAGE_ATTRIBUTE
from ..classes.manager import ServiceInstanceManager, ServiceInstanceRegistry
from ..classes.service import AbstractService
from ..extensions import (
    ExtensionOperation,
    ExtensionRuntime,
    ExtensionRuntimeError,
    discover_plugin_targets,
)
from .runner import AgentRunner
from .lifecycle import AgentLifecycle


DEFAULT_HTTP_HEADERS: dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip",
    "Connection": "keep-alive",
}

http_default_headers = ConfigField[dict[str, str] | None](
    name="http_default_headers",
    default=None,
    description="Extra headers merged into the agent HTTP client defaults",
)

http_timeout = ConfigField[int](
    name="http_timeout",
    default=120,
    description="Default timeout in seconds for the agent HTTP client",
)

plugins_dir = ConfigField[str](
    name="plugins_dir",
    default="commamatrix_plugins",
    description="Directory to load extensions from when auto_load_plugins is True",
)


def _framework_prefix() -> str:
    """
    Package prefix for this framework installation (e.g. 'commamatrix' or 'src.commamatrix').
    Derived from the Agent module path to avoid double-import issues with the src/ layout.
    """
    parts = __name__.split(".")
    return ".".join(parts[: parts.index("commamatrix") + 1])


class Agent:
    """Orchestrates the agent lifecycle: parse -> LLM -> tools -> send.

    Creates all native managers during __init__, wires them into AgentLifecycle, and exposes convenience properties for direct access.
    """

    def __init__(
        self,
        *,
        config: dict[ConfigField, Any] | Config = {},
        auto_load_main: bool = True,
        auto_load_plugins: bool = True,
        essentials: bool = True,
    ):
        load_dotenv()
        if isinstance(config, dict):
            config = Config(overrides=config)
        self.config: Config = config
        self._auto_load_main = auto_load_main
        self._auto_load_plugins = auto_load_plugins
        self._essentials = essentials

        self.services = ServiceInstanceRegistry()
        self.runner = AgentRunner()
        self._started = False
        self._start_lock = asyncio.Lock()
        self._extension_runtime = ExtensionRuntime()
        self._http_client: AsyncClient | None = None

        self.tool_manager = ToolManager(agent=self)
        self.hook_manager = HookManager(agent=self)
        self.instruction_manager = InstructionManager(agent=self)
        self.llm_adapter = LLMAdapterManager(agent=self)
        self.storage = StorageManager(agent=self)
        self.file_storage = FileStorageManager(agent=self)
        self.service_manager: ServiceInstanceManager[AbstractService] = ServiceInstanceManager(agent=self)
        self.connector_manager = ConnectorManager(agent=self)

        self.manager = AgentLifecycle(registry=self.services, children=[
            self.tool_manager,
            self.hook_manager,
            self.instruction_manager,
            self.llm_adapter,
            self.storage,
            self.file_storage,
            self.service_manager,
            self.connector_manager,
        ])

        if self._auto_load_plugins:
            self._extension_runtime.apply(self._workspace_plugin_targets(), operation="add")

    @staticmethod
    def _workspace_plugin_targets() -> list[str]:
        root = Path.cwd() / "commamatrix_plugins"
        return [str(target) for target in discover_plugin_targets(root)]

    @property
    def _extension_scope(self) -> list[str]:
        return self._extension_runtime.scope_list

    @property
    def extension_scope(self) -> tuple[str, ...]:
        """Return the module names currently active for this agent."""
        return self._extension_runtime.scope

    @property
    def http_client(self) -> AsyncClient:
        """Shared HTTP client with browser-like defaults. Lazy-created on first access.

        Extra headers from ``http_default_headers`` config are merged on top of ``DEFAULT_HTTP_HEADERS``.
        Timeout is controlled by the ``http_timeout`` config field (default 120 s).
        """
        if self._http_client is None:
            headers = dict(DEFAULT_HTTP_HEADERS)
            extra = self.config.get(http_default_headers)
            if extra:
                headers.update(extra)
            self._http_client = AsyncClient(
                headers=headers,
                follow_redirects=True,
                timeout=self.config.get(http_timeout),
            )
        return self._http_client

    @staticmethod
    def _resolve_module_name(module_or_path: str | types.ModuleType) -> str | None:
        """Resolve an import name or filesystem path to a canonical module name."""
        return ExtensionRuntime.resolve_module_name(module_or_path)

    async def _apply_extensions(self, *module_or_path: str | types.ModuleType, operation: ExtensionOperation) -> list[str]:
        """Apply an extension operation and refresh active managers."""
        original_scope = list(self._extension_scope)
        try:
            handled = self._extension_runtime.apply(module_or_path, operation)
            if handled and self._started:
                self.manager.set_scope(self._extension_scope)
                await self.manager.refresh()
            return handled
        except Exception as exc:
            self._extension_runtime.replace_scope(original_scope)
            if isinstance(exc, ExtensionRuntimeError):
                raise
            raise RuntimeError("Failed to refresh extension managers") from exc

    async def add_extensions(self, *module_or_path: str | types.ModuleType) -> list[str]:
        """Activate modules or importable Python paths for this agent."""
        return await self._apply_extensions(*module_or_path, operation="add")

    async def remove_extensions(self, *module_or_path: str | types.ModuleType) -> list[str]:
        """Deactivate modules previously active for this agent."""
        return await self._apply_extensions(*module_or_path, operation="remove")

    async def reload_extensions(self, *module_or_path: str | types.ModuleType) -> list[str]:
        """Reload a module and all currently loaded submodules under its name."""
        return await self._apply_extensions(*module_or_path, operation="reload")

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
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
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

    async def _restore_chain_state(self, run: RunCtx, last_item_id: int | None) -> None:
        """Restore chain_state from the conversation branch ending at last_item_id."""
        if last_item_id is None:
            return
        branch = await self._load_dialog(last_item_id)
        for item in reversed(branch):
            chain = item.meta.get("chain")
            if isinstance(chain, dict):
                run.chain_state.update(chain)
                return

    async def run(
        self, run: RunCtx, history: list[DialogItem] | None = None
    ) -> AfterLlmCallCtx | None:
        """Run: LLM call -> tools -> send until no calls remain."""
        await self._ensure_started()
        error: Exception | None = None

        try:
            last_item_id = await self._store_history(run, history)
            await self._restore_chain_state(run, last_item_id)

            if (await self._before_run(run)).abort:
                return None

            async with self._typing(run):
                while True:
                    run.iteration += 1
                    run.tool_output_tail = None

                    dialog = await self._load_dialog(last_item_id)
                    tools_list = list(self.tool_manager.descriptors)
                    before_llm_ctx = BeforeLlmCallCtx(run=run, dialog=dialog, tools=tools_list)

                    await self.hook_manager.fire(HookEventType.BEFORE_LLM_CALL, before_llm_ctx)

                    stream = (run.connector.supports_streaming if run.connector else False)
                    blocks: list[LLMResponseBlock] = []
                    tool_calls: list[LLMResponseToolCallBlock] = []
                    llm_response: LLMResponse | None = None

                    async for event in self.llm_adapter.ask_llm(before_llm_ctx, stream=stream):
                        if isinstance(event, StreamDelta):
                            if run.connector:
                                await run.connector.send_stream_chunk(run.origin, event)
                        elif isinstance(event, LLMResponseBlock):
                            blocks.append(event)
                        elif isinstance(event, StreamEnd):
                            llm_response = LLMResponse(
                                content=blocks,
                                stop_reason=event.stop_reason,
                                usage=event.usage,
                                meta=event.meta,
                            )

                    if llm_response is None:
                        raise LLMResponseError("Adapter yielded no StreamEnd event")

                    # A tool call starts execution only after the complete assistant turn is delivered.
                    # Keep tool calls at the end of that turn so text/reasoning cannot appear between a  call and its result in the conversation timeline.
                    ordered_blocks = sorted(blocks, key=lambda _block: isinstance(_block, LLMResponseToolCallBlock))
                    llm_response.content = ordered_blocks
                    for event in ordered_blocks:
                        dialog_item = event.to_dialog_item(
                            role=DialogRole.ASSISTANT,
                            user=run.user,
                            origin=run.origin,
                            previous_item_id=last_item_id,
                        )
                        last_item_id = await self._send_and_store_item(run, dialog_item, last_item_id)
                        if isinstance(event, LLMResponseToolCallBlock):
                            tool_calls.append(event)

                    after_llm_ctx = AfterLlmCallCtx(run=run, response=llm_response)
                    await self.hook_manager.fire(HookEventType.AFTER_LLM_CALL, after_llm_ctx)
                    self._validate_response(after_llm_ctx.response)

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
            await self.hook_manager.fire(HookEventType.AFTER_RUN, AfterRunCtx(run=run, error=error))

    async def _ensure_started(self) -> None:
        """Lazy init: load .env, add defaults, start lifecycle, fire on_agent_start."""
        load_dotenv()
        async with self._start_lock:
            if not self._started:
                prefix = _framework_prefix()
                if self._auto_load_main:
                    await self.add_extensions("__main__")
                await self.add_extensions(prefix + ".components")
                if self._auto_load_plugins:
                    plugin_targets = self._workspace_plugin_targets()
                    if plugin_targets:
                        await self.add_extensions(*plugin_targets)
                if not self._scope_has_attribute(STORAGE_ATTRIBUTE):
                    await self.add_extensions(prefix + ".builtin.sqlite")
                if not self._scope_has_attribute(FILE_STORAGE_ATTRIBUTE):
                    await self.add_extensions(prefix + ".builtin.fs")
                if self._essentials:
                    from ...essentials import setup as _setup_essentials

                    await _setup_essentials(self)
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

    async def _store_history(
        self, run: RunCtx, history: list[DialogItem] | None
    ) -> int | None:
        """Persist items in a history batch and return the last item_id."""
        last_item_id: int | None = None
        if history is not None:
            for item in history:
                if item.item_id is None:
                    item.meta.setdefault("chain", {}).update(run.chain_state)
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
        """Fetch a provider-valid conversation branch from storage."""
        if last_item_id is None:
            return []

        dialog = await self.storage.get_branch(last_item_id)
        known_tool_call_ids: set[str] = set()
        result: list[DialogItem] = []
        for item in dialog:
            if item.item_type is DialogItemType.TOOL_CALL:
                try:
                    data = json.loads(item.content)
                    known_tool_call_ids.add(data["tool_call_id"])
                except (KeyError, TypeError, ValueError):
                    pass
                result.append(item)
                continue

            if item.item_type is DialogItemType.TOOL_CALL_RESULT:
                try:
                    data = json.loads(item.content)
                    if data["tool_call_id"] not in known_tool_call_ids:
                        continue
                except (KeyError, TypeError, ValueError):
                    continue

            result.append(item)
        return result

    async def _run_tool_lifecycle(
        self,
        run: RunCtx,
        tool_call: ToolCall,
        last_item_id: int | None = None,
        *,
        persist_result: bool = True,
        tool_meta: dict[str, Any] | None = None,
    ) -> tuple[int | None, ToolCallResult]:
        """Fire hooks and invoke a tool, optionally sending its result."""
        before_ctx = BeforeToolCallCtx(
            run=run,
            tool_call=tool_call,
            meta=dict(tool_meta or {}),
        )
        await self.hook_manager.fire(HookEventType.BEFORE_TOOL_CALL, before_ctx)

        effective_call = before_ctx.tool_call

        if before_ctx.abort_tool_call:
            result = ToolCallResult.aborted(
                effective_call.tool_call_id, before_ctx.abort_reason
            )
        else:
            result = await self.tool_manager.call(effective_call, ctx=before_ctx)

        after_ctx = AfterToolCallCtx(run=run, tool_call=effective_call, result=result)
        await self.hook_manager.fire(HookEventType.AFTER_TOOL_CALL, after_ctx)

        if not persist_result:
            return last_item_id, after_ctx.result

        async with run.tool_output_lock:
            tail = (
                run.tool_output_tail
                if run.tool_output_tail is not None
                else last_item_id
            )
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
        dialog_item.meta["chain"] = dict(run.chain_state)
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
        print(f"[Agent] ERROR in run {run.origin}: {type(error).__name__}: {error}", file=sys.stderr)
        ctx = OnErrorCtx(run=run, error=error)
        await self.hook_manager.fire(HookEventType.ON_ERROR, ctx)
        if not ctx.suppress:
            raise error

    @staticmethod
    def _validate_response(response: LLMResponse, _run: RunCtx | None = None) -> None:
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

    @staticmethod
    def _split_runs(parsed: OnParsedCtx) -> list[tuple[RunCtx, list[DialogItem]]]:
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
