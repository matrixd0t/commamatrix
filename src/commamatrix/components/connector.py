# components/connector.py

from __future__ import annotations

import asyncio
import types
import weakref
from abc import abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import tzinfo
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Generic,
    TypeVar,
    cast,
    get_args,
    get_origin,
)
from typing import Union as TypingUnion

from ..core.classes.lifecycle_registry import lifecycle_component
from ..core.classes.manager import ServiceInstanceManager
from ..core.classes.service import AbstractService, ServiceDescriptor
from ..core.classes.source import PythonSource
from .dialog import DialogItem, DialogOrigin
from .llm_adapter import LLMModalities, StreamDelta

if TYPE_CHECKING:
    from ..core.agent import Agent
    from .hook import OnParsedCtx

type OnRecv = Callable[[dict], Awaitable[list[asyncio.Task]]]

CONNECTOR_ATTRIBUTE = "__commamatrix_connector__"

OrgT = TypeVar("OrgT", bound=DialogOrigin)


@dataclass(frozen=True, slots=True)
class UserInfo:
    """Basic platform user data returned by connector lookups."""

    id: int | str
    name: str
    matched_name: str | None = None
    name_changed: bool = False


class Connector(AbstractService, Generic[OrgT]):
    """Abstract platform adapter. Subclasses implement parse() to convert platform format into OnParsedCtx, and send() to deliver outgoing messages.
    Lifecycle: start() launches listener, stop() cancels."""

    origin_types: ClassVar[tuple[type[DialogOrigin], ...]] = ()
    supports_streaming: ClassVar[bool] = False
    modalities: ClassVar[LLMModalities] = LLMModalities()

    def __init__(self, agent: Agent) -> None:
        super().__init__(agent)
        self._listener_task: asyncio.Task | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        for base in getattr(cls, "__orig_bases__", ()):
            origin = get_origin(base)
            if origin is not Connector and not (isinstance(origin, type) and issubclass(origin, Connector)):
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
        current = self._listener_task
        if current is not None and not current.done():
            return
        self._listener_task = asyncio.create_task(self.listen(self.agent.handle))
        self.logger.info("Connector listener started connector=%s", type(self).__name__)

    async def stop(self) -> None:
        task = self._listener_task
        self._listener_task = None
        if task is None or task.done():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.logger.info("Connector listener stopped connector=%s", type(self).__name__)

    @abstractmethod
    async def parse(self, data: dict) -> OnParsedCtx | None: ...

    @abstractmethod
    async def send(self, origin: DialogOrigin, item: DialogItem) -> str:
        """Render an item and return its external ID, or an empty string."""

    async def publish_item(self, origin: DialogOrigin, item: DialogItem) -> None:
        """Publish a persisted item to passive subscribers when supported."""

    async def get_user_timezone(self, origin: DialogOrigin) -> tzinfo | None:
        """Return a user's timezone when the platform can provide one."""
        return None

    async def get_user_info(self, user: int | str) -> UserInfo | None:
        """Return basic user information when the platform supports lookup."""
        return None

    async def send_stream_chunk(self, origin: DialogOrigin, chunk: StreamDelta) -> None:
        """Send a real-time content delta to the platform for live rendering."""

    @asynccontextmanager
    async def typing(self, origin: DialogOrigin) -> AsyncIterator[None]:
        yield

    async def listen(self, on_recv: OnRecv) -> None:
        pass


@dataclass(frozen=True, slots=True)
class ConnectorDescriptor(ServiceDescriptor):
    """Extends ServiceDescriptor with connector_cls for direct Connector instantiation."""
    connector_cls: type[Connector]


class PythonConnectorSource(PythonSource[ConnectorDescriptor]):
    """Scans scope for concrete Connector subclasses and builds ConnectorDescriptors for each."""

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


@lifecycle_component(key="connector_manager", priority=200, after="service_manager")
class ConnectorManager(ServiceInstanceManager[Connector]):
    """
    Manages connector instances.
    Wires agent.handle on each connector during creation and provides resolve() to retrieve all active connectors.
    """

    def __init__(self, agent: Agent, **kwargs: object) -> None:
        super().__init__(agent, source=PythonConnectorSource(), **kwargs)

    def resolve(self) -> list[Connector]:
        return self.instances

    def resolve_for_origin(self, origin: DialogOrigin) -> Connector:
        matches = [connector for connector in self.instances if isinstance(origin, connector.origin_types)]
        if len(matches) != 1:
            self.logger.error("Connector resolution failed origin_type=%s matches=%d", type(origin).__name__, len(matches))
            raise LookupError(f"Expected one connector for {type(origin).__name__}, found {len(matches)}")
        self.logger.debug("Connector resolved origin_type=%s connector=%s", type(origin).__name__, type(matches[0]).__name__)
        return matches[0]

    def _create_instance(self, descriptor: ConnectorDescriptor) -> Connector:
        return descriptor.connector_cls(agent=self.agent)
