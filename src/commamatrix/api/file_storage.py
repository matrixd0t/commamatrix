# api/file_storage.py

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from .service import AbstractService

if TYPE_CHECKING:
    from .config import Config

FILE_STORAGE_ATTRIBUTE = "__commamatrix_file_storage__"


class FileStorage(AbstractService):
    """Abstract binary blob storage. Implementations persist files keyed by
    string IDs that embed the file extension (e.g. abc123.png)."""

    def __init__(self, config: Config) -> None:
        super().__init__(config)

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "__abstractmethods__", None):
            setattr(cls, FILE_STORAGE_ATTRIBUTE, True)

    @abstractmethod
    async def save(self, data: bytes, ext: str | None = None) -> str:
        """Persist binary data and return the assigned file ID.
        If ext is provided (e.g. '.png'), it is appended to the ID."""

    @abstractmethod
    async def get(self, file_id: str) -> bytes | None:
        """Retrieve raw bytes by file ID, or None if not found."""

    @abstractmethod
    async def delete(self, file_id: str) -> bool:
        """Remove a stored file by ID. Return True on success, False if not found."""
