# api/storage.py

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional, TYPE_CHECKING

from .dialog import DialogItem, DialogOrigin

if TYPE_CHECKING:
    from .config import Config


class Storage(ABC):
    def __init__(self, config: Config) -> None:
        """Initialize from per-agent Config. Subclasses read their fields via config.get(field)."""

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
