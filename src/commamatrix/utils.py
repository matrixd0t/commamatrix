# utils.py

from __future__ import annotations

import asyncio
import hashlib
import inspect
import os
import stat
import tempfile
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .components.config import ConfigField


__all__ = [
    "framework_prefix",
    "commamatrix_dir",
    "allow_absolute_paths",
    "PathResolutionError",
    "TextFileFormat",
    "TextFileSnapshot",
    "resolve_path",
    "read_text_file",
    "write_bytes_file",
    "write_text_file",
    "read_text_file_async",
    "write_bytes_file_async",
    "write_text_file_async",
    "await_if_needed",
    "to_jsonable",
]


def framework_prefix() -> str:
    """Return the import prefix used by the framework package."""
    parts = __name__.split(".")
    return ".".join(parts[: parts.index("commamatrix") + 1])


FP = framework_prefix()

commamatrix_dir = ConfigField[str](
    name="commamatrix_dir",
    default=".commamatrix",
    description="Root directory for all Commamatrix data",
)

allow_absolute_paths = ConfigField[bool](
    name="allow_absolute_paths",
    default=True,
    description="Allow agent to access absolute paths outside the CWD.",
)


class PathResolutionError(ValueError):
    """Raised when a user path violates the active filesystem policy."""


class TextFileFormat:
    """Encoding and newline style used when serializing a text file."""

    __slots__ = ("encoding", "newline")

    def __init__(self, encoding: str = "utf-8", newline: str = "\n") -> None:
        self.encoding = encoding
        self.newline = newline

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, TextFileFormat)
            and self.encoding == other.encoding
            and self.newline == other.newline
        )

    def __repr__(self) -> str:
        return f"TextFileFormat(encoding={self.encoding!r}, newline={self.newline!r})"


class TextFileSnapshot:
    """Text content together with the original bytes and file metadata."""

    __slots__ = ("content", "file_format", "digest", "mode")

    def __init__(self, content: str, file_format: TextFileFormat, digest: str, mode: int) -> None:
        self.content = content
        self.file_format = file_format
        self.digest = digest
        self.mode = mode


def resolve_path(value: str | os.PathLike[str], *, root: str | os.PathLike[str] | None = None, allow_absolute: bool = False) -> Path:
    """Resolve a user path under ``root`` unless absolute paths are allowed.

    Relative paths are interpreted from ``root`` and resolved through symlinks
    before the workspace boundary is checked. This policy is shared by code
    tools and general file-writing tools.
    """
    raw_value = os.fspath(value)
    if not isinstance(raw_value, str):
        raise PathResolutionError("bytes paths are not supported")
    raw = raw_value.strip()
    if not raw:
        raise PathResolutionError("path must not be empty")

    root_path = (Path(root) if root is not None else Path.cwd()).resolve()
    candidate = Path(raw)
    if candidate.drive and not candidate.is_absolute():
        raise PathResolutionError(f"drive-relative paths are not supported: {raw!r}")

    if candidate.is_absolute():
        if not allow_absolute:
            raise PathResolutionError(
                f"absolute paths are disabled: {raw!r}; use a relative path"
            )
        resolved = candidate.resolve(strict=False)
    else:
        resolved = (root_path / candidate).resolve(strict=False)

    if not allow_absolute and not resolved.is_relative_to(root_path):
        raise PathResolutionError(f"path escapes the workspace: {raw!r}")
    return resolved


def _text_encoding(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        return "utf-32"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    return "utf-8"


def _newline_style(content: str) -> str:
    if "\r\n" in content:
        return "\r\n"
    if "\r" in content:
        return "\r"
    return "\n"


def _normalize_newlines(content: str) -> str:
    return content.replace("\r\n", "\n").replace("\r", "\n")


def read_text_file(path: Path) -> TextFileSnapshot:
    """Read a UTF text file while retaining format and replacement metadata."""
    raw = path.read_bytes()
    encoding = _text_encoding(raw)
    decoded = raw.decode(encoding)
    file_format = TextFileFormat(
        encoding=encoding,
        newline=_newline_style(decoded),
    )
    mode = stat.S_IMODE(path.stat().st_mode)
    return TextFileSnapshot(
        content=_normalize_newlines(decoded),
        file_format=file_format,
        digest=hashlib.sha256(raw).hexdigest(),
        mode=mode,
    )


def _encode_text(content: str, file_format: TextFileFormat) -> bytes:
    normalized = _normalize_newlines(content)
    serialized = normalized.replace("\n", file_format.newline)
    return serialized.encode(file_format.encoding)


def write_bytes_file(path: Path, data: bytes, *, mode: int | None = None) -> None:
    """Atomically replace a file with bytes, preserving its mode if possible."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode is None and path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def write_text_file(path: Path, content: str, *, file_format: TextFileFormat | None = None, mode: int | None = None) -> None:
    """Atomically write UTF text while preserving existing file formatting."""
    if file_format is None and path.exists():
        snapshot = read_text_file(path)
        file_format = snapshot.file_format
        if mode is None:
            mode = snapshot.mode
    file_format = file_format or TextFileFormat()
    write_bytes_file(path, _encode_text(content, file_format), mode=mode)


async def read_text_file_async(path: Path) -> TextFileSnapshot:
    return await asyncio.to_thread(read_text_file, path)


async def write_bytes_file_async(path: Path, data: bytes, *,  mode: int | None = None) -> None:
    await asyncio.to_thread(write_bytes_file, path, data, mode=mode)


async def write_text_file_async(path: Path, content: str, *, file_format: TextFileFormat | None = None, mode: int | None = None) -> None:
    await asyncio.to_thread(write_text_file, path, content, file_format=file_format, mode=mode)


async def await_if_needed(result: Any) -> Any:
    if inspect.isawaitable(result):
        return await result
    return result


def to_jsonable(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {str(key): to_jsonable(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(value) for value in obj]
    if hasattr(obj, "model_dump"):
        return to_jsonable(obj.model_dump(mode="json"))
    if is_dataclass(obj) and not isinstance(obj, type):
        return {
            field.name: to_jsonable(getattr(obj, field.name))
            for field in fields(obj)
        }
    if hasattr(obj, "__dict__"):
        return {
            key: to_jsonable(value)
            for key, value in obj.__dict__.items()
            if not key.startswith("_")
        }
    return str(obj)
