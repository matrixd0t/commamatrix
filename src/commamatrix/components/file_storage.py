# components/file_storage.py

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from ..core.base.service import AbstractService
from ..core.base.manager import ActiveInstanceServiceManager
from .config import active_file_storage

if TYPE_CHECKING:
    from .config import Config

FILE_STORAGE_ATTRIBUTE = "__commamatrix_file_storage__"


class FileStorage(AbstractService):
    def __init__(self, config: Config) -> None:
        super().__init__(config)

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "__abstractmethods__", None):
            setattr(cls, FILE_STORAGE_ATTRIBUTE, True)

    @abstractmethod
    async def save(self, data: bytes, ext: str | None = None) -> str: ...

    @abstractmethod
    async def get(self, file_id: str) -> bytes | None: ...

    @abstractmethod
    async def delete(self, file_id: str) -> bool: ...


class FileStorageManager(ActiveInstanceServiceManager):
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
