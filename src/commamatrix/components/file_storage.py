# components/file_storage.py

from __future__ import annotations

import asyncio
from abc import abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from mimetypes import guess_type
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from httpx2 import HTTPError

from ..core.classes.lifecycle_registry import lifecycle_component
from ..core.classes.service import AbstractService
from ..core.classes.manager import ActiveServiceInstanceManager
from ..core.classes.source import PythonServiceSource
from .config import ConfigField

FILE_STORAGE_ATTRIBUTE = "__commamatrix_file_storage__"

active_file_storage = ConfigField[str | None](
    name="active_file_storage",
    default=None,
    description="Descriptor id of the active file storage, or None for first available",
)


class DataType(StrEnum):
    TEXT = "text"
    FILE = "file"
    IMAGE = "image"


@dataclass(slots=True, kw_only=True)
class FileData:
    data: bytes
    name: str
    mime_type: str
    data_type: DataType
    url: str | None = None


@dataclass(slots=True, kw_only=True)
class FileContext:
    content: str
    name: str
    mime_type: str
    data_type: DataType


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

    def url(self, file_id: str) -> str:
        return self.agent.http_server.file_url(file_id)


class PythonFileStorageSource(PythonServiceSource):
    def __init__(self) -> None:
        super().__init__(base_type=FileStorage, marker_attribute=FILE_STORAGE_ATTRIBUTE, id_prefix="file_storage")


@lifecycle_component(key="file_storage", priority=400, after="table_manager")
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

    def url(self, file_id: str) -> str:
        return self.agent.http_server.file_url(file_id)


def ext_to_mime(ext: str) -> str:
    mime_type, _ = guess_type(f"file.{ext.lstrip('.')}")
    if not mime_type and ext.lstrip(".").lower() == "webp":
        return "image/webp"
    return mime_type or "application/octet-stream"


def normalize_file_id(file_id: object) -> str | None:
    if not isinstance(file_id, str) or not file_id or file_id in {".", ".."}:
        return None
    if "/" in file_id or "\\" in file_id:
        return None
    return file_id


def _normalize_content_type(content_type: DataType | str) -> DataType:
    value = content_type.value if isinstance(content_type, DataType) else str(content_type).lower()
    value = value.removesuffix("_input").removesuffix("_output")
    try:
        return DataType(value)
    except ValueError as exc:
        raise ValueError(f"Unsupported file content type: {content_type!r}") from exc


def _normalize_modalities(modalities: Iterable[DataType | str] | DataType | str | None) -> set[DataType]:
    if modalities is None:
        return set()
    if isinstance(modalities, (DataType, str)):
        modalities = (modalities,)
    return {_normalize_content_type(modality) for modality in modalities}


def _clean_mime_type(value: str | None) -> str | None:
    if not value:
        return None
    mime_type = value.split(";", 1)[0].strip().lower()
    return mime_type or None


def _source_name(ref: str, name: str | None) -> str:
    if name:
        return name
    parsed = urlparse(ref)
    if parsed.scheme in {"http", "https"}:
        return unquote(Path(parsed.path).name) or ref
    return Path(ref).name or ref


def _infer_content_type(mime_type: str) -> DataType:
    if mime_type.startswith("image/"):
        return DataType.IMAGE
    if (
        mime_type.startswith("text/")
        or mime_type in {"application/json", "application/javascript", "application/yaml", "application/x-yaml"}
        or mime_type.endswith(("+json", "+xml"))
    ):
        return DataType.TEXT
    return DataType.FILE


async def read_file(
    ref: str,
    *,
    file_storage: FileStorage | None = None,
    http_client: Any | None = None,
    name: str | None = None,
    ext: str | None = None,
    mime_type: str | None = None,
    content_type: DataType | str | None = None,
    make_url: bool = False,
) -> FileData | None:
    """Load bytes from a URL, absolute path, or configured file storage."""
    ref = str(ref).strip()
    if not ref:
        return None

    data: bytes = b""
    response_mime: str | None = None
    source_url: str | None = None
    if urlparse(ref).scheme in {"http", "https"}:
        if http_client is None:
            if file_storage is None:
                raise RuntimeError("An HTTP client or FileStorage is required for URL sources")
            http_client = file_storage.agent.http_client
        try:
            response = await http_client.get(ref, follow_redirects=True, timeout=30)
            response.raise_for_status()
        except HTTPError:
            return None
        data = response.content
        response_mime = _clean_mime_type(response.headers.get("content-type"))
        source_url = ref
    elif Path(ref).is_absolute():
        path = Path(ref)
        if not path.is_file():
            return None
        try:
            async with aio_open(path, "rb") as file:
                data = await file.read()
        except OSError:
            return None
    else:
        if file_storage is None:
            return None
        stored_data = await file_storage.get(ref)
        if stored_data is None:
            return None
        data = stored_data
        source_url = file_storage.url(ref)

    file_name = _source_name(ref, name)
    file_ext = (ext or Path(file_name).suffix).lstrip(".").lower()
    if source_url is None and make_url and Path(ref).is_absolute() and file_storage is not None:
        stored_id = await file_storage.save(data, ext=file_ext or None)
        source_url = file_storage.url(stored_id)
    resolved_mime = (
        _clean_mime_type(mime_type)
        or response_mime
        or _clean_mime_type(guess_type(file_name)[0])
        or ext_to_mime(file_ext)
    )
    resolved_type = (
        _normalize_content_type(content_type)
        if content_type is not None
        else _infer_content_type(resolved_mime)
    )
    return FileData(
        data=data,
        name=file_name,
        mime_type=resolved_mime,
        data_type=resolved_type,
        url=source_url,
    )


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-32", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def file_to_context(
    file_data: FileData,
    *,
    modalities: Iterable[DataType | str] | DataType | str | None = None,
    content_type: DataType | str | None = None,
) -> FileContext:
    """Render file data as text, a URL, or a compact context marker."""
    source_type: DataType
    if content_type is not None:
        source_type = _normalize_content_type(content_type)
    else:
        inferred_type = file_data.data_type
        if inferred_type is None:
            inferred_type = DataType.FILE
        source_type = _normalize_content_type(inferred_type)
    if source_type is DataType.TEXT:
        content = _decode_text(file_data.data)
        return FileContext(
            content=content,
            data_type=source_type,
            mime_type=file_data.mime_type,
            name=file_data.name,
        )

    if source_type in _normalize_modalities(modalities) and file_data.url:
        return FileContext(
            content=file_data.url,
            data_type=source_type,
            mime_type=file_data.mime_type,
            name=file_data.name,
        )

    content = (
        f"[Attached {source_type.value}: name={file_data.name}, "
        f"size={len(file_data.data)} bytes, mime={file_data.mime_type}]"
    )
    return FileContext(
        content=content,
        data_type=source_type,
        mime_type=file_data.mime_type,
        name=file_data.name,
    )
