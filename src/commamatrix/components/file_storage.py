# components/file_storage.py

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from ..core.classes.service import AbstractService
from ..core.classes.manager import ActiveServiceInstanceManager
from ..core.classes.source import PythonServiceSource
from .config import ConfigField

if TYPE_CHECKING:
    from ..core.agent import Agent

FILE_STORAGE_ATTRIBUTE = "__commamatrix_file_storage__"

active_file_storage = ConfigField[str | None](
    name="active_file_storage",
    default=None,
    description="Descriptor id of the active file storage, or None for first available",
)


class FileStorage(AbstractService):
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


class PythonFileStorageSource(PythonServiceSource):
    def __init__(self) -> None:
        super().__init__(base_type=FileStorage, marker_attribute=FILE_STORAGE_ATTRIBUTE, id_prefix="file_storage")


class FileStorageManager(ActiveServiceInstanceManager[FileStorage]):
    base_type = FileStorage
    marker_attribute = FILE_STORAGE_ATTRIBUTE
    id_prefix = "file_storage"
    active_field = active_file_storage

    def __init__(self, agent, **kwargs) -> None:
        super().__init__(agent, source=PythonFileStorageSource(), **kwargs)

    async def save(self, data: bytes, ext: str | None = None) -> str:
        return await self._active.save(data, ext)

    async def get(self, file_id: str) -> bytes | None:
        return await self._active.get(file_id)

    async def delete(self, file_id: str) -> bool:
        return await self._active.delete(file_id)
