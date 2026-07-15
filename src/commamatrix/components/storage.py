# components/storage.py

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Optional, TYPE_CHECKING

from ..core.base.service import AbstractService
from ..core.base.manager import ActiveInstanceServiceManager
from .config import active_storage
from .dialog import DialogItem, DialogOrigin

if TYPE_CHECKING:
    from .config import Config

STORAGE_ATTRIBUTE = "__commamatrix_storage__"


class Storage(AbstractService):
    def __init__(self, config: Config) -> None:
        super().__init__(config)

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "__abstractmethods__", None):
            setattr(cls, STORAGE_ATTRIBUTE, True)

    @abstractmethod
    async def save_event(self, entry: DialogItem) -> int | None: ...

    @abstractmethod
    async def get_branch(self, last_item_id: int) -> list[DialogItem]: ...

    @abstractmethod
    async def find_item_id_by_external_id(
        self, external_id: str, origin: DialogOrigin
    ) -> Optional[int]: ...

    async def execute(self, query: str, params: tuple = ()) -> list[dict[str, Any]]:
        raise NotImplementedError


class StorageManager(ActiveInstanceServiceManager):
    _cls = Storage
    _attribute = STORAGE_ATTRIBUTE
    _prefix = "storage"
    active_field = active_storage

    async def save_event(self, entry: DialogItem) -> int | None:
        return await self._active.save_event(entry)

    async def get_branch(self, last_item_id: int) -> list[DialogItem]:
        return await self._active.get_branch(last_item_id)

    async def find_item_id_by_external_id(self, external_id: str, origin: DialogOrigin) -> int | None:
        return await self._active.find_item_id_by_external_id(external_id, origin)

    async def execute(self, query: str, params: tuple = ()) -> list[dict[str, Any]]:
        return await self._active.execute(query, params)
