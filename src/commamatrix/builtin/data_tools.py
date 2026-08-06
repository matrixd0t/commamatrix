# builtin/data_tools.py

from __future__ import annotations

import asyncio
from json import dumps
from mimetypes import guess_type
from pathlib import Path
from urllib.parse import unquote, urlparse

from httpx2 import HTTPError

from ..components.config import ConfigField
from ..components.dialog import DialogItem, DialogItemType, DialogRole
from ..components.file_storage import (
    DataType,
    FileData,
    ext_to_mime,
    file_to_context,
    read_file,
)
from ..components.hook import BeforeToolCallCtx
from ..components.tool import tool
from ..utils import (
    allow_absolute_paths,
    resolve_path,
    write_bytes_file_async,
    write_text_file_async,
)
from .web_utils.security import validate_url

read_timeout = ConfigField[int](
    name="read_timeout",
    default=30,
    description="Timeout in seconds for a single HTTP request during read.",
)
read_max_response_bytes = ConfigField[int](
    name="read_max_response_bytes",
    default=5_242_880,
    description="Maximum byte count for a downloaded URL during read.",
)
read_max_redirects = ConfigField[int](
    name="read_max_redirects",
    default=5,
    description="Maximum number of HTTP redirects to follow during read.",
)


def _extension(ext: str) -> str:
    value = ext.strip()
    if not value:
        return ""
    return value if value.startswith(".") else f".{value}"


def _is_http_url(value: str) -> bool:
    return urlparse(value).scheme in {"http", "https"}


def _is_local_path_ref(value: str) -> bool:
    path = Path(value)
    return path.is_absolute() or path.parent != Path(".") or any(
        part in {".", ".."} for part in path.parts
    )


def _make_file_name(dest: str, ext: str) -> str:
    parsed = urlparse(dest)
    name = Path(parsed.path if parsed.scheme else dest).name
    extension = _extension(ext)
    if not name:
        name = "file"
    if extension and not Path(name).suffix:
        name += extension
    return name


def _queue_file_input(file_data: FileData, ref: str, ctx: BeforeToolCallCtx) -> None:
    item_type = (
        DialogItemType.IMAGE_INPUT
        if file_data.data_type == DataType.IMAGE
        else DialogItemType.FILE_INPUT
    )
    field_name = file_data.data_type.value
    extension = Path(file_data.name).suffix.lstrip(".")
    ctx.follow_up_items.append(
        DialogItem(
            content=dumps(
                {
                    field_name: {
                        "ref": ref,
                        "ext": extension,
                        "name": file_data.name,
                        "mime_type": file_data.mime_type,
                    }
                },
                ensure_ascii=False,
            ),
            item_type=item_type,
            role=DialogRole.USER,
            user=ctx.run.user,
            origin=ctx.run.origin,
            meta={"is_tool_call_result": True},
        )
    )


def _clean_mime_type(value: str | None) -> str | None:
    if not value:
        return None
    mime_type = value.split(";", 1)[0].strip().lower()
    return mime_type or None


def _content_type(mime_type: str) -> DataType:
    if mime_type.startswith("image/"):
        return DataType.IMAGE
    if (
        mime_type.startswith("text/")
        or mime_type in {"application/json", "application/javascript", "application/yaml", "application/x-yaml"}
        or mime_type.endswith(("+json", "+xml"))
    ):
        return DataType.TEXT
    return DataType.FILE


