from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, ClassVar, Generic, TYPE_CHECKING, TypeVar, get_args, get_origin, Callable, Awaitable
from contextlib import asynccontextmanager

from .dialog import DialogItem, DialogOrigin

if TYPE_CHECKING:
    from .hooks import OnParsedCtx
    from ..core.agent import Agent

type OnEvent = Callable[[dict], Awaitable[None]]


class ConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: list[type[Connector]] = []
        self._ctx_types: dict[type, type[Connector]] = {}

    def register(self, connector_cls: type[Connector]) -> None:
        ctx_type = connector_cls.origin_type
        if ctx_type is None:
            raise TypeError(f'{connector_cls.__name__} не параметризован. Используй Connector[MyContext].')

        if existing := self._ctx_types.get(ctx_type):
            raise RuntimeError(f'Для {ctx_type.__name__} уже зарегистрирован {existing.__name__}.')

        self._ctx_types[ctx_type] = connector_cls
        self._connectors.append(connector_cls)

    async def parse_any(self, data: dict, agent: type[Agent]) -> OnParsedCtx | None:
        for connector_cls in self._connectors:
            if ctx := await connector_cls.parse(data, agent):
                return ctx
        return None

    def listening(self) -> list[type[ListensEvents]]:
        return [c for c in self._connectors if issubclass(c, ListensEvents)]

    def __iter__(self):
        return iter(self._connectors)

    def __len__(self) -> int:
        return len(self._connectors)


CONNECTOR_REGISTRY = ConnectorRegistry()

OrgT = TypeVar('OrgT', bound=DialogOrigin)


class Connector(ABC, Generic[OrgT]):
    """
    Abstract connector. Concrete subclasses auto-register in __init_subclass__
    and read config dynamically from ConfigField. All public methods are classmethods.
    """
    origin_type: ClassVar[type | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        for base in getattr(cls, "__orig_bases__", ()):
            origin = get_origin(base)
            if origin is Connector or (isinstance(origin, type) and issubclass(origin, Connector)):
                args = get_args(base)
                if args and not isinstance(args[0], TypeVar):
                    cls.origin_type = args[0]
                    break

        if not getattr(cls, '__abstractmethods__', None):
            CONNECTOR_REGISTRY.register(cls)

    @classmethod
    @abstractmethod
    async def parse(cls, data: dict, agent: type[Agent]) -> OnParsedCtx | None: ...

    @classmethod
    @abstractmethod
    async def send(cls, origin: OrgT, item: DialogItem) -> str: ...

    @classmethod
    @asynccontextmanager
    async def typing(cls, origin: OrgT) -> AsyncIterator[None]:
        yield


class ListensEvents(ABC):
    @classmethod
    @abstractmethod
    async def listen(cls, on_event: OnEvent) -> None:
        ...
