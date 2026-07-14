# core/storage_manager.py

from __future__ import annotations

from .provider_manager import ActiveServiceInstanceManager
from ..api.config import active_storage
from ..api.dialog import DialogItem, DialogOrigin
from ..api.storage import STORAGE_ATTRIBUTE, Storage


class StorageManager(ActiveServiceInstanceManager):
    """Manages Storage instances and forwards calls to the active one."""

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
