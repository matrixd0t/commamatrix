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
from pathlib import Path
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
from ...components.connector import ConnectorManager
from ...components.llm_adapter import LLMAdapterManager
from ...components.storage import StorageManager, STORAGE_ATTRIBUTE
from ...components.file_storage import FileStorageManager, FILE_STORAGE_ATTRIBUTE
from ..classes.manager import ServiceInstanceManager, ServiceInstanceRegistry
from ..classes.service import AbstractService
from .runner import AgentRunner
from .lifecycle import AgentLifecycle


def _framework_prefix() -> str:
    """Package prefix for this framework installation (e.g. 'commamatrix'
    or 'src.commamatrix').  Derived from the Agent module path to avoid
    double-import issues with the src/ layout."""
    parts = __name__.split(".")
    return ".".join(parts[: parts.index("commamatrix") + 1])


class Agent:
    """Orchestrates the agent lifecycle: parse -> LLM -> tools -> send.

    Creates all native managers during __init__, wires them into
    AgentLifecycle, and exposes convenience properties for direct access.
    """

    def __init__(
        self,
        *,
        config: dict[ConfigField, Any] | Config = {},
        auto_load_main: bool = True,
        essentials: bool = True,
    ):
        load_dotenv()
        if isinstance(config, dict):
            config = Config(overrides=config)
        self.config: Config = config
        self._auto_load_main = auto_load_main
        self._essentials = essentials

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
        self.service_manager: ServiceInstanceManager[AbstractService] = (
            ServiceInstanceManager(agent=self)
        )
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

    @property
    def extension_scope(self) -> tuple[str, ...]:
        """Return the module names currently active for this agent."""
        return tuple(self._extension_scope)

    @staticmethod
    def _resolve_module_name(module_or_path: str | types.ModuleType) -> str | None:
        """Resolve an import name or filesystem path to a canonical module name."""
        if isinstance(module_or_path, str):
            path = Path(module_or_path).expanduser()
            looks_like_path = (
                path.exists()
                or path.is_absolute()
                or path.parent != Path(".")
                or path.suffix.lower() == ".py"
            )
            if looks_like_path:
                return Agent._module_name_from_path(path)
            return module_or_path
        if isinstance(module_or_path, types.ModuleType):
            return module_or_path.__name__
        return None

    @staticmethod
    def _module_name_from_path(path: Path) -> str:
        """Resolve a Python path to its importable name without synthetic modules."""
        resolved = path.resolve()
        if resolved.is_dir():
            source_path = resolved / "__init__.py"
            module_path = resolved
        elif resolved.is_file() and resolved.suffix.lower() == ".py":
            source_path = resolved
            module_path = resolved.parent if resolved.name == "__init__.py" else resolved.with_suffix("")
        else:
            raise ImportError(f"Extension path is not a Python module: {path}")

        for module_name, module in tuple(sys.modules.items()):
            module_file = getattr(module, "__file__", None)
            if module_file is not None:
                try:
                    if Path(str(module_file)).resolve() == source_path.resolve():
                        return module_name
                except OSError:
                    continue

        roots: list[Path] = [Path.cwd()]
        roots.extend(Path(entry or Path.cwd()) for entry in sys.path)
        candidates: list[tuple[int, int, int, str, Path]] = []
        seen_roots: set[Path] = set()
        for index, root in enumerate(roots):
            try:
                root = root.resolve()
            except OSError:
                continue
            if root in seen_roots:
                continue
            seen_roots.add(root)
            try:
                relative = module_path.relative_to(root)
            except ValueError:
                continue
            parts = relative.parts
            if not parts or not all(part.isidentifier() for part in parts):
                continue
            first_loaded = int(parts[0] in sys.modules)
            candidates.append((first_loaded, len(root.parts), -index, ".".join(parts), root))

        if candidates:
            _, _, _, module_name, import_root = max(candidates)
        else:
            package_parts: list[str] = []
            package_dir = resolved.parent if resolved.is_file() else resolved
            while (package_dir / "__init__.py").is_file():
                package_parts.insert(0, package_dir.name)
                package_dir = package_dir.parent
            leaf = [] if resolved.is_dir() or resolved.name == "__init__.py" else [resolved.stem]
            parts = package_parts + leaf
            if not parts or not all(part.isidentifier() for part in parts):
                raise ImportError(f"Cannot derive an importable module name from: {path}")
            module_name = ".".join(parts)
            import_root = package_dir

        existing_roots = {
            str(Path(entry or Path.cwd()).resolve()) for entry in sys.path
        }
        if str(import_root) not in existing_roots:
            sys.path.insert(0, str(import_root))
        return module_name

    async def _apply_extensions(self, *module_or_path: str | types.ModuleType, handler: Callable[[str], bool]) -> list[str]:
        """Resolve targets, apply one operation, and refresh active managers."""
        handled: list[str] = []
        original_scope = list(self._extension_scope)
        for entry in module_or_path:
            module_name: str | None = None
            try:
                module_name = self._resolve_module_name(entry)
                if module_name is None:
                    continue
                if handler(module_name):
                    handled.append(module_name)
            except Exception as exc:
                self._extension_scope = original_scope
                target = module_name or f"<{type(entry).__name__}>"
                raise RuntimeError(
                    f"Failed to process extension {target}: {exc}"
                ) from exc
        if handled and self._started:
            try:
                self.manager.set_scope(self._extension_scope)
                await self.manager.refresh()
            except Exception as exc:
                self._extension_scope = original_scope
                raise RuntimeError("Failed to refresh extension managers") from exc
        return handled

    def _do_add(self, module_name: str) -> bool:
        if module_name not in sys.modules:
            importlib.import_module(module_name)
        prefix = module_name + "."
        active = set(self._extension_scope)
        new_names: list[str] = []
        for name in [module_name, *sorted(sys.modules)]:
            if (name == module_name or name.startswith(prefix)) and name not in active:
                active.add(name)
                new_names.append(name)
        self._extension_scope.extend(new_names)
        return True

    def _do_remove(self, module_name: str) -> bool:
        prefix = module_name + "."
        before = len(self._extension_scope)
        self._extension_scope = [
            m
            for m in self._extension_scope
            if m != module_name and not m.startswith(prefix)
        ]
        return len(self._extension_scope) < before

    def _do_reload(self, module_name: str) -> bool:
        prefix = module_name + "."
        original_scope = list(self._extension_scope)
        module_names = tuple(
            name
            for name in sys.modules
            if name == module_name or name.startswith(prefix)
        )
        saved_modules = {name: sys.modules[name] for name in module_names}
        try:
            for name in module_names:
                sys.modules.pop(name, None)
            importlib.import_module(module_name)
            alive = sorted(
                name
                for name in sys.modules
                if name == module_name or name.startswith(prefix)
            )
            self._extension_scope = [
                *[
                    name
                    for name in original_scope
                    if name != module_name and not name.startswith(prefix)
                ],
                *alive,
            ]
        except Exception:
            for name in tuple(sys.modules):
                if name == module_name or name.startswith(prefix):
                    sys.modules.pop(name, None)
            sys.modules.update(saved_modules)
            self._extension_scope = original_scope
            raise
        return True

    async def add_extensions(self, *module_or_path: str | types.ModuleType) -> list[str]:
        """Activate modules or importable Python paths for this agent."""
        return await self._apply_extensions(*module_or_path, handler=self._do_add)

    async def remove_extensions(self, *module_or_path: str | types.ModuleType) -> list[str]:
        """Deactivate modules previously active for this agent."""
        return await self._apply_extensions(*module_or_path, handler=self._do_remove)

    async def reload_extensions(self, *module_or_path: str | types.ModuleType) -> list[str]:
        """Reload a module and all currently loaded submodules under its name."""
        return await self._apply_extensions(*module_or_path, handler=self._do_reload)

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
                    before_llm_ctx = BeforeLlmCallCtx(
                        run=run, dialog=dialog, tools=tools_list
                    )
                    await self.hook_manager.fire(
                        HookEventType.BEFORE_LLM_CALL, before_llm_ctx
                    )

                    stream = (
                        run.connector.supports_streaming if run.connector else False
                    )
                    blocks: list[LLMResponseBlock] = []
                    tool_calls: list[LLMResponseToolCallBlock] = []
                    llm_response: LLMResponse | None = None

                    async for event in self.llm_adapter.ask_llm(
                        before_llm_ctx, stream=stream
                    ):
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

                    # A tool call starts execution only after the complete
                    # assistant turn is delivered. Keep tool calls at the end
                    # of that turn so text/reasoning cannot appear between a
                    # call and its result in the conversation timeline.
                    ordered_blocks = [
                        block
                        for block in blocks
                        if not isinstance(block, LLMResponseToolCallBlock)
                    ] + [
                        block
                        for block in blocks
                        if isinstance(block, LLMResponseToolCallBlock)
                    ]
                    llm_response.content = ordered_blocks
                    for event in ordered_blocks:
                        dialog_item = event.to_dialog_item(
                            role=DialogRole.ASSISTANT,
                            user=run.user,
                            origin=run.origin,
                            previous_item_id=last_item_id,
                        )
                        last_item_id = await self._send_and_store_item(
                            run, dialog_item, last_item_id
                        )
                        if isinstance(event, LLMResponseToolCallBlock):
                            tool_calls.append(event)

                    after_llm_ctx = AfterLlmCallCtx(run=run, response=llm_response)
                    await self.hook_manager.fire(
                        HookEventType.AFTER_LLM_CALL, after_llm_ctx
                    )
                    self._validate_response(after_llm_ctx.response, run)

                    for block in tool_calls:
                        tool_call = ToolCall(
                            tool_call_id=block.tool_call_id,
                            tool_name=block.tool_name,
                            tool_args=block.tool_args,
                        )
                        last_item_id, _ = await self._run_tool_lifecycle(
                            run, tool_call, last_item_id
                        )

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
                HookEventType.AFTER_RUN, AfterRunCtx(run=run, error=error)
            )

    async def _ensure_started(self) -> None:
        """Lazy init: load .env, add defaults, start lifecycle, fire on_agent_start."""
        load_dotenv()
        async with self._start_lock:
            if not self._started:
                prefix = _framework_prefix()
                if self._auto_load_main:
                    await self.add_extensions("__main__")
                await self.add_extensions(prefix + ".components")
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

    async def _send_and_store_item(
        self, run: RunCtx, dialog_item: DialogItem, last_item_id: int | None
    ) -> int | None:
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
