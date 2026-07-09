from abc import ABC, abstractmethod
from typing import Any, Optional

from .dialog import DialogItem, DialogOrigin


class Storage(ABC):
    @classmethod
    @abstractmethod
    async def save_event(cls, entry: DialogItem) -> int | None:
        ...

    @classmethod
    @abstractmethod
    async def get_branch(cls, last_item_id: int) -> list[DialogItem]:
        ...

    @classmethod
    @abstractmethod
    async def find_item_id_by_external_id(cls, external_id: str, origin: DialogOrigin) -> Optional[int]:
        ...

    @classmethod
    async def execute(cls, query: str, params: tuple = ()) -> list[dict[str, Any]]:
        raise NotImplementedError
