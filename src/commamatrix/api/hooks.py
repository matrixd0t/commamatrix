from __future__ import annotations

from dataclasses import field, dataclass
from enum import StrEnum
from uuid import uuid4
from typing import TYPE_CHECKING, Any
from collections.abc import Callable, Awaitable

from ..core import FunctionRegistry
from .tool import ToolRegistry
from .connector import Connector
from .dialog import DialogItem, DialogOrigin
from .llm_adapter import LLMResponse, ToolCallResult, ToolCall, LLMAdapter

if TYPE_CHECKING:
    from ..core.agent import Agent

type Handler[CtxT] = Callable[[CtxT], Awaitable[None]]


class HooksRegistry(FunctionRegistry):
    """
    Реестр хуков. FunctionRegistry с методом fire
    """

    async def fire(self, event: str, ctx: Any) -> None:
        """
        Запускает все хуки для события, отсортированные по полю priority
        При одинаковом priority — в порядке регистрации (т.е. в порядке импорта плагинов)
        """
        entries = self.where(event=event)
        for entry in sorted(entries, key=lambda e: e.meta.get('priority', 0)):
            await entry.fn(ctx)


HOOKS_REGISTRY = HooksRegistry()


class Hook[CtxT]:
    """
    Типизированная фабрика декораторов для обработчиков событий
    OrgT определяет сигнатуру обработчика — IDE выводит тип ctx автоматически
    """

    def __init__(self, registry: FunctionRegistry, event: str, ctx_type: type[CtxT]) -> None:
        self._registry = registry
        self._event = event
        self._ctx_type = ctx_type
        self.__name__ = event

    def __call__(self, fn: Handler[CtxT] | None = None, /, **meta: object) -> Handler[CtxT] | Callable[[Handler[CtxT]], Handler[CtxT]]:
        def decorator(f: Handler[CtxT]) -> Handler[CtxT]:
            self._registry.register(f, event=self._event, **meta)
            return f
        if fn is not None:
            return decorator(fn)
        return decorator

    def __repr__(self) -> str:
        return f'Hook[{self._ctx_type.__name__}](event={self._event!r})'


class HookEventType(StrEnum):
    ON_PARSED = 'on_parsed'
    BEFORE_RUN = 'before_run'
    BEFORE_LLM_CALL = 'before_llm_call'
    AFTER_LLM_CALL = 'after_llm_call'
    BEFORE_TOOL_CALL = 'before_tool_call'
    AFTER_TOOL_CALL = 'after_tool_call'
    BEFORE_SEND = 'before_send'
    ON_ERROR = 'on_error'
    AFTER_RUN = 'after_run'


@dataclass(slots=True, kw_only=True)
class BaseEventCtx:
    """
    Базовый контекст события
    meta — данные, специфичные для КОНКРЕТНОГО события (не переживают его).
    Для данных, живущих дольше одного события — используйте run.state.
    """
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, kw_only=True)
class RunCtx:
    """
    Common properties of an agentic loop run. This object is passed to every event context.

    Use 'state' field to pass arbitrary information between events in same agentic loop.
    connector is None for headless/sub-agent runs (no platform to send to).
    """
    agent: type[Agent]
    connector: type[Connector] | None = None
    origin: DialogOrigin
    user: str
    """
    platform-specific identifier of user that triggered a chain of events.

    examples: 'tg:11111', 'vk:22334455'
    """
    run_id: str = field(default_factory=lambda: uuid4().hex)
    iteration: int = 0
    state: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, kw_only=True)
class OnParsedCtx(BaseEventCtx):
    agent: type[Agent]
    connector: type[Connector]
    raw: dict
    dialog_items: list[DialogItem]
    previous_external_id: str | None = None


on_parsed = Hook(HOOKS_REGISTRY, event=HookEventType.ON_PARSED, ctx_type=OnParsedCtx)
"""
После парсинга входящих данных коннектором. dialog_items можно мутировать/фильтровать

@on_parsed
async def handler(ctx: OnParsedCtx):
    ...
"""


@dataclass(slots=True, kw_only=True)
class BeforeRunCtx(BaseEventCtx):
    run: RunCtx
    abort: bool = False


before_run = Hook(HOOKS_REGISTRY, event=HookEventType.BEFORE_RUN, ctx_type=BeforeRunCtx)
"""
В самом начале _run, до первого обращения к storage
abort = отменить весь run
tools может быть изменен, это не отразится на общем реестре инструментов

@before_run
async def handler(ctx: BeforeRunCtx):
    ...
"""


