# core/agent/agent.py
"""Agent orchestrator — the top-level entry point for CommaMatrix.

Agent creates all native managers, wires them into AgentLifecycle for lifecycle management,
and provides the public API: start(), stop(), run_forever(), handle(raw), run(), and submit_run().
Extensions are activated per-agent via add_extensions(), with optional workspace plugin auto-discovery.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from collections import defaultdict
from collections.abc import Iterable, Iterator, MutableMapping
from contextlib import asynccontextmanager
from pathlib import Path
from traceback import format_exc
from uuid import uuid4

from typing import TYPE_CHECKING, Any, Callable, Literal, cast

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv() -> None:
        """Keep .env loading optional for the core package."""

from httpx2 import AsyncClient

from ...components.config import Config, ConfigField
from ...components.dialog import DialogItem, DialogItemType, DialogRole
from ...components.hook import (
    AfterLlmCallCtx,
    AfterRunCtx,
    AfterSendCtx,
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
    reasoning,
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
from ...components.storage import STORAGE_ATTRIBUTE
from ...components.file_storage import FILE_STORAGE_ATTRIBUTE
from ..classes.manager import ServiceInstanceRegistry
from ..extensions import (
    ExtensionOperation,
    ExtensionRuntime,
    ExtensionRuntimeError,
    MissingExtensionDependencyError,
    discover_plugin_targets,
)
from ...utils import FP, commamatrix_dir
from .runner import AgentRunner
from .lifecycle import AgentLifecycle

if TYPE_CHECKING:
    from ...components.connector import ConnectorManager
    from ...components.file_storage import FileStorageManager
    from ...components.hook import HookManager
    from ...components.http_client import HttpClient
    from ...components.instruction import InstructionManager
    from ...components.llm_adapter import LLMAdapterManager
    from ...components.server import Server
    from ...components.storage import StorageManager
    from ...components.table import TableManager
    from ...components.tool import ToolManager
    from ..classes.manager import ServiceInstanceManager
    from ..classes.service import AbstractService


plugins_dir = ConfigField[str](
    name="plugins_dir",
    default="plugins",
    description="Subdirectory of commamatrix_dir to load extensions from when auto_load_plugins is True",
)

agentic_model = ConfigField[str](
    name="agentic_model",
    default="",
    description="Substring used to select the default agent model; empty selects any model",
)


class AgentRegistry(MutableMapping[str, "Agent"]):
    """Resolve agents by their current, mutable names."""

    def __init__(self) -> None:
        self._agents: dict[int, Agent] = {}

    def register(self, agent: Agent) -> None:
        for agent_id, current in list(self._agents.items()):
            if current is not agent and current.name == agent.name:
                del self._agents[agent_id]
        self._agents[id(agent)] = agent

    def __getitem__(self, name: str) -> Agent:
        for agent in reversed(list(self._agents.values())):
            if agent.name == name:
                return agent
        raise KeyError(name)

    def __setitem__(self, name: str, agent: Agent) -> None:
        self.register(agent)

    def __delitem__(self, name: str) -> None:
        agent = self[name]
        del self._agents[id(agent)]

    def __iter__(self) -> Iterator[str]:
        names: set[str] = set()
        for agent in self._agents.values():
            if agent.name not in names:
                names.add(agent.name)
                yield agent.name

    def __len__(self) -> int:
        return len({agent.name for agent in self._agents.values()})


agent_by_name = AgentRegistry()


def get_subagent_by_name(name: str) -> Agent:
    """Return the agent registered under its current name."""
    return agent_by_name[name]


class Agent:
    """Orchestrates the agent lifecycle: parse -> LLM -> tools -> send."""

    if TYPE_CHECKING:
        tool_manager: ToolManager
        hook_manager: HookManager
        instruction_manager: InstructionManager
        llm_adapter: LLMAdapterManager
        storage: StorageManager
        table_manager: TableManager
        file_storage: FileStorageManager
        service_manager: ServiceInstanceManager[AbstractService]
        connector_manager: ConnectorManager
        http_server: Server
        scheduler: AbstractService | None

    def __init__(
            self,
            name: str,
            description: str = "",
            *,
            config: dict[ConfigField, Any] | Config = {},
            auto_load_main: bool = True,
            auto_load_plugins: bool = True,
    ):
        load_dotenv()
        self.name = name
        self.description = description
        agent_by_name.register(self)
        if isinstance(config, dict):
            config = Config(overrides=config)
        self.config: Config = config
        self._auto_load_main = auto_load_main
        self._auto_load_plugins = auto_load_plugins

        self.services = ServiceInstanceRegistry()
        self.runner = AgentRunner()
        self._started = False
        self._start_lock = asyncio.Lock()
        self._filesystem_lock = asyncio.Lock()
        self._extension_runtime = ExtensionRuntime()

        self.lifecycle = AgentLifecycle(registry=self.services, agent=self, auto_register=True)

        if self._auto_load_plugins:
            self._extension_runtime.apply(self._workspace_plugin_targets(), operation="add")

    def _workspace_plugin_targets(self) -> list[str]:
        root = (
            Path.cwd()
            / self.config.get(commamatrix_dir)
            / self.config.get(plugins_dir)
        )
        return [str(target) for target in discover_plugin_targets(root)]

    @property
    def _extension_scope(self) -> list[str]:
        return self._extension_runtime.scope_list

    @property
    def extension_scope(self) -> tuple[str, ...]:
        """Return the module names currently active for this agent."""
        return self._extension_runtime.scope

    def config_fields_markdown(self) -> str:
        """Return active extension configuration fields as Markdown sections."""
        def markdown_cell(value: object) -> str:
            return str(value).replace("|", r"\|").replace("\n", "<br>")

        fields: list[tuple[str, str, ConfigField[Any]]] = []
        seen: set[int] = set()
        for module_name in self._extension_scope:
            module = sys.modules.get(module_name)
            if module is None:
                continue
            for object_name, field in vars(module).items():
                if object_name.startswith("_") or not isinstance(field, ConfigField):
                    continue
                declaring_module = getattr(field, "_declaration_module", None)
                if declaring_module is not None and declaring_module != module_name:
                    continue
                if id(field) in seen:
                    continue
                seen.add(id(field))
                fields.append((module_name, object_name, field))

        if not fields:
            return "# Active Configuration Fields\n\nNo `ConfigField` declarations found in the active extension scope."

        lines = ["# Active Configuration Fields", ""]
        for module_name, object_name, field in fields:
            type_hint = getattr(field, "_type_hint", Any)
            type_name = getattr(type_hint, "__name__", str(type_hint).replace("typing.", ""))
            field_name = field.name or object_name
            heading = f"## {markdown_cell(field_name)}: {markdown_cell(type_name)}"
            if field.has_default:
                if callable(getattr(field, "_default", None)) and not isinstance(field._default, type):
                    default = "computed"
                else:
                    default = repr(field._default)
                heading += f" (default: {markdown_cell(default)})"
            lines.extend((heading, f"From: {markdown_cell(module_name)}"))
            if field.description:
                lines.append(markdown_cell(field.description))
            lines.append("")
        return "\n".join(lines).rstrip()

    def config_fields_info(self) -> str:
        """Return active extension configuration fields as Markdown."""
        return self.config_fields_markdown()

    def __getattr__(self, name: str) -> Any:
        lifecycle = self.__dict__.get("lifecycle")
        if lifecycle is not None and lifecycle.has_key(name):
            return lifecycle.get(name)
        raise AttributeError(f"{type(self).__name__!s} has no attribute {name!r}")

    @property
    def http_client(self) -> AsyncClient:
        """Return the shared HTTP client owned by the lifecycle component."""
        return cast("HttpClient", self.lifecycle.get("http_client")).client

    @staticmethod
    def _resolve_module_name(module_or_path: str | types.ModuleType) -> str | None:
        """Resolve an import name or filesystem path to a canonical module name."""
        return ExtensionRuntime.resolve_module_name(module_or_path)

    @staticmethod
    def _normalize_extension_targets(targets: Iterable[str | types.ModuleType | Iterable[str | types.ModuleType]]) -> tuple[str | types.ModuleType, ...]:
        normalized: list[str | types.ModuleType] = []
        for target in targets:
            if isinstance(target, (str, types.ModuleType)):
                normalized.append(target)
            elif isinstance(target, Iterable):
                normalized.extend(target)
            else:
                normalized.append(cast(str | types.ModuleType, target))
        return tuple(normalized)

    async def _apply_extensions(self, *module_or_path: str | types.ModuleType | Iterable[str | types.ModuleType], operation: ExtensionOperation) -> list[str]:
        """Apply an extension operation and refresh active managers."""
        original_scope = list(self._extension_scope)
        targets = self._normalize_extension_targets(module_or_path)
        try:
            handled = self._extension_runtime.apply(targets, operation)
            if handled:
                await self.lifecycle.sync_registered(self._extension_scope)
                self.lifecycle.set_scope(self._extension_scope)
                if self._started:
                    await self.lifecycle.refresh()
            return handled
        except Exception as exc:
            self._extension_runtime.replace_scope(original_scope)
            if isinstance(exc, ExtensionRuntimeError):
                raise
            raise RuntimeError("Failed to refresh extension managers") from exc

    async def add_extensions(self, *module_or_path: str | types.ModuleType | Iterable[str | types.ModuleType]) -> list[str]:
        """Activate modules, paths, or iterables of them for this agent."""
        return await self._apply_extensions(*module_or_path, operation="add")

    async def remove_extensions(self,  *module_or_path: str | types.ModuleType | Iterable[str | types.ModuleType]) -> list[str]:
        """Deactivate modules previously active for this agent."""
        return await self._apply_extensions(*module_or_path, operation="remove")

    async def reload_extensions(self, *module_or_path: str | types.ModuleType | Iterable[str | types.ModuleType]) -> list[str]:
        """Reload a module and all currently loaded submodules under its name."""
        return await self._apply_extensions(*module_or_path, operation="reload")

    async def refresh_extensions(self) -> None:
        """Propagate scope and refresh all services."""
        await self.lifecycle.sync_registered(self._extension_scope)
        self.lifecycle.set_scope(self._extension_scope)
        await self.lifecycle.refresh()

    async def start(self) -> None:
        """Discover extensions, resolve connectors, and start listener tasks."""
        await self._ensure_started()

    async def stop(self) -> None:
        """Stop scheduled/listener services, then cancel active runs."""
        await self.lifecycle.stop()
        await self.runner.stop()
        self._started = False

    async def run_forever(self) -> None:
        """Start the agent and keep it alive until the task is cancelled."""
        async with self:
            await asyncio.Event().wait()

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
            print("[Agent DEBUG] handle no connector parsed the event", file=sys.stderr)
            return []

        print(
            f"[Agent DEBUG] handle parsed items={len(parsed.dialog_items)} previous_external_id={parsed.previous_external_id!r} ids={[item.item_id for item in parsed.dialog_items]}",
            file=sys.stderr
        )
        await self._resolve_previous_item(parsed)
        await self.hook_manager.fire(HookEventType.ON_PARSED, parsed)

        tasks: list[asyncio.Task] = []
        for run, history in self._split_runs(parsed):
            print(f"[Agent DEBUG] submit run origin={run.origin} user={run.user!r} history_ids={[item.item_id for item in history]}", file=sys.stderr)
            task = await self.runner.submit(self.runner.make_key(run.origin, run.user), self.run(run, history=history))
            if task is not None:
                tasks.append(task)
        print(f"[Agent DEBUG] handle submitted tasks={len(tasks)}", file=sys.stderr)
        return tasks

    async def submit_run(
        self,
        *,
        parent_item_id: int | None = None,
        instructions: str | None = None,
        dialog_items: list[DialogItem] | None = None,
        tools: str | None,
        user: str = "agent",
        meta: dict[str, Any] | None = None,
        state: dict[str, Any] | None = None,
        wait_for_result: bool = True,
        conflict_policy: Literal["replace", "skip"] = "skip",
        runner_namespace: str = "subagent",
        runner_key: str | None = None,
        on_error: Callable[[Exception], Any] | None = None,
    ) -> AfterLlmCallCtx | str | None:
        """Forward a headless run to the optional subagent extension."""
        from ...builtin.subagent import submit_run as submit_subagent_run

        return await submit_subagent_run(
            self,
            parent_item_id=parent_item_id,
            instructions=instructions,
            dialog_items=dialog_items,
            tools=tools,
            user=user,
            meta=meta,
            state=state,
            wait_for_result=wait_for_result,
            conflict_policy=conflict_policy,
            runner_namespace=runner_namespace,
            runner_key=runner_key,
            on_error=on_error,
        )

    @asynccontextmanager
    async def _typing(self, run: RunCtx):
        """Wrap the run in typing for its current origin."""
        connector = self.connector_manager.resolve_for_origin(run.origin)
        async with connector.typing(run.origin):
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

    async def run(self, run: RunCtx, history: list[DialogItem] | None = None) -> AfterLlmCallCtx | None:
        """Run: LLM call -> tools -> send until no calls remain."""
        await self._ensure_started()
        error: Exception | None = None

        try:
            last_item_id = await self._store_history(run, history)
            run.last_item_id = last_item_id
            await self._restore_chain_state(run, last_item_id)
            if run.state.get("subagent"):
                run.chain_state["allowed_tools"] = run.state["allowed_tools"]

            if (await self._before_run(run)).abort:
                return None
            self._select_model(run)

            async with self._typing(run):
                while True:
                    run.iteration += 1
                    run.tool_output_tail = None

                    dialog = await self._load_dialog(last_item_id)
                    tools_list = list(self.tool_manager.descriptors)
                    selected_adapter = run.adapter
                    selected_llm = run.llm
                    before_llm_ctx = BeforeLlmCallCtx(
                        run=run,
                        dialog=dialog,
                        tools=tools_list,
                        reasoning=self._resolve_reasoning(run),
                    )

                    await self.hook_manager.fire(HookEventType.BEFORE_LLM_CALL, before_llm_ctx)
                    if run.adapter is not selected_adapter or run.llm is not selected_llm:
                        before_llm_ctx.reasoning = self._resolve_reasoning(run)

                    connector = self.connector_manager.resolve_for_origin(run.origin)
                    stream = connector.supports_streaming
                    blocks: list[LLMResponseBlock] = []
                    tool_calls: list[LLMResponseToolCallBlock] = []
                    tool_parent_item_ids: list[int | None] = []
                    llm_response: LLMResponse | None = None
                    stream_ids: dict[str, str] = {}

                    async for event in self.llm_adapter.ask_llm(before_llm_ctx, stream=stream):
                        if isinstance(event, StreamDelta):
                            stream_key = event.delta_type
                            if event.delta_type == "tool_call":
                                tool_index = event.meta.get("tool_call_index")
                                tool_id = event.meta.get("tool_call_id")
                                tool_key = tool_index if tool_index is not None else tool_id
                                if tool_key is not None:
                                    stream_key = f"tool_call:{tool_key}"
                            stream_id = stream_ids.setdefault(stream_key, f"stream:{uuid4().hex}")
                            event.meta["stream_id"] = stream_id
                            event.meta["previous_item_id"] = last_item_id
                            await connector.send_stream_chunk(run.origin, event)
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
                    # Keep tool calls at the end of that turn so text/reasoning cannot appear between a call and its result in the conversation timeline.
                    ordered_blocks = sorted(blocks, key=lambda _block: isinstance(_block, LLMResponseToolCallBlock))
                    llm_response.content = ordered_blocks
                    for event in ordered_blocks:
                        previous_item_id = last_item_id
                        dialog_item = event.to_dialog_item(
                            role=DialogRole.ASSISTANT,
                            user=run.user,
                            origin=run.origin,
                            previous_item_id=previous_item_id,
                        )
                        last_item_id = await self._send_and_store_item(run, dialog_item, last_item_id)
                        if isinstance(event, LLMResponseToolCallBlock):
                            tool_calls.append(event)
                            tool_parent_item_ids.append(previous_item_id)

                    after_llm_ctx = AfterLlmCallCtx(run=run, response=llm_response)
                    await self.hook_manager.fire(HookEventType.AFTER_LLM_CALL, after_llm_ctx)
                    self._validate_response(after_llm_ctx.response)

                    for block, parent_item_id in zip(tool_calls, tool_parent_item_ids):
                        run.state["child_parent_item_id"] = parent_item_id
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
            if run.last_item_id is not None:
                try:
                    run.dialog_items = await self._load_dialog(run.last_item_id)
                except Exception:
                    run.dialog_items = []
            await self.hook_manager.fire(HookEventType.AFTER_RUN, AfterRunCtx(run=run, error=error))

    async def _ensure_started(self) -> None:
        """Lazy init: load .env, add defaults, start lifecycle, fire on_agent_start."""
        load_dotenv()
        async with self._start_lock:
            if not self._started:
                Path(self.config.get(commamatrix_dir)).mkdir(parents=True, exist_ok=True)
                if self._auto_load_main:
                    await self.add_extensions("__main__")
                await self.add_extensions(FP + ".components")
                await self.add_extensions(FP + ".builtin.filesystem")
                if self._auto_load_plugins:
                    (Path.cwd() / self.config.get(commamatrix_dir) / self.config.get(plugins_dir)).mkdir(parents=True, exist_ok=True)
                    plugin_targets = self._workspace_plugin_targets()
                    if plugin_targets:
                        await self.add_extensions(*plugin_targets)
                if not self._scope_has_attribute(STORAGE_ATTRIBUTE):
                    try:
                        await self.add_extensions(FP + ".builtin.sql.sqlite_storage")
                    except MissingExtensionDependencyError as exc:
                        if exc.dependency_module != "aiosqlite":
                            raise
                if not self._scope_has_attribute(FILE_STORAGE_ATTRIBUTE):
                    await self.add_extensions(FP + ".builtin.simple_fs")
                await self.lifecycle.sync_registered(self._extension_scope)
                self.lifecycle.set_scope(self._extension_scope)
                await self.lifecycle.start()
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

    @staticmethod
    def _resolve_reasoning(run: RunCtx) -> str | None:
        if run.adapter is None or run.llm is None:
            return None
        return run.adapter.resolve_reasoning_mode(run.llm)

    def _select_model(self, run: RunCtx) -> None:
        if run.adapter is not None and run.llm is not None:
            return

        if run.adapter is not None:
            available = [(run.adapter, llm) for llm in run.adapter.llms]
        elif run.llm is not None:
            adapter = self.llm_adapter.resolve_adapter(run.llm)
            if adapter is None:
                raise RuntimeError(f"No adapter provides the selected LLM '{run.llm.model_name}'")
            run.adapter = adapter
            return
        else:
            available = list(self.llm_adapter.iter_llms())

        if not available:
            raise RuntimeError("No LLM models available")

        model_filter = self.config.get(agentic_model)
        if model_filter:
            available = [
                (adapter, llm)
                for adapter, llm in available
                if model_filter in llm.model_name
            ]
            if not available:
                raise RuntimeError(
                    f"No LLM model matches agentic_model '{model_filter}'"
                )

        adapter, llm = min(available, key=lambda item: item[1].cost.input_tokens)
        run.adapter = adapter
        run.llm = llm

    async def _store_history(self, run: RunCtx, history: list[DialogItem] | None) -> int | None:
        """Persist items in a history batch and return the last item_id."""
        last_item_id: int | None = run.last_item_id
        if history is not None:
            for item in history:
                if item.item_id is None:
                    if last_item_id is not None and item.previous_item_id is None:
                        item.previous_item_id = last_item_id
                    item.meta.setdefault("chain", {}).update(run.chain_state)
                    print(f"[Agent DEBUG] save input item_type={item.item_type.value} previous_item_id={item.previous_item_id} external_id={item.external_id!r} origin={item.origin}", file=sys.stderr)
                    last_item_id = await self.storage.save_event(item)
                    print(f"[Agent DEBUG] saved input item_id={last_item_id}", file=sys.stderr)
                    if last_item_id is not None:
                        item.item_id = last_item_id
                        run.last_item_id = last_item_id
                        connector = self.connector_manager.resolve_for_origin(item.origin)
                        print(f"[Agent DEBUG] publish input item_id={item.item_id} connector={type(connector).__name__}", file=sys.stderr)
                        await connector.publish_item(item.origin, item)
                else:
                    last_item_id = item.item_id
                    run.last_item_id = last_item_id
        return last_item_id

    async def _resolve_previous_item(self, parsed: OnParsedCtx) -> None:
        """Link the first dialog item to its replied-to message by external_id."""
        if parsed.previous_external_id and parsed.dialog_items:
            replied_item_id = await self.storage.find_item_id_by_external_id(
                parsed.previous_external_id,
                parsed.dialog_items[0].origin,
            )
            print(f"[Agent DEBUG] resolve previous external_id={parsed.previous_external_id!r} -> item_id={replied_item_id}", file=sys.stderr)
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
            run.pending_input_items.extend(before_ctx.follow_up_items)
            return last_item_id, after_ctx.result

        follow_up_items = [*run.pending_input_items, *before_ctx.follow_up_items]
        run.pending_input_items.clear()

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
            for follow_up_item in follow_up_items:
                follow_up_item.previous_item_id = last_item_id
                last_item_id = await self._send_and_store_item(run, follow_up_item, last_item_id)
            run.tool_output_tail = last_item_id

        return last_item_id, after_ctx.result

    async def _send_and_store_item(self, run: RunCtx, dialog_item: DialogItem, last_item_id: int | None) -> int | None:
        """Let the connector render an item, then persist it regardless of delivery."""
        dialog_item.meta["chain"] = dict(run.chain_state)
        before_send_ctx = BeforeSendCtx(run=run, dialog_item=dialog_item)
        await self.hook_manager.fire(HookEventType.BEFORE_SEND, before_send_ctx)

        connector = self.connector_manager.resolve_for_origin(run.origin)
        print(f"[Agent DEBUG] send item_type={dialog_item.item_type.value} previous_item_id={dialog_item.previous_item_id} connector={type(connector).__name__}", file=sys.stderr)
        external_id = await connector.send(run.origin, dialog_item)
        dialog_item.external_id = external_id or None
        print(f"[Agent DEBUG] sent external_id={dialog_item.external_id!r}", file=sys.stderr)

        saved_id = await self.storage.save_event(dialog_item)
        print(f"[Agent DEBUG] saved output item_id={saved_id} external_id={dialog_item.external_id!r}", file=sys.stderr)
        if saved_id is not None:
            dialog_item.item_id = saved_id
            run.last_item_id = saved_id
            await connector.publish_item(dialog_item.origin, dialog_item)
        await self.hook_manager.fire(HookEventType.AFTER_SEND, AfterSendCtx(run=run, dialog_item=dialog_item, external_id=dialog_item.external_id))
        return saved_id if saved_id is not None else last_item_id

    async def _handle_error(self, run: RunCtx, error: Exception) -> None:
        """Fire on_error hook; re-raise unless suppressed."""
        print(f"[Agent] ERROR in run {run.origin}: {type(error).__name__}: {error}\n{format_exc()}", file=sys.stderr)
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

