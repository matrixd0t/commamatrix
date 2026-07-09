import asyncio
from collections import defaultdict

from ..api import *
from ..builtin.sqlite import *
from ..builtin.fs import *
from .runner import AgentRunner


storage_cls = ConfigField[type[Storage]](init=True, default=SqliteStorage, description='Storage implementation class')
file_storage_cls = ConfigField[type[FileStorage]](init=True, default=SimpleFileStorage, description='File storage implementation class')
llm_adapter_cls = ConfigField[type[LLMAdapter]](init=True, description='LLM adapter class')


# noinspection PyPropertyDefinition
class Agent:
    connector_registry: ConnectorRegistry = CONNECTOR_REGISTRY
    tool_registry: ToolRegistry = TOOL_REGISTRY
    hooks_registry: HooksRegistry = HOOKS_REGISTRY

    def __new__(cls, *args, **kwargs):
        raise TypeError('Agent is not instantiable — use classmethods directly')

    @staticmethod
    def config_info() -> str:
        """Return a formatted table of all init-required config fields with their status."""
        return ConfigField.config_info()

    @staticmethod
    def validate() -> str:
        """Check config: return 'OK' if all init fields are set, or the config_info report otherwise."""
        return result if (result := ConfigField._validate()) is not None else 'OK'

    @classmethod
    def storage(cls) -> type[Storage]:
        """Return the currently configured Storage implementation class."""
        return storage_cls.get()

    @classmethod
    def file_storage(cls) -> type[FileStorage]:
        """Return the currently configured FileStorage implementation class."""
        return file_storage_cls.get()

    @classmethod
    def llm_adapter(cls) -> type[LLMAdapter]:
        """Return the currently configured LLMAdapter implementation class."""
        return llm_adapter_cls.get()

    @classmethod
    async def start_listeners(cls) -> list[asyncio.Task]:
        """Start all connector listeners as asyncio tasks; returns the list of tasks."""
        tasks = []
        for listener_cls in cls.connector_registry.listening():
            tasks.append(asyncio.create_task(listener_cls.listen(cls.handle)))
        return tasks

    @classmethod
    async def handle(cls, raw: dict) -> None:
        """Parse an incoming raw event through all connectors and spawn a run for each origin."""
        parsed = await cls.connector_registry.parse_any(raw, cls)
        if parsed is None:
            return

        await cls.hooks_registry.fire(HookEventType.ON_PARSED, parsed)

        connector = parsed.connector
        dialog_items = parsed.dialog_items

        if parsed.previous_external_id and dialog_items:
            replied_item_id = await cls.storage().find_item_id_by_external_id(
                parsed.previous_external_id, dialog_items[0].origin
            )
            if replied_item_id is not None:
                dialog_items[0].previous_item_id = replied_item_id

        dialog_items_by_origin: dict[DialogOrigin, list[DialogItem]] = defaultdict(list[DialogItem])
        for dialog_item in dialog_items:
            dialog_items_by_origin[dialog_item.origin].append(dialog_item)

        for origin, origin_items in dialog_items_by_origin.items():
            run = RunCtx(connector=connector, user=origin_items[-1].user, origin=origin, agent=cls)
            await AgentRunner.submit(AgentRunner.make_key(run.origin, run.user), cls.run(run, history=origin_items))

    @classmethod
    async def run(cls, run: RunCtx, history: list[DialogItem] | None = None) -> AfterLlmCallCtx | None:
        """Execute the main agent loop: LLM call → tool execution → send response, until no tool calls remain."""
        error: Exception | None = None
        result_ctx: AfterLlmCallCtx | None = None
        last_item_id: int | None = None

        try:
            before_run_ctx = BeforeRunCtx(run=run)
            await cls.hooks_registry.fire(HookEventType.BEFORE_RUN, before_run_ctx)
            if before_run_ctx.abort:
                return None

            if history is not None:
                for item in history:
                    if not item.item_id:
                        last_item_id = await cls.storage().save_event(item)

            while True:
                run.iteration += 1
                current_tool_registry = cls.tool_registry.copy()

                dialog: list[DialogItem] = await cls.storage().get_branch(last_item_id) if last_item_id else []

                before_llm_ctx = BeforeLlmCallCtx(run=run, dialog=dialog, tools=current_tool_registry)
                await cls.hooks_registry.fire(HookEventType.BEFORE_LLM_CALL, before_llm_ctx)

                llm_response = await cls.llm_adapter().ask_llm(before_llm_ctx)

                after_llm_ctx = AfterLlmCallCtx(run=run, response=llm_response)
                await cls.hooks_registry.fire(HookEventType.AFTER_LLM_CALL, after_llm_ctx)
                llm_response = after_llm_ctx.response

                if llm_response.stop_reason == StopReason.MAX_TOKENS:
                    raise LLMTruncatedError(f'Response truncated at iteration {run.iteration}')

                if llm_response.stop_reason == StopReason.ERROR:
                    raise LLMResponseError(f'LLM error at iteration {run.iteration}')

                content_blocks: list[LLMResponseBlock] = []
                tool_call_executed = False

                for block in llm_response.content:
                    if isinstance(block, LLMResponseToolCallBlock):
                        tool_call_executed = True
                        tool_call = ToolCall(
                            tool_call_id=block.tool_call_id,
                            tool_name=block.tool_name,
                            tool_args=block.tool_args,
                        )

                        before_tool_call_ctx = BeforeToolCallCtx(run=run, tool_call=tool_call)
                        await cls.hooks_registry.fire(HookEventType.BEFORE_TOOL_CALL, before_tool_call_ctx)
                        tool_call = before_tool_call_ctx.tool_call

                        if before_tool_call_ctx.abort_tool_call:
                            tool_call_result = ToolCallResult.aborted(tool_call.tool_call_id, before_tool_call_ctx.abort_reason)
                        else:
                            tool_call_result = await cls.tool_registry.call(tool_call)

                        after_tool_call_ctx = AfterToolCallCtx(run=run, tool_call=tool_call, result=tool_call_result)
                        await cls.hooks_registry.fire(HookEventType.AFTER_TOOL_CALL, after_tool_call_ctx)

                        last_item_id = await cls.storage().save_event(DialogItem(
                            content=after_tool_call_ctx.tool_call.dump_json(), item_type=DialogItemType.TOOL_CALL,
                            role=DialogRole.ASSISTANT, user=run.user, origin=run.origin,
                            previous_item_id=last_item_id,
                        ))
                        last_item_id = await cls.storage().save_event(DialogItem(
                            content=tool_call_result.dump_json(), item_type=DialogItemType.TOOL_CALL_RESULT,
                            role=DialogRole.TOOL, user=run.user, origin=run.origin,
                            previous_item_id=last_item_id,
                        ))
                    else:
                        content_blocks.append(block)

                if tool_call_executed:
                    for block in content_blocks:
                        last_item_id = await cls.storage().save_event(DialogItem(
                            content=block.content_str(), item_type=block.item_type(),
                            role=DialogRole.ASSISTANT, user=run.user, origin=run.origin,
                            previous_item_id=last_item_id,
                        ))
                    continue

                result_ctx = after_llm_ctx
                for block in content_blocks:
                    item = DialogItem(
                        content=block.content_str(), item_type=block.item_type(),
                        role=DialogRole.ASSISTANT, user=run.user, origin=run.origin,
                        previous_item_id=last_item_id,
                    )
                    before_send_ctx = BeforeSendCtx(run=run, dialog_item=item)
                    await cls.hooks_registry.fire(HookEventType.BEFORE_SEND, before_send_ctx)
                    if run.connector is not None:
                        external_id = await run.connector.send(run.origin, before_send_ctx.dialog_item)
                    else:
                        external_id = None
                    last_item_id = await cls.storage().save_event(
                        before_send_ctx.dialog_item.model_copy(update={'external_id': external_id})
                    )
                break

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            error = exc
            error_ctx = OnErrorCtx(run=run, error=exc)
            await cls.hooks_registry.fire(HookEventType.ON_ERROR, error_ctx)
            if not error_ctx.suppress:
                raise

        finally:
            await cls.hooks_registry.fire(HookEventType.AFTER_RUN, AfterRunCtx(run=run, error=error))

        return result_ctx
