# core/storage_manager.py

from __future__ import annotations

from typing import Any, Optional

from .provider_manager import ProviderManager
from ..api.config import Config, active_storage
from ..api.dialog import DialogItem, DialogOrigin
from ..api.storage import STORAGE_ATTRIBUTE, Storage
from ..builtin.python.provider_source import PythonProviderSource


class StorageManager(ProviderManager):
    """Manages Storage instances and forwards calls to the active one."""

    def __init__(self) -> None:
        source = PythonProviderSource(Storage, STORAGE_ATTRIBUTE, "storage")
        super().__init__(source, active_field=active_storage, error_prefix="storage")

    async def save_event(self, entry: DialogItem) -> int | None:
        storage = self._active
        if storage is None:
            raise RuntimeError("No active storage")
        return await storage.save_event(entry)

    async def get_branch(self, last_item_id: int) -> list[DialogItem]:
        storage = self._active
        if storage is None:
            raise RuntimeError("No active storage")
        return await storage.get_branch(last_item_id)

    async def find_item_id_by_external_id(self, external_id: str, origin: DialogOrigin) -> Optional[int]:
        storage = self._active
        if storage is None:
            raise RuntimeError("No active storage")
        return await storage.find_item_id_by_external_id(external_id, origin)

    async def execute(self, query: str, params: tuple = ()) -> list[dict[str, Any]]:
        storage = self._active
        if storage is None:
            raise RuntimeError("No active storage")
        return await storage.execute(query, params)
