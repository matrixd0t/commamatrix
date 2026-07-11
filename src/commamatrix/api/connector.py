# api/connector.py

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, ClassVar, Generic, TYPE_CHECKING, TypeVar, get_args, get_origin
from contextlib import asynccontextmanager

from .dialog import DialogItem, DialogOrigin
from ..core.extension_runtime import ExtensionDescriptor, ExtensionSource

if TYPE_CHECKING:
    from .hooks import OnParsedCtx
    from ..core.agent import Agent

CONNECTOR_ATTRIBUTE = "__commamatrix_connector__"
CONNECTOR_MODULES: set[str] = set()

type OnEvent = Callable[[dict], Awaitable[None]]


OrgT = TypeVar('OrgT', bound=DialogOrigin)


class Connector(ABC, Generic[OrgT]):
    """
    Abstract connector. Concrete subclasses auto-register their module
    in __init_subclass__ for later scanning by PythonConnectorSource.
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
            setattr(cls, CONNECTOR_ATTRIBUTE, True)
            CONNECTOR_MODULES.add(cls.__module__)

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
class ConnectorDescriptor(ExtensionDescriptor):
    connector_cls: type[Connector]
    metadata: dict[str, Any] = field(default_factory=dict)

    def _fingerprint_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "connector_cls": self.connector_cls.__qualname__,
        }


class ConnectorSource(ExtensionSource[ConnectorDescriptor]):
    @abstractmethod
    def scan(self) -> list[ConnectorDescriptor]:
        raise NotImplementedError

    async def invoke(self, descriptor: ConnectorDescriptor, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError
