# api/file_storage.py

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config


class FileStorage(ABC):
    """Abstract binary blob storage. Implementations persist files keyed by
    string IDs that embed the file extension (e.g. abc123.png)."""

    def __init__(self, config: Config) -> None:
        """Initialize from per-agent Config. Subclasses read their fields via config.get(field)."""

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