@dataclass(slots=True, kw_only=True)
class BeforeLlmCallCtx(BaseEventCtx):
    run: RunCtx
    dialog: list[DialogItem]
    tools: ToolRegistry
    llm_call_params: dict = field(default_factory=dict)
    """
    Дополнительные провайдер-специфичные параметры вызова llm, например, модель, температура, top_k и т.п.
    """


before_llm_call = Hook(HOOKS_REGISTRY, event=HookEventType.BEFORE_LLM_CALL, ctx_type=BeforeLlmCallCtx)
"""
Перед вызовом LLM
dialog — список DialogItem (доменные объекты, рендеринг в messages ещё не выполнен — он адаптер-специфичен и произойдёт внутри ask_llm)
Можно мутировать/фильтровать dialog и tools.

@before_llm_call
async def handler(ctx: BeforeLlmCallCtx):
    ...
"""


@dataclass(slots=True, kw_only=True)
class AfterLlmCallCtx(BaseEventCtx):
    run: RunCtx
    response: LLMResponse


after_llm_call = Hook(HOOKS_REGISTRY, event=HookEventType.AFTER_LLM_CALL, ctx_type=AfterLlmCallCtx)
"""
После ответа LLM.
messages — то, что реально было отправлено конкретным адаптером (уже в его нативном формате, Anthropic/OpenAI/etc).
response можно мутировать или полностью заменить.

@before_llm_call
async def handler(ctx: BeforeLlmCallCtx):
    ...
"""


@dataclass(slots=True, kw_only=True)
class BeforeToolCallCtx(BaseEventCtx):
    run: RunCtx
    tool_call: ToolCall
    abort_tool_call: bool = False
    abort_reason: str = ''


before_tool_call = Hook(HOOKS_REGISTRY, event=HookEventType.BEFORE_TOOL_CALL, ctx_type=BeforeToolCallCtx)
"""
Вызывается перед выполнением инструмента.
tool_call можно изменять (tool_call.arguments['x'] = ...)
или заменить целиком (ctx.tool_call = ToolCall(...)) — например,
чтобы перенаправить вызов на другой тул с другим набором аргументов

abort_tool_call — отменить именно ЭТОТ вызов инструмента (не весь run).

@before_tool_call
async def handler(ctx: BeforeToolCallCtx):
    ...
"""


@dataclass(slots=True, kw_only=True)
class AfterToolCallCtx(BaseEventCtx):
    run: RunCtx
    tool_call: ToolCall
    result: ToolCallResult


after_tool_call = Hook(HOOKS_REGISTRY, event=HookEventType.AFTER_TOOL_CALL, ctx_type=AfterToolCallCtx)
"""
Вызывается после выполнения инструмента
tool_call — тот же объект (с учётом изменений из before_tool_execution),
возвращён не для повторной передачи данных, а для сопоставления с result.
Изменения tool_call.arguments здесь уже не влияет на реальный вызов
(он выполнен), но влияет на то, что запишется в DialogItem

@after_tool_call
async def handler(ctx: AfterToolCallCtx):
    ...
"""


@dataclass(slots=True, kw_only=True)
class BeforeSendCtx(BaseEventCtx):
    run: RunCtx
    dialog_item: DialogItem


before_send = Hook(HOOKS_REGISTRY, event=HookEventType.BEFORE_SEND, ctx_type=BeforeSendCtx)
"""
Перед отправкой одного DialogItem пользователю.
Вызывается для каждого элемента ответа (текст, изображение, файл — отдельно).

@before_send
async def handler(ctx: BeforeSendCtx):
    ...
"""


@dataclass(slots=True, kw_only=True)
class OnErrorCtx(BaseEventCtx):
    run: RunCtx
    error: Exception
    suppress: bool = False


on_error = Hook(HOOKS_REGISTRY, event=HookEventType.ON_ERROR, ctx_type=OnErrorCtx)
"""
Исключение в цикле агента (кроме CancelledError — тот наружу, без хука).
suppress=True — подавить исключение, run завершится "тихо" (after_run всё равно отработает через finally).

@on_error
async def handler(ctx: OnErrorCtx):
    ...
"""


@dataclass(slots=True, kw_only=True)
class AfterRunCtx(BaseEventCtx):
    run: RunCtx
    error: Exception | None = None


after_run = Hook(HOOKS_REGISTRY, event=HookEventType.AFTER_RUN, ctx_type=AfterRunCtx)
"""
Вызывается после завершения run, в finally — независимо от успеха, ошибки или CancelledError.
Место для cleanup: закрытие трейсинг-спана, decrement счётчиков, billing.
error is None при успешном завершении.

@after_run
async def handler(ctx: AfterRunCtx):
    ...
"""