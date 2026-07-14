# core/file_storage_manager.py

from __future__ import annotations

from .provider_manager import ActiveServiceInstanceManager
from ..api.config import active_file_storage
from ..api.file_storage import FILE_STORAGE_ATTRIBUTE, FileStorage


class FileStorageManager(ActiveServiceInstanceManager):
    """Manages FileStorage instances and forwards calls to the active one."""

    _cls = FileStorage
    _attribute = FILE_STORAGE_ATTRIBUTE
    _prefix = "file storage"
    active_field = active_file_storage

    async def save(self, data: bytes, ext: str | None = None) -> str:
        return await self._active.save(data, ext)

    async def get(self, file_id: str) -> bytes | None:
        return await self._active.get(file_id)

    async def delete(self, file_id: str) -> bool:
        return await self._active.delete(file_id)
