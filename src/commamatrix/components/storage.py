# components/storage.py

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Optional, TYPE_CHECKING

from ..core.classes.service import AbstractService
from ..core.classes.manager import ActiveServiceInstanceManager
from ..core.classes.source import PythonServiceSource
from .config import ConfigField
from .dialog import DialogItem, DialogOrigin

if TYPE_CHECKING:
    from ..core.agent import Agent

STORAGE_ATTRIBUTE = "__commamatrix_storage__"

active_storage = ConfigField[str | None](
    name="active_storage",
    default=None,
    description="Descriptor id of the active storage, or None for first available",
)


class Storage(AbstractService):
    def __init__(self, agent: Agent) -> None:
        super().__init__(agent)

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "__abstractmethods__", None):
            setattr(cls, STORAGE_ATTRIBUTE, True)

    @abstractmethod
    async def save_event(self, entry: DialogItem) -> int | None: ...

    @abstractmethod
    async def get_branch(self, last_item_id: int) -> list[DialogItem]: ...

    @abstractmethod
    async def find_item_id_by_external_id(self, external_id: str, origin: DialogOrigin) -> Optional[int]: ...

    @abstractmethod
    async def get_history(self, *, origin_type: type[DialogOrigin] | None = None, origin_fields: dict[str, Any] | None = None) -> list[DialogItem]: ...

    async def execute(self, query: str, params: tuple = ()) -> list[dict[str, Any]]:
        raise NotImplementedError


class PythonStorageSource(PythonServiceSource):
    """Storage-specific source with per-module tracking for extension
    management. Extends PythonServiceSource with module-level
    descriptor indexing used by add_extensions / remove_extensions."""

    def __init__(self) -> None:
        super().__init__(base_type=Storage, marker_attribute=STORAGE_ATTRIBUTE, id_prefix="storage")


class StorageManager(ActiveServiceInstanceManager[Storage]):
    base_type = Storage
    marker_attribute = STORAGE_ATTRIBUTE
    id_prefix = "storage"
    active_field = active_storage

    def __init__(self, agent, **kwargs) -> None:
        super().__init__(agent, source=PythonStorageSource(), **kwargs)

    async def save_event(self, entry: DialogItem) -> int | None:
        return await self._active.save_event(entry)

    async def get_branch(self, last_item_id: int) -> list[DialogItem]:
        return await self._active.get_branch(last_item_id)

    async def find_item_id_by_external_id(self, external_id: str, origin: DialogOrigin) -> int | None:
        return await self._active.find_item_id_by_external_id(external_id, origin)

    async def get_history(self, *, origin_type: type[DialogOrigin] | None = None, origin_fields: dict[str, Any] | None = None) -> list[DialogItem]:
        return await self._active.get_history(origin_type=origin_type, origin_fields=origin_fields)

    async def execute(self, query: str, params: tuple = ()) -> list[dict[str, Any]]:
        return await self._active.execute(query, params)
