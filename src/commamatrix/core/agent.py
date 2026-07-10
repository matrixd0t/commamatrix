# core/agent.py

import asyncio
from collections import defaultdict
from collections.abc import Iterator

from ..api import *
from ..builtin.sqlite import SqliteStorage
from ..builtin.fs import SimpleFileStorage
from ..builtin.python.tool_source import PythonToolSource
from ..builtin.python.hook_source import PythonHookSource
from .runner import AgentRunner
from .tool_runtime import ToolRuntime
from .hook_runtime import HookRuntime
from .virtual_imports import install_import_hook


class Agent:
    """
    Orchestrates the agent lifecycle: parse → LLM → tools → send.
    """

    def __init__(
        self, *,
        llm_adapter: type[LLMAdapter],
        storage: type[Storage] = SqliteStorage,
        file_storage: type[FileStorage] = SimpleFileStorage,
        connector_registry: ConnectorRegistry = CONNECTOR_REGISTRY,
        tool_runtime: ToolRuntime | None = None,
        hook_runtime: HookRuntime | None = None,
    ):
        self.connector_registry = connector_registry
        self.storage = storage
        self.file_storage = file_storage
        self.llm_adapter = llm_adapter

        self.tool_runtime = tool_runtime or ToolRuntime()
        self.hook_runtime = hook_runtime or HookRuntime()
        self.tool_runtime.mount(PythonToolSource())
        self.hook_runtime.mount(PythonHookSource())

        install_import_hook(self.tool_runtime)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start_listeners(self) -> list[asyncio.Task]:
        """Start all connector listener tasks (e.g. TCP servers)."""
        tasks = []
        for listener_cls in self.connector_registry.listening():
            tasks.append(asyncio.create_task(listener_cls.listen(self.handle)))
        return tasks

    async def handle(self, raw: dict) -> None:
        """Parse an incoming event and spawn a run per origin."""
        parsed = await self.connector_registry.parse_any(raw, self)
        if parsed is None:
            return

        await self.hook_runtime.fire(HookEventType.ON_PARSED.value, parsed)

        await self._resolve_previous_item(parsed)

        for run, history in self._split_runs(parsed):
            await AgentRunner.submit(
                AgentRunner.make_key(run.origin, run.user),
                self.run(run, history=history),
            )

    async def run(self, run: RunCtx, history: list[DialogItem] | None = None) -> AfterLlmCallCtx | None:
        """Main agentic loop: LLM call → tools → send, repeat until no tool calls remain."""
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

    async def _before_run(self, run: RunCtx) -> BeforeRunCtx:
        """Fire *before_run* hook; caller checks ``.abort`` on the returned context."""
        ctx = BeforeRunCtx(run=run)
        await self.hook_runtime.fire(HookEventType.BEFORE_RUN.value, ctx)
        return ctx

    async def _store_history(self, history: list[DialogItem] | None) -> int | None:
        """Persist unsaved history items and return the last item id."""
        last_item_id: int | None = None
        if history is not None:
            for item in history:
                if not item.item_id:
                    last_item_id = await self.storage.save_event(item)
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

        before_llm_ctx = BeforeLlmCallCtx(run=run, dialog=dialog, tools=self.tool_runtime)
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

    async def _execute_tool(self, run: RunCtx, block: LLMResponseToolCallBlock, last_item_id: int | None) -> tuple[int | None, ToolCallResult]:
        """Fire before_tool_call hook → execute → fire after_tool_call → save both items."""
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
            result = await self.tool_runtime.call(tool_call)

        after_ctx = AfterToolCallCtx(run=run, tool_call=tool_call, result=result)
        await self.hook_runtime.fire(HookEventType.AFTER_TOOL_CALL.value, after_ctx)

        last_item_id = await self.storage.save_event(DialogItem(
            content=after_ctx.tool_call.dump_json(), item_type=DialogItemType.TOOL_CALL,
            role=DialogRole.ASSISTANT, user=run.user, origin=run.origin,
            previous_item_id=last_item_id,
        ))
        last_item_id = await self.storage.save_event(DialogItem(
            content=result.dump_json(), item_type=DialogItemType.TOOL_CALL_RESULT,
            role=DialogRole.TOOL, user=run.user, origin=run.origin,
            previous_item_id=last_item_id,
        ))

        return last_item_id, result

    async def _execute_tools(self, run: RunCtx, response: LLMResponse, last_item_id: int | None) -> tuple[int | None, bool]:
        """Iterate LLM response blocks: execute tool calls, accumulate content."""
        content_blocks: list[LLMResponseBlock] = []
        tool_call_executed = False

        for block in response.content:
            if isinstance(block, LLMResponseToolCallBlock):
                tool_call_executed = True
                last_item_id, _ = await self._execute_tool(run, block, last_item_id)
            else:
                content_blocks.append(block)

        if tool_call_executed:
            for block in content_blocks:
                last_item_id = await self.storage.save_event(DialogItem(
                    content=block.content_str(), item_type=block.item_type(),
                    role=DialogRole.ASSISTANT, user=run.user, origin=run.origin,
                    previous_item_id=last_item_id,
                ))

        return last_item_id, tool_call_executed

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

    async def _handle_error(self, run: RunCtx, exc: Exception) -> None:
        """Fire *on_error* hook; re-raise unless the hook suppresses."""
        error_ctx = OnErrorCtx(run=run, error=exc)
        await self.hook_runtime.fire(HookEventType.ON_ERROR.value, error_ctx)
        if not error_ctx.suppress:
            raise

    def _split_runs(self, parsed: OnParsedCtx) -> Iterator[tuple[RunCtx, list[DialogItem]]]:
        """Yield ``(RunCtx, items)`` tuples, one per distinct origin."""
        by_origin: dict[DialogOrigin, list[DialogItem]] = defaultdict(list)
        for item in parsed.dialog_items:
            by_origin[item.origin].append(item)

        for origin, items in by_origin.items():
            yield RunCtx(
                connector=parsed.connector,
                user=items[-1].user,
                origin=origin,
                agent=self,
            ), items