def _truncate_text(content: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(content) <= max_chars:
        return content
    marker = "\n\n[truncated]"
    if max_chars <= len(marker):
        return content[:max_chars]
    return content[: max_chars - len(marker)] + marker


def _extract_content(html: str) -> str:
    from trafilatura import extract
    return extract(html, output_format="markdown", include_links=True, include_tables=True) or ""


async def _fetch_url(ref: str, ctx: BeforeToolCallCtx) -> tuple[FileData, str] | str:
    try:
        validate_url(ref)
    except ValueError as exc:
        return f"Error: {exc}"

    config = ctx.run.agent.config
    current_url = ref
    response = None
    max_redirects = config.get(read_max_redirects)
    for _ in range(max_redirects + 1):
        try:
            response = await ctx.run.agent.http_client.get(
                current_url,
                timeout=config.get(read_timeout),
                follow_redirects=False,
            )
        except Exception as exc:
            return f"Error: HTTP request failed: {exc}"

        if response.is_redirect:
            location = response.headers.get("location")
            if not location:
                return "Error: redirect without Location header."
            next_url = str(response.url.join(location))
            try:
                validate_url(next_url)
            except ValueError as exc:
                return f"Error: redirect target blocked - {exc}"
            current_url = next_url
            continue
        break

    if response is None:
        return "Error: HTTP request failed."
    if response.is_redirect:
        return f"Error: too many redirects (max {max_redirects})"
    if response.status_code >= 400:
        return f"Error: HTTP {response.status_code}."

    max_bytes = config.get(read_max_response_bytes)
    content_length = response.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                return f"Error: response exceeds the configured size limit ({int(content_length)} > {max_bytes} bytes)"
        except ValueError:
            pass

    data = response.content
    if len(data) > max_bytes:
        return "Error: response exceeds the configured size limit."

    parsed = urlparse(current_url)
    name = unquote(Path(parsed.path).name) or current_url
    mime_type = _clean_mime_type(response.headers.get("content-type"))
    mime_type = mime_type or guess_type(name)[0] or ext_to_mime(Path(name).suffix)
    return FileData(
        data=data,
        name=name,
        mime_type=mime_type,
        data_type=_content_type(mime_type),
    ), current_url


@tool(alias="data", filesystem=True)
async def read(ref: str, max_chars: int = 4000, *, ctx: BeforeToolCallCtx) -> str:
    """
    Read a text, image, or file from a URL, path, or local storage.
    HTML pages will be converted to Markdown.
    Images and files are provided as user input after tool call (if supported; otherwise decoded as text).
    """
    ref = ref.strip()
    if _is_http_url(ref):
        fetched = await _fetch_url(ref, ctx)
        if isinstance(fetched, str):
            return fetched
        file_data, source_url = fetched
    else:
        local_path: Path | None = None
        if _is_local_path_ref(ref):
            try:
                local_path = resolve_path(ref, root=Path.cwd(), allow_absolute=ctx.run.agent.config.get(allow_absolute_paths))
            except ValueError as exc:
                return f"Error: {exc}"
        else:
            candidate = resolve_path(ref, root=Path.cwd(), allow_absolute=ctx.run.agent.config.get(allow_absolute_paths))
            if candidate.is_file():
                local_path = candidate

        file_data = await read_file(
            str(local_path) if local_path is not None else ref,
            file_storage=fs.active if (fs := ctx.run.agent.file_storage) else None,
            http_client=ctx.run.agent.http_client,
        )
        source_url = ref
        if file_data is None:
            return f"Error: file not found or unavailable: {ref}"

    content_type = DataType(file_data.data_type)
    if _is_http_url(ref) and file_data.mime_type in {"text/html", "application/xhtml+xml"}:
        try:
            markdown = await asyncio.to_thread(_extract_content, file_to_context(file_data).content)
        except Exception as exc:
            return f"Error: content extraction failed: {exc}"
        if not markdown:
            return "No readable content found at this URL."
        output = f"Source: {source_url}\n\n{markdown}"
        return _truncate_text(output, max_chars)

    if content_type is DataType.TEXT:
        return _truncate_text(file_to_context(file_data).content, max_chars)

    if ctx.run.llm is not None and content_type in ctx.run.llm.modalities.input:
        _queue_file_input(file_data, ref, ctx)
        return "OK"

    content = file_to_context(file_data, content_type=DataType.TEXT).content
    return _truncate_text(content, max_chars)


@tool(alias="data", filesystem=True)
async def write(content: str | bytes, dest: str | None = None, ext: str = "", *, ctx: BeforeToolCallCtx) -> str:
    """
    Write UTF-8 text or any bytes to a path, URL, or local storage.
    Do not specify dest if you just need to save a file, its file_id will be returned.
    """
    data = content.encode("utf-8") if isinstance(content, str) else content
    extension = _extension(ext)
    destination = dest.strip() if dest else ""
    mime_type = "text/plain" if isinstance(content, str) and not extension else ext_to_mime(extension)
    name = _make_file_name(destination, extension) if destination else f"file{extension}"

    if _is_http_url(destination):
        try:
            response = await ctx.run.agent.http_client.post(
                destination,
                files={"file": (name, data, mime_type)},
            )
            response.raise_for_status()
        except HTTPError as exc:
            return f"Error uploading file to {destination}: {exc}"
        return "OK"

    if destination:
        try:
            path = resolve_path(
                destination,
                root=Path.cwd(),
                allow_absolute=ctx.run.agent.config.get(allow_absolute_paths),
            )
            async with ctx.run.agent._filesystem_lock:
                if isinstance(content, str):
                    await write_text_file_async(path, content)
                else:
                    await write_bytes_file_async(path, data)
        except (OSError, UnicodeError, ValueError) as exc:
            return f"Error writing file to {destination}: {exc}"
        return "OK"

    try:
        return await ctx.run.agent.file_storage.save(
            data,
            ext=extension or None,
        )
    except Exception as exc:
        return f"Error saving file to FileStorage: {exc}"


__all__ = [
    "read_timeout",
    "read_max_response_bytes",
    "read_max_redirects",
    "read",
    "write",
]
