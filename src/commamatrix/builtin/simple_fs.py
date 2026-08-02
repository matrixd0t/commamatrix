# builtin/simple_fs.py

from __future__ import annotations

import uuid
from aiofiles import open, os
from pathlib import Path

from typing import TYPE_CHECKING
from ..components.file_storage import FileStorage
from ..components.config import ConfigField
from ..utils import commamatrix_dir

if TYPE_CHECKING:
    from ..core.agent import Agent

files_dir = ConfigField[str](name='files_dir', default='files', description='Subdirectory of commamatrix_dir for file storage')


class SimpleFileStorage(FileStorage):

    def __init__(self, agent: Agent) -> None:
        super().__init__(agent)
        self._directory = Path(self.config.get(commamatrix_dir)) / self.config.get(files_dir)

    async def save(self, data: bytes, ext: str | None = None) -> str:
        self._directory.mkdir(parents=True, exist_ok=True)
        file_id = uuid.uuid4().hex + (f'.{ext.lstrip(".")}' if ext else '')
        path = self._directory / file_id
        async with open(path, 'wb') as f:
            await f.write(data)
        return file_id

    async def _resolve_path(self, file_id: str) -> Path | None:
        path = self._directory / file_id
        try:
            async with open(path, 'rb'):
                return path
        except FileNotFoundError:
            pass

        if '.' not in file_id:
            try:
                for entry in self._directory.iterdir():
                    if entry.name.startswith(file_id + '.') and entry.is_file():
                        return entry
            except FileNotFoundError:
                return None

        return None

    async def get(self, file_id: str) -> bytes | None:
        path = await self._resolve_path(file_id)
        if path is None:
            return None
        async with open(path, 'rb') as file:
            return await file.read()

    async def delete(self, file_id: str) -> bool:
        path = await self._resolve_path(file_id)
        if path is None:
            return False
        try:
            await os.remove(path)
        except FileNotFoundError:
            return False
        return True


__all__ = [
    "files_dir",
    "SimpleFileStorage"
]
