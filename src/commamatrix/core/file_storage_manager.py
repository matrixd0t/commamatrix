# core/file_storage_manager.py

from __future__ import annotations

from .provider_manager import ProviderManager
from ..api.config import active_file_storage
from ..api.file_storage import FILE_STORAGE_ATTRIBUTE, FileStorage
from ..builtin.python.provider_source import PythonProviderSource


class FileStorageManager(ProviderManager):
    """Manages FileStorage instances and forwards calls to the active one."""

    def __init__(self) -> None:
        source = PythonProviderSource(FileStorage, FILE_STORAGE_ATTRIBUTE, "file_storage")
        super().__init__(source, active_field=active_file_storage, error_prefix="file storage")

    async def save(self, data: bytes, ext: str | None = None) -> str:
        fs = self._active
        if fs is None:
            raise RuntimeError("No active file storage")
        return await fs.save(data, ext)

    async def get(self, file_id: str) -> bytes | None:
        fs = self._active
        if fs is None:
            raise RuntimeError("No active file storage")
        return await fs.get(file_id)

    async def delete(self, file_id: str) -> bool:
        fs = self._active
        if fs is None:
            raise RuntimeError("No active file storage")
        return await fs.delete(file_id)
