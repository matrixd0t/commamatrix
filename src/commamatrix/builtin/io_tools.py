# builtin/io_tools.py

from __future__ import annotations

import base64
import binascii
from mimetypes import guess_type
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from aiofiles import open as aio_open
from httpx import HTTPError

from ..components.file_storage import (
    FileContentType,
    FileData,
    ext_to_mime,
    file_to_context,
    read_file,
)
from ..components.hook import BeforeToolCallCtx
from ..components.tool import tool

ContentType = Literal["text", "file", "image"]


def _extension(name: str, ext: str | None) -> str:
    value = (ext or Path(name).suffix).strip()
    if not value:
        return ""
    return value if value.startswith(".") else f".{value}"


def _mime_type(name: str, ext: str | None, mime_type: str | None) -> str:
    if mime_type:
        return mime_type.split(";", 1)[0].strip().lower()
    return guess_type(name)[0] or ext_to_mime(ext or Path(name).suffix)


def _with_name(file_data: FileData, name: str | None, ext: str | None) -> FileData:
    file_name = name or file_data.name or "file"
    extension = _extension(file_name, ext)
    if extension and not Path(file_name).suffix:
        file_name += extension
    if file_name == file_data.name:
        return file_data
    return FileData(
        data=file_data.data,
        name=file_name,
        mime_type=file_data.mime_type,
        content_type=file_data.content_type,
        source=file_data.source,
    )


async def _read_source(
        source: str,
        *,
        name: str | None,
        ext: str | None,
        mime_type: str | None,
        content_type: ContentType | None,
        ctx: BeforeToolCallCtx,
) -> FileData:
    file_data = await read_file(
        source,
        file_storage=ctx.run.agent.file_storage,
        http_client=ctx.run.agent.http_client,
        name=name,
        ext=ext,
        mime_type=mime_type,
        content_type=content_type,
    )
    if file_data is None:
        raise FileNotFoundError(f"File source was not found: {source}")
    return _with_name(file_data, name, ext)


@tool(alias="io")
async def read(
        ref: str,
        modalities: list[Literal["text", "file", "image"]],
        content_type: ContentType | None = None,
        name: str | None = None,
        ext: str | None = None,
        mime_type: str | None = None,
        *,
        ctx: BeforeToolCallCtx,
) -> str:
    """Read a URL, absolute path, or stored file as text or data URI."""
    file_data = await read_file(
        ref,
        file_storage=ctx.run.agent.file_storage,
        http_client=ctx.run.agent.http_client,
        name=name,
        ext=ext,
        mime_type=mime_type,
        content_type=content_type,
    )
    if file_data is None:
        return f"Error: file not found or unavailable: {ref}"
    rendered = file_to_context(
        file_data,
        modalities=modalities,
        content_type=content_type,
    )
    return rendered.content


@tool(alias="io")
async def write(
        source: str,
        target: str | None = None,
        source_type: Literal["content", "ref"] = "content",
        encoding: Literal["text", "base64"] = "text",
        name: str | None = None,
        ext: str | None = None,
        mime_type: str | None = None,
        field_name: str = "file",
        fields: dict[str, str] | None = None,
        content_type: ContentType | None = None,
        *,
        ctx: BeforeToolCallCtx,
) -> str:
    """Write text/base64 or a referenced file to storage, a path, or multipart HTTP."""
    if source_type not in {"content", "ref"}:
        return "Error: source_type must be 'content' or 'ref'."
    if source_type == "ref" and not source.strip():
        return "Error: source must not be empty for source_type='ref'."
    if encoding not in {"text", "base64"}:
        return "Error: encoding must be 'text' or 'base64'."
    field_name = field_name.strip()
    if not field_name:
        return "Error: field_name must not be empty."

    try:
        if source_type == "ref":
            file_data = await _read_source(
                source,
                name=name,
                ext=ext,
                mime_type=mime_type,
                content_type=content_type,
                ctx=ctx,
            )
        else:
            file_name = name or "file"
            extension = _extension(file_name, ext)
            if extension and not Path(file_name).suffix:
                file_name += extension
            resolved_mime = _mime_type(file_name, ext, mime_type)
            if encoding == "text" and mime_type is None and ext is None and not Path(file_name).suffix:
                resolved_mime = "text/plain"
            data = (
                base64.b64decode(source, validate=True)
                if encoding == "base64"
                else source.encode("utf-8")
            )
            resolved_type = FileContentType(content_type) if content_type else (
                FileContentType.IMAGE
                if resolved_mime.startswith("image/")
                else FileContentType.TEXT
                if resolved_mime.startswith("text/")
                else FileContentType.FILE
            )
            file_data = FileData(
                data=data,
                name=file_name,
                mime_type=resolved_mime,
                content_type=resolved_type,
                source="tool",
            )
    except (binascii.Error, FileNotFoundError, OSError, ValueError) as exc:
        return f"Error preparing file: {exc}"

    destination = target.strip() if target else ""
    parsed = urlparse(destination)
    if parsed.scheme in {"http", "https"}:
        try:
            response = await ctx.run.agent.http_client.post(
                destination,
                data=fields or {},
                files={field_name: (file_data.name, file_data.data, file_data.mime_type)},
            )
            response.raise_for_status()
        except HTTPError as exc:
            return f"Error uploading file to {destination}: {exc}"
        response_text = response.text.strip()
        suffix = f"\nResponse: {response_text[:2000]}" if response_text else ""
        return f"Uploaded {file_data.name} ({len(file_data.data)} bytes) to {destination}.{suffix}"

    if destination:
        path = Path(destination)
        if not path.is_absolute():
            return "Error: target must be an HTTP(S) URL, an absolute path, or omitted."
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            async with aio_open(path, "wb") as file:
                await file.write(file_data.data)
        except OSError as exc:
            return f"Error writing file to {path}: {exc}"
        return f"Wrote {len(file_data.data)} bytes to {path}."

    try:
        file_name = file_data.name or "file"
        file_id = await ctx.run.agent.file_storage.save(
            file_data.data,
            ext=_extension(file_name, ext),
        )
    except Exception as exc:
        return f"Error saving file to FileStorage: {exc}"
    return f"Stored file {file_id} ({len(file_data.data)} bytes)."
