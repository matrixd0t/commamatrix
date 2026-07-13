# api/service.py

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any

from ..extensions import ExtensionDescriptor, ExtensionSource

SERVICE_ATTRIBUTE = "__commamatrix_service__"


class Service(ABC):
    """Lifecycle contract for agent-owned components.

    Subclasses are auto-discovered via __init_subclass__ marker when
    imported. start / stop are called by the owning agent;
    refresh is called before each handle and after start.
    """

    config: Any

    def __init__(self, config: Any = None) -> None:
        self.config = config

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "__abstractmethods__", None):
            setattr(cls, SERVICE_ATTRIBUTE, True)

    async def start(self) -> None:
        """Initialize resources. Called once after agent startup."""

    async def stop(self) -> None:
        """Release resources. Called once during agent shutdown."""

    async def refresh(self) -> None:
        """Synchronize state with current extension set. May be called often."""


@dataclass(frozen=True, slots=True)
class ServiceDescriptor(ExtensionDescriptor):
    """Immutable descriptor for a discoverable Service class."""

    service_cls: type[Service]
    metadata: dict[str, Any] = field(default_factory=dict)

    def _fingerprint_payload(self) -> dict[str, Any]:
        return {"id": self.id, "service_cls": self.service_cls.__qualname__}

