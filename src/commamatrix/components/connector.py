# components/connector.py

from __future__ import annotations

import asyncio
import types
import weakref
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import (
    Any,
    ClassVar,
    Generic,
    TYPE_CHECKING,
    TypeVar,
    Union as TypingUnion,
    cast,
    get_args,
    get_origin,
)

from ..core.base.service import AbstractService, ServiceDescriptor
from ..core.base.source import Source, PythonSource
from ..core.base.manager import ServiceInstanceManager, ServiceInstanceRegistry
from .dialog import DialogItem, DialogOrigin

if TYPE_CHECKING:
    from .hook import OnParsedCtx
    from .config import Config
    from ..core.agent import Agent

CONNECTOR_ATTRIBUTE = "__commamatrix_connector__"

type OnEvent = Callable[[dict], Awaitable[None]]
OrgT = TypeVar("OrgT", bound=DialogOrigin)


class Connector(AbstractService, Generic[OrgT]):
    origin_types: ClassVar[tuple[type[DialogOrigin], ...]] = ()
    _on_event: OnEvent | None = None

    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self._listener_task: asyncio.Task | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        for base in getattr(cls, "__orig_bases__", ()):
            origin = get_origin(base)
            if origin is not Connector and not (
                isinstance(origin, type) and issubclass(origin, Connector)
            ):
                continue
            collected: list[type[DialogOrigin]] = []
            for arg in get_args(base):
                arg_origin = get_origin(arg)
                if arg_origin is types.UnionType or arg_origin is TypingUnion:
                    for a in get_args(arg):
                        if isinstance(a, type) and issubclass(a, DialogOrigin):
                            collected.append(a)
                elif isinstance(arg, type) and issubclass(arg, DialogOrigin):
                    collected.append(arg)
            if collected:
                cls.origin_types = tuple(collected)
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
    async def send(self, origin: DialogOrigin, item: DialogItem) -> str: ...

    @asynccontextmanager
    async def typing(self, origin: DialogOrigin) -> AsyncIterator[None]:
        yield

    async def listen(self, on_event: OnEvent) -> None:
        pass


@dataclass(frozen=True, slots=True)
class ConnectorDescriptor(ServiceDescriptor):
    connector_cls: type[Connector]


class ConnectorSource(Source[ConnectorDescriptor], ABC):
    pass


class PythonConnectorSource(PythonSource[ConnectorDescriptor], ConnectorSource):
    def __init__(self) -> None:
        super().__init__()

    @property
    def marker_attribute(self) -> str:
        return CONNECTOR_ATTRIBUTE

    def build_descriptor(self, object_name: str, obj: object) -> ConnectorDescriptor | None:
        connector_cls = cast(type[Connector], obj)
        return ConnectorDescriptor(
            id=f"connector://{connector_cls.__module__}/{object_name}",
            service_cls=connector_cls,
            connector_cls=connector_cls,
            metadata={},
            _source_ref=weakref.ref(self),
        )


class ConnectorManager(ServiceInstanceManager):
    def __init__(self, config: Config, registry: ServiceInstanceRegistry, on_event: OnEvent | None = None) -> None:
        source = PythonConnectorSource()
        super().__init__(source, config, registry)
        self._on_event = on_event

    def bind(self, on_event: OnEvent) -> None:
        self._on_event = on_event

    def resolve(self) -> list[Connector]:
        return self.instances

    def _create_instance(self, descriptor: ConnectorDescriptor) -> Connector:
        connector = descriptor.connector_cls(config=self._config)
        connector._on_event = self._on_event
        return connector
