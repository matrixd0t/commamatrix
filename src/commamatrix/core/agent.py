# core/agent.py

from __future__ import annotations

import asyncio
import inspect
from collections import defaultdict
from collections.abc import Iterator

from ..api import *
from ..builtin.python.tool_source import PythonToolSource
from ..builtin.python.hook_source import PythonHookSource
from ..builtin.python.connector_source import PythonConnectorSource
from ..builtin.sqlite import SqliteStorage
from ..builtin.fs import SimpleFileStorage
from .runner import AgentRunner
from .services import ServiceRegistry
from .tool_runtime import ToolRuntime
from .hook_runtime import HookRuntime
from .connector_runtime import ConnectorRuntime


class Agent:
    """
    Orchestrates the agent lifecycle: parse → LLM → tools → send.
    """

    def __init__(
        self, *,
        llm_adapter: LLMAdapter,
        storage: Storage | None = None,
        file_storage: FileStorage | None = None,
        connectors: list[Connector] | None = None,
        connector_runtime: ConnectorRuntime | None = None,
        tool_runtime: ToolRuntime | None = None,
        hook_runtime: HookRuntime | None = None,
    ):
        self.llm_adapter = llm_adapter
        self.storage = storage or SqliteStorage()
        self.file_storage = file_storage or SimpleFileStorage()

        self.connector_runtime = connector_runtime or ConnectorRuntime()
        self.tool_runtime = tool_runtime or ToolRuntime()
        self.hook_runtime = hook_runtime or HookRuntime()
        self.services = ServiceRegistry()

        self._provided_connectors = connectors or []
        self._connectors: list[Connector] = []
        self._listener_tasks: list[asyncio.Task] = []
        self.runner = AgentRunner()
        self.connector_runtime.mount(PythonConnectorSource())
        self.tool_runtime.mount(PythonToolSource())
        self.hook_runtime.mount(PythonHookSource())
        self._started = False
        self._start_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> list[asyncio.Task]:
        """Discover extensions, resolve connectors, and start listener tasks."""
        await self._ensure_started()

        active_tasks = [task for task in self._listener_tasks if not task.done()]
        if active_tasks:
            self._listener_tasks = active_tasks
            return active_tasks

        self._listener_tasks = [
            asyncio.create_task(connector.listen(self.handle))
            for connector in self._connectors
            if callable(getattr(connector, 'listen', None))
        ]
        return self._listener_tasks

    async def stop(self) -> None:
        """Stop listeners, cancel active runs, and close agent-owned services."""
        listener_tasks = self._listener_tasks
        self._listener_tasks = []
        for task in listener_tasks:
            if not task.done():
                task.cancel()
        if listener_tasks:
            await asyncio.gather(*listener_tasks, return_exceptions=True)

        await self.runner.stop()

        for service in reversed(list(self.services.values())):
            stop = getattr(service, 'stop', None)
            if not callable(stop):
                continue
            result = stop()
            if inspect.isawaitable(result):
                await result

        self._started = False

    async def __aenter__(self) -> Agent:
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.stop()

    async def handle(self, raw: dict) -> None:
        """Initialize extensions, parse an incoming event, and spawn runs per origin."""
        await self._ensure_started()
        parsed = await self.connector_runtime.parse_any(self._connectors, raw, self)
        if parsed is None:
            return

        await self.hook_runtime.fire(HookEventType.ON_PARSED.value, parsed)

        await self._resolve_previous_item(parsed)

        for run, history in self._split_runs(parsed):
            await self.runner.submit(
                self.runner.make_key(run.origin, run.user),
                self.run(run, history=history),
            )

    async def run(self, run: RunCtx, history: list[DialogItem] | None = None) -> AfterLlmCallCtx | None:
        """Initialize extensions, then run: LLM call → tools → send until no calls remain."""
        await self._ensure_started()
        error: Exception | None = None

        try:
            if (await self._before_run(run)).abort:
                return None

            last_item_id = await self._store_history(history)

            while True:
                run.iteration += 1
                self.tool_runtime.scan()

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
            await self.hook_runtime.fire(
                HookEventType.AFTER_RUN.value, AfterRunCtx(run=run, error=error),
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _ensure_started(self) -> None:
        """Discover extensions and run one-time initialization hooks."""
        if self._started:
            return

        async with self._start_lock:
            if self._started:
                return

            config_error = ConfigField.validate()
            if config_error is not None:
                raise RuntimeError(f'Missing required configuration:\n{config_error}')

            self.connector_runtime.scan()
            self._connectors = self.connector_runtime.resolve(self._provided_connectors)
            self.tool_runtime.scan()
            self.hook_runtime.scan()
            await self.hook_runtime.fire(
                HookEventType.ON_AGENT_START.value,
                OnAgentStartCtx(agent=self),
            )
            self._started = True

    async def _before_run(self, run: RunCtx) -> BeforeRunCtx:
        """Fire before_run hook; caller checks ``.abort`` on the returned context."""
        ctx = BeforeRunCtx(run=run)
        await self.hook_runtime.fire(HookEventType.BEFORE_RUN.value, ctx)
        return ctx

    async def _store_history(self, history: list[DialogItem] | None) -> int | None:
        """Persist unsaved history items and return the history tip."""
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
        """Link the first dialog item to its replied-to message if ``previous_external_id`` is set."""
        if parsed.previous_external_id and parsed.dialog_items:
            replied_item_id = await self.storage.find_item_id_by_external_id(
                parsed.previous_external_id, parsed.dialog_items[0].origin,
            )
            if replied_item_id is not None:
                parsed.dialog_items[0].previous_item_id = replied_item_id

    async def _load_dialog(self, last_item_id: int | None) -> list[DialogItem]:
        """Load the full dialog branch from storage starting at the given tip, or [] if None."""
        if last_item_id is None:
            return []
        return await self.storage.get_branch(last_item_id)

    async def _call_llm(self, run: RunCtx, last_item_id: int | None) -> AfterLlmCallCtx:
        """Load dialog → before_llm_call hook → LLM request → after_llm_call hook → validate."""
        dialog = await self._load_dialog(last_item_id)

        tools_list = list(self.tool_runtime.descriptors)
        before_llm_ctx = BeforeLlmCallCtx(run=run, dialog=dialog, tools=tools_list)
        await self.hook_runtime.fire(HookEventType.BEFORE_LLM_CALL.value, before_llm_ctx)

        llm_response = await self.llm_adapter.ask_llm(before_llm_ctx)

        after_llm_ctx = AfterLlmCallCtx(run=run, response=llm_response)
        await self.hook_runtime.fire(HookEventType.AFTER_LLM_CALL.value, after_llm_ctx)

        self._validate_response(after_llm_ctx.response, run)

        return after_llm_ctx

    @staticmethod
    def _validate_response(response: LLMResponse, run: RunCtx) -> None:
        """Raise if the LLM response was truncated or errored."""
        if response.stop_reason == StopReason.MAX_TOKENS:
            raise LLMTruncatedError(f'Response truncated at iteration {run.iteration}')
        if response.stop_reason == StopReason.ERROR:
            raise LLMResponseError(f'LLM error at iteration {run.iteration}')

    async def _execute_tool(self, run: RunCtx, block: LLMResponseToolCallBlock) -> tuple[ToolCall, ToolCallResult]:
        """Fire tool hooks and execute one call without persisting it."""
        tool_call = ToolCall(
            tool_call_id=block.tool_call_id,
            tool_name=block.tool_name,
            tool_args=block.tool_args,
        )

        before_ctx = BeforeToolCallCtx(run=run, tool_call=tool_call)
        await self.hook_runtime.fire(HookEventType.BEFORE_TOOL_CALL.value, before_ctx)
        tool_call = before_ctx.tool_call

        if before_ctx.abort_tool_call:
            result = ToolCallResult.aborted(tool_call.tool_call_id, before_ctx.abort_reason)
        else:
            result = await self.tool_runtime.call(tool_call, ctx=before_ctx)

        after_ctx = AfterToolCallCtx(run=run, tool_call=tool_call, result=result)
        await self.hook_runtime.fire(HookEventType.AFTER_TOOL_CALL.value, after_ctx)
        return after_ctx.tool_call, after_ctx.result

    async def _execute_tools(self, run: RunCtx, response: LLMResponse, last_item_id: int | None) -> tuple[int | None, bool]:
        """Persist the assistant response, execute calls concurrently, then persist results."""
        tool_blocks = [block for block in response.content if isinstance(block, LLMResponseToolCallBlock)]
        if not tool_blocks:
            return last_item_id, False

        for block in response.content:
            if isinstance(block, LLMResponseToolCallBlock):
                content = ToolCall(
                    tool_call_id=block.tool_call_id,
                    tool_name=block.tool_name,
                    tool_args=block.tool_args,
                ).dump_json()
                item_type = DialogItemType.TOOL_CALL
            else:
                content = block.content_str()
                item_type = block.item_type()
            last_item_id = await self.storage.save_event(DialogItem(
                content=content, item_type=item_type,
                role=DialogRole.ASSISTANT, user=run.user, origin=run.origin,
                previous_item_id=last_item_id,
            ))

        executed = await asyncio.gather(*(self._execute_tool(run, block) for block in tool_blocks))
        for tool_call, result in executed:
            last_item_id = await self.storage.save_event(DialogItem(
                content=result.dump_json(), item_type=DialogItemType.TOOL_CALL_RESULT,
                role=DialogRole.TOOL, user=run.user, origin=run.origin,
                previous_item_id=last_item_id,
            ))

        return last_item_id, True

    async def _send_block(self, run: RunCtx, block: LLMResponseBlock, last_item_id: int | None) -> int | None:
        """Fire before_send hook → send via connector → persist and return new item id."""
        item = DialogItem(
            content=block.content_str(), item_type=block.item_type(),
            role=DialogRole.ASSISTANT, user=run.user, origin=run.origin,
            previous_item_id=last_item_id,
        )
        before_send_ctx = BeforeSendCtx(run=run, dialog_item=item)
        await self.hook_runtime.fire(HookEventType.BEFORE_SEND.value, before_send_ctx)

        if run.connector is not None:
            external_id = await run.connector.send(run.origin, before_send_ctx.dialog_item)
        else:
            external_id = None

        return await self.storage.save_event(
            before_send_ctx.dialog_item.model_copy(update={'external_id': external_id})
        )

    async def _send_blocks(self, run: RunCtx, blocks: list[LLMResponseBlock], last_item_id: int | None) -> int | None:
        """Send all non-tool blocks to the user and persist them."""
        for block in blocks:
            last_item_id = await self._send_block(run, block, last_item_id)
        return last_item_id

    async def _handle_error(self, run: RunCtx, error: Exception) -> None:
        """Fire on_error hook and re-raise unless a handler suppresses the exception."""
        ctx = OnErrorCtx(run=run, error=error)
        await self.hook_runtime.fire(HookEventType.ON_ERROR.value, ctx)
        if not ctx.suppress:
            raise error

    @staticmethod
    def _split_runs(parsed: OnParsedCtx) -> Iterator[tuple[RunCtx, list[DialogItem]]]:
        """Group parsed dialog items by origin and produce a RunCtx for each group."""
        by_origin: dict[DialogOrigin, list[DialogItem]] = defaultdict(list)
        for item in parsed.dialog_items:
            by_origin[item.origin].append(item)

        for origin, items in by_origin.items():
            user = items[-1].user
            yield RunCtx(
                agent=parsed.agent,
                connector=parsed.connector,
                origin=origin,
                user=user,
            ), items
