from typing import Any, Iterable, overload, Callable
import inspect

import bm25s
from matrix_fn_schema import build_json_schema

from .llm_adapter import ToolCall, ToolCallResult
from ..core.registry import FunctionRegistryEntry, FunctionRegistry, AsyncOrSyncFunction


class UnknownToolError(Exception):
    ...


DEFAULT_TOOL_CATEGORY = 'other'
DEFAULT_TOOL_SEARCH_AMOUNT = 10

type Decorator[F: AsyncOrSyncFunction] = Callable[[F], F]


def build_tool_doc(fn: AsyncOrSyncFunction, category: str = DEFAULT_TOOL_CATEGORY) -> str:
    _cat = f"[ category: {category} ]\n" if category != DEFAULT_TOOL_CATEGORY else ""
    _async = "async " if inspect.iscoroutinefunction(fn) else ""
    return (
        f'{_cat}{_async}def {fn.__name__}{inspect.signature(fn)}:\n'
        f'"""\n{inspect.getdoc(fn) or ""}\n"""'
    ).strip()


class ToolRegistry(FunctionRegistry):
    """
    Registry + специфичные для инструментов операции: JSON-схемы для LLM и семантический поиск по сигнатурам / docstring'ам.
    Метод where() наследуется без изменений
    """

    def schemas(self, entries: Iterable[FunctionRegistryEntry] | None = None) -> list[dict[str, Any]]:
        entries = entries if entries is not None else self
        return [build_json_schema(e.fn) for e in entries]

    async def call(self, tool_call: ToolCall):
        for elem in self:
            if elem.name == tool_call.tool_name:
                if inspect.iscoroutinefunction(elem.fn):
                    result = await elem.fn(**tool_call.tool_args)
                else:
                    result = elem.fn(**tool_call.tool_args)
                return ToolCallResult(tool_call_id=tool_call.tool_call_id, content=str(result))
        raise UnknownToolError(f'Tool "{tool_call.tool_name}" not found')

    def search(
            self, query: str, *, entries: Iterable[FunctionRegistryEntry] | None = None, limit: int = DEFAULT_TOOL_SEARCH_AMOUNT
    ) -> list[FunctionRegistryEntry]:
        entries = list(entries if entries is not None else self)
        if not entries:
            return []

        docs = [e.meta['doc'] for e in entries]
        names = [e.name for e in entries]

        retriever = bm25s.BM25()
        retriever.index(bm25s.tokenize(docs))
        retriever.corpus = names

        results, scores = retriever.retrieve(
            bm25s.tokenize(query),
            k=min(limit, len(entries)),
        )
        by_name = {e.name: e for e in entries}
        return [
            by_name[name]
            for name, score in zip(results[0], scores[0])
            if score > 0
        ]


# Изолированный реестр — только для инструментов, не пересекается с реестром хуков
TOOL_REGISTRY = ToolRegistry()


@overload
def tool(arg: AsyncOrSyncFunction) -> AsyncOrSyncFunction: ...


@overload
def tool(arg: str = ..., **meta: Any) -> Decorator: ...


def tool(
        arg: AsyncOrSyncFunction | str = DEFAULT_TOOL_CATEGORY,
        **meta: Any,
) -> AsyncOrSyncFunction | Decorator:
    """
    Dual-mode декоратор для регистрации python-функции как инструмента для вызова агентом.

    @tool
    @tool("payments")
    @tool(codeact=False)
    @tool("system", role="admin")
    """
    category = DEFAULT_TOOL_CATEGORY if callable(arg) else arg

    def decorator(func: AsyncOrSyncFunction) -> AsyncOrSyncFunction:
        TOOL_REGISTRY.register(
            func,
            category=category,
            doc=build_tool_doc(func, category),
            **meta,
        )
        return func

    return decorator(arg) if callable(arg) else decorator
