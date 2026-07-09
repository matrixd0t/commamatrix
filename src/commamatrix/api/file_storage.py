from abc import ABC, abstractmethod


class FileStorage(ABC):
    """Abstract binary blob storage. Implementations persist files keyed by
    string IDs that embed the file extension (e.g. abc123.png)."""

    @classmethod
    @abstractmethod
    async def save(cls, data: bytes, ext: str | None = None) -> str:
        """Persist binary data and return the assigned file ID.
        If ext is provided (e.g. '.png'), it is appended to the ID."""

    @classmethod
    @abstractmethod
    async def get(cls, file_id: str) -> bytes | None:
        """Retrieve raw bytes by file ID, or None if not found."""

    @classmethod
    @abstractmethod
    async def delete(cls, file_id: str) -> bool:
        """Remove a stored file by ID. Return True on success, False if not found."""
