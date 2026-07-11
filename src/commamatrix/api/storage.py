# api/storage.py

from abc import ABC, abstractmethod
from typing import Any, Optional

from .dialog import DialogItem, DialogOrigin


class Storage(ABC):
    @abstractmethod
    async def save_event(self, entry: DialogItem) -> int | None:
        ...

    @abstractmethod
    async def get_branch(self, last_item_id: int) -> list[DialogItem]:
        ...

    @abstractmethod
    async def find_item_id_by_external_id(self, external_id: str, origin: DialogOrigin) -> Optional[int]:
        ...

    async def execute(self, query: str, params: tuple = ()) -> list[dict[str, Any]]:
        raise NotImplementedError
