# builtin/simple_fs.py

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from ..components.config import ConfigField
from ..components.file_storage import FileStorage
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
        await asyncio.to_thread(path.write_bytes, data)
        self.logger.debug("File saved size=%d extension=%s", len(data), ext or "")
        return file_id

    async def _resolve_path(self, file_id: str) -> Path | None:
        path = self._directory / file_id
        if await asyncio.to_thread(path.is_file):
            return path

        if '.' not in file_id:
            try:
                entries = await asyncio.to_thread(lambda: tuple(self._directory.iterdir()))
                for entry in entries:
                    if entry.name.startswith(file_id + '.') and entry.is_file():
                        return entry
            except FileNotFoundError:
                return None

        return None

    async def get(self, file_id: str) -> bytes | None:
        path = await self._resolve_path(file_id)
        if path is None:
            return None
        try:
            data = await asyncio.to_thread(path.read_bytes)
            self.logger.debug("File loaded size=%d", len(data))
            return data
        except OSError:
            self.logger.warning("File read failed")
            return None

    async def delete(self, file_id: str) -> bool:
        path = await self._resolve_path(file_id)
        if path is None:
            return False
        try:
            await asyncio.to_thread(path.unlink)
        except FileNotFoundError:
            return False
        self.logger.debug("File deleted")
        return True


__all__ = [
    "SimpleFileStorage",
    "files_dir"
]
