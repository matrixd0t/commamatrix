# core/base/service.py

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ...components.config import Config
from .descriptor import Descriptor

if TYPE_CHECKING:
    from ..agent.agent import Agent

SERVICE_ATTRIBUTE = "__commamatrix_service__"


class AbstractService(ABC):
    """Agent-owned component integrated into lifecycle.

    Pure lifecycle ABC: start / stop / refresh.

    You generally want to subclass Service instead of this.
    Subclass this directly when you need the lifecycle contract
    but NOT automatic discovery (like Connector subclasses, which
    are discovered separately via CONNECTOR_ATTRIBUTE).
    """

    def __init__(self, agent: Agent) -> None:
        self.agent = agent

    @property
    def config(self) -> Config:
        return self.agent.config

    async def start(self) -> None:
        """Initialize resources. Called once after agent startup."""

    async def stop(self) -> None:
        """Release resources. Called once during agent shutdown."""

    async def refresh(self) -> None:
        """Synchronize state with current extension set. May be called often."""


class Service(AbstractService):
    """AbstractService subclass that auto-registers via SERVICE_ATTRIBUTE.

    Used for services that should be discovered by provider managers
    (Storage, FileStorage, LLMAdapter, CodeActService, etc.).

    You generally should subclass THIS instead of AbstractService while designing
    a service that should integrate into Agent lifecycle.
    """

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "__abstractmethods__", None):
            setattr(cls, SERVICE_ATTRIBUTE, True)


@dataclass(frozen=True, slots=True)
class ServiceDescriptor(Descriptor):
    """Immutable descriptor for a discoverable AbstractService class."""

    service_cls: type[AbstractService]
    metadata: dict[str, Any]

    def _fingerprint_payload(self) -> dict[str, Any]:
        return {"id": self.id, "service_cls": self.service_cls.__qualname__}
