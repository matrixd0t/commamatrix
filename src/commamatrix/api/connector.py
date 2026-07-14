# api/connector.py

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, AsyncIterator
from dataclasses import dataclass, field
from typing import (
    Any,
    ClassVar,
    Generic,
    TYPE_CHECKING,
    TypeVar,
    get_args,
    get_origin,
)
import asyncio
from contextlib import asynccontextmanager

from .dialog import DialogItem, DialogOrigin
from .service import AbstractService, ServiceDescriptor
from ..extensions import ExtensionDescriptor, ExtensionSource

if TYPE_CHECKING:
    from .config import Config
    from .hooks import OnParsedCtx
    from ..core.agent import Agent

CONNECTOR_ATTRIBUTE = "__commamatrix_connector__"

type OnEvent = Callable[[dict], Awaitable[None]]


OrgT = TypeVar("OrgT", bound=DialogOrigin)


class Connector(AbstractService, Generic[OrgT]):
    """Abstract connector. Concrete subclasses are discovered by ConnectorManager.

    Extends AbstractService: start() / stop() manage the listener lifecycle
    instead of explicit start_listening / stop_listening.
    """

    origin_type: ClassVar[type | None] = None
    _on_event: OnEvent | None = None

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self._listener_task: asyncio.Task | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        for base in getattr(cls, "__orig_bases__", ()):
            origin = get_origin(base)
            if origin is Connector or (
                isinstance(origin, type) and issubclass(origin, Connector)
            ):
                args = get_args(base)
                if args and not isinstance(args[0], TypeVar):
                    cls.origin_type = args[0]
                    break

        if not getattr(cls, "__abstractmethods__", None):
            setattr(cls, CONNECTOR_ATTRIBUTE, True)

    @property
    def listener_task(self) -> asyncio.Task | None:
        return getattr(self, "_listener_task", None)

    async def start(self) -> None:
        if self._on_event is not None:
            current = self._listener_task
            if current is not None and not current.done():
                return
            self._listener_task = asyncio.create_task(self.listen(self._on_event))

    async def stop(self) -> None:
        task = self._listener_task
        self._listener_task = None
        if task is None or task.done():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    @abstractmethod
    async def parse(self, data: dict, agent: Agent) -> OnParsedCtx | None: ...

    @abstractmethod
    async def send(self, origin: OrgT, item: DialogItem) -> str: ...

    @asynccontextmanager
    async def typing(self, origin: OrgT) -> AsyncIterator[None]:
        yield

    async def listen(self, on_event: OnEvent) -> None:
        pass


@dataclass(frozen=True, slots=True)
class ConnectorDescriptor(ServiceDescriptor):
    connector_cls: type[Connector]


class ConnectorSource(ExtensionSource[ConnectorDescriptor], ABC):
    pass
