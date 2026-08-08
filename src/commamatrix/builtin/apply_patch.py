# builtin/apply_patch.py

"""Text-file patch tool for coding agents.

The patch syntax intentionally follows the familiar Begin/End Patch format,
while the implementation keeps workspace policy, text format preservation and
per-operation results local to CommaMatrix.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ..components.config import ConfigField
from ..components.hook import BeforeToolCallCtx
from ..components.instruction import InstructionCtx, instruction
from ..components.tool import tool
from ..utils import (
    PathResolutionError,
    TextFileFormat,
    allow_absolute_paths,
    read_text_file,
    resolve_path,
    write_text_file,
)


class PatchError(Exception):
    """Raised for malformed patches or unusable patch operations."""


class PatchOperationError(PatchError):
    def __init__(self, operation_index: int, message: str) -> None:
        super().__init__(message)
        self.operation_index = operation_index


@dataclass(slots=True)
class Hunk:
    context_lines: list[str] = field(default_factory=list)
    lines: list[tuple[str, str]] = field(default_factory=list)
    end_of_file: bool = False


@dataclass(slots=True)
class FileOp:
    action: Literal["add", "update", "delete"]
    path: str
    move_to: str | None = None
    content: str | None = None
    hunks: list[Hunk] = field(default_factory=list)


@dataclass(slots=True)
class PatchOperationResult:
    path: str
    action: str
    status: Literal["applied", "not applied", "failed", "would apply"]
    message: str = ""
    move_to: str | None = None

    def render(self) -> str:
        location = self.path
        if self.move_to:
            location += f" -> {self.move_to}"
        suffix = f": {self.message}" if self.message else ""
        return f"{self.status.upper()}: {location}{suffix}"


@dataclass(slots=True)
class PatchResult:
    operations: list[PatchOperationResult]
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None and all(
            operation.status in {"applied", "would apply"}
            for operation in self.operations
        )

    def render(self) -> str:
        lines = [operation.render() for operation in self.operations]
        if self.error:
            lines.append(f"PATCH ERROR: {self.error}")
        return "\n".join(lines)


@dataclass(slots=True)
class _PlannedOperation:
    operation: FileOp
    source: Path
    destination: Path | None = None
    original_digest: str | None = None
    original_mode: int | None = None
    content: str | None = None
    file_format: TextFileFormat | None = None


max_patch_chars = ConfigField[int](
    name="max_patch_chars",
    default=2_000_000,
    description="Maximum text size accepted by the apply_patch tool.",
)


@instruction(priority=-120)
def apply_patch_guidance(_ctx: InstructionCtx) -> str:
    """Recommend the patch tool for code edits and multi-file changes."""
    return """
# Code editing
When editing code, prefer the `code_apply_patch` tool (named `tools.code.apply_patch` in CodeAct) over other I/O methods such as shell redirection or direct file writes. This is especially important when a change affects multiple files: combine related operations into one patch when practical, keep the patch focused, and inspect the affected code before applying it.
"""


# --------------------------------------------------------------------------
# Patch parsing
# --------------------------------------------------------------------------


def parse_patch(patch_text: str) -> list[FileOp]:
    lines = patch_text.splitlines()

    if lines and lines[0].strip() == "*** Begin Patch":
        lines = lines[1:]
    else:
        raise PatchError("patch must start with '*** Begin Patch'")

    if lines and lines[-1].strip() == "*** End Patch":
        lines = lines[:-1]
    else:
        raise PatchError("patch must end with '*** End Patch'")

    operations: list[FileOp] = []
    index = 0
    total = len(lines)

    def is_new_section(_line: str) -> bool:
        return _line.startswith(("*** Add File: ", "*** Update File: ", "*** Delete File: "))

    while index < total:
        line = lines[index]

        if line.startswith("*** Add File: "):
            path = line[len("*** Add File: "):].strip()
            if not path:
                raise PatchError("Add File path must not be empty")
            index += 1
            content_lines: list[str] = []
            while index < total and not is_new_section(lines[index]):
                content_line = lines[index]
                if content_line.startswith("+"):
                    content_lines.append(content_line[1:])
                elif content_line.strip() == "":
                    # Keep the parser forgiving for hand-written patches.
                    content_lines.append("")
                else:
                    raise PatchError(
                        f"invalid line in 'Add File: {path}': {content_line!r}"
                    )
                index += 1
            content = "\n".join(content_lines)
            if content_lines:
                content += "\n"
            operations.append(FileOp(action="add", path=path, content=content))
            continue

        if line.startswith("*** Delete File: "):
            path = line[len("*** Delete File: "):].strip()
            if not path:
                raise PatchError("Delete File path must not be empty")
            index += 1
            operations.append(FileOp(action="delete", path=path))
            continue

        if line.startswith("*** Update File: "):
            path = line[len("*** Update File: "):].strip()
            if not path:
                raise PatchError("Update File path must not be empty")
            index += 1
            move_to: str | None = None
            if index < total and lines[index].startswith("*** Move to: "):
                move_to = lines[index][len("*** Move to: "):].strip()
                if not move_to:
                    raise PatchError(f"Move to path for {path!r} must not be empty")
                index += 1

            hunks: list[Hunk] = []
            current: Hunk | None = None
            while index < total and not is_new_section(lines[index]):
                hunk_line = lines[index]
                if hunk_line.startswith("@@"):
                    if current is not None:
                        hunks.append(current)
                    current = Hunk()
                    context = hunk_line[2:].strip()
                    if context:
                        current.context_lines.append(context)
                elif hunk_line.strip() == "*** End of File":
                    if current is None:
                        current = Hunk()
                    current.end_of_file = True
                else:
                    if current is None:
                        current = Hunk()
                    if hunk_line.startswith("+"):
                        current.lines.append(("+", hunk_line[1:]))
                    elif hunk_line.startswith("-"):
                        current.lines.append(("-", hunk_line[1:]))
                    elif hunk_line.startswith(" "):
                        current.lines.append((" ", hunk_line[1:]))
                    elif hunk_line.strip() == "":
                        current.lines.append((" ", ""))
                    else:
                        raise PatchError(
                            f"invalid line in 'Update File: {path}': {hunk_line!r}"
                        )
                index += 1

            if current is not None:
                hunks.append(current)
            if not hunks:
                raise PatchError(f"Update File {path!r} has no hunks")
            operations.append(
                FileOp(action="update", path=path, move_to=move_to, hunks=hunks)
            )
            continue

        if line.strip() == "":
            index += 1
            continue
        raise PatchError(f"unexpected line in patch: {line!r}")

    if not operations:
        raise PatchError("patch contains no file operations")
    return operations


# --------------------------------------------------------------------------
# Applying text hunks
# --------------------------------------------------------------------------


def _find_hunk_position(file_lines: list[str], before: list[str], start: int, context_hint: list[str] | None = None) -> int:
    """Find one exact hunk match, with trailing-whitespace fallback."""
    if not before:
        return min(start, len(file_lines))

    line_count = len(file_lines)
    before_count = len(before)
    exact = [
        index
        for index in range(start, line_count - before_count + 1)
        if file_lines[index: index + before_count] == before
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise PatchError(_ambiguous_hunk_message(before, context_hint))

    before_rstrip = [line.rstrip() for line in before]
    fallback = [
        index
        for index in range(start, line_count - before_count + 1)
        if [line.rstrip() for line in file_lines[index: index + before_count]] == before_rstrip
    ]
    if len(fallback) == 1:
        return fallback[0]
    if len(fallback) > 1:
        raise PatchError(_ambiguous_hunk_message(before, context_hint))

    hint = ""
    if context_hint:
        hint = f"\nHunk hint: {context_hint[0]}"
    snippet = "\n".join(before[:3])
    raise PatchError(
        "could not find hunk context; the file does not match the expected "
        f"content.\nExpected fragment:\n{snippet}{hint}"
    )


def _ambiguous_hunk_message(before: list[str], context_hint: list[str] | None) -> str:
    hint = f" Hunk hint: {context_hint[0]}" if context_hint else ""
    snippet = "\n".join(before[:3])
    return (
        "hunk context is ambiguous; add more context to identify one location."
        f"{hint}\nCandidate fragment:\n{snippet}"
    )


def _apply_hunk(file_lines: list[str], hunk: Hunk, search_from: int) -> tuple[list[str], int]:
    def apply_lines(lines: list[tuple[str, str]]) -> tuple[list[str], int]:
        before = [text for operation, text in lines if operation in {" ", "-"}]
        after = [text for operation, text in lines if operation in {" ", "+"}]

        if hunk.end_of_file and not before:
            position = len(file_lines)
        else:
            position = _find_hunk_position(
                file_lines,
                before,
                search_from,
                context_hint=hunk.context_lines,
            )
        if hunk.end_of_file and position + len(before) != len(file_lines):
            raise PatchError("hunk marked '*** End of File' does not reach the file end")

        new_lines = file_lines[:position] + after + file_lines[position + len(before):]
        return new_lines, position + len(after)

    try:
        return apply_lines(hunk.lines)
    except PatchError as exc:
        if not str(exc).startswith("could not find hunk context;"):
            raise
        mismatch = exc

    # Tolerate an extra indentation space on context lines from CodeAct output.
    relaxed_lines = [
        (
            operation,
            text[1:] if operation == " " and text.startswith(" ") else text,
        )
        for operation, text in hunk.lines
    ]
    if relaxed_lines == hunk.lines:
        raise mismatch
    return apply_lines(relaxed_lines)


def apply_update(original_text: str, hunks: list[Hunk]) -> str:
    trailing_newline = original_text.endswith("\n")
    file_lines = original_text.split("\n")
    if trailing_newline and file_lines and file_lines[-1] == "":
        file_lines.pop()

    search_from = 0
    for hunk in hunks:
        file_lines, search_from = _apply_hunk(file_lines, hunk, search_from)

    result = "\n".join(file_lines)
    if trailing_newline or (hunks and hunks[-1].end_of_file):
        result += "\n"
    return result


# --------------------------------------------------------------------------
# Planning and committing operations
# --------------------------------------------------------------------------


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _operation_result(operation: FileOp, status: Literal["applied", "not applied", "failed", "would apply"], message: str = "") -> PatchOperationResult:
    return PatchOperationResult(
        path=operation.path,
        action=operation.action,
        status=status,
        message=message,
        move_to=operation.move_to,
    )


def _not_applied_results(operations: list[FileOp], failed_index: int, message: str) -> list[PatchOperationResult]:
    results: list[PatchOperationResult] = []
    for index, operation in enumerate(operations):
        if index == failed_index:
            results.append(_operation_result(operation, "failed", message))
        else:
            results.append(
                _operation_result(
                    operation,
                    "not applied",
                    "not applied because patch validation failed",
                )
            )
    return results


def _plan_operations(operations: list[FileOp], *, root: Path, allow_absolute: bool) -> list[_PlannedOperation]:
    planned: list[_PlannedOperation] = []
    touched: dict[Path, str] = {}

    for operation_index, operation in enumerate(operations):
        try:
            source = resolve_path(
                operation.path,
                root=root,
                allow_absolute=allow_absolute,
            )
            destination = None
            if operation.move_to:
                destination = resolve_path(
                    operation.move_to,
                    root=root,
                    allow_absolute=allow_absolute,
                )
                if destination == source:
                    raise PatchError("Move to destination must differ from source")

            paths = [source] + ([destination] if destination is not None else [])
            for path in paths:
                assert path is not None
                if path in touched:
                    raise PatchError(
                        f"path {path} is used by multiple patch operations: "
                        f"{touched[path]} and {operation.path}"
                    )
            touched[source] = operation.path
            if destination is not None:
                touched[destination] = operation.move_to or operation.path

            if operation.action == "add":
                if _exists(source):
                    raise PatchError(f"file already exists: {operation.path}")
                planned.append(
                    _PlannedOperation(
                        operation=operation,
                        source=source,
                        content=operation.content or "",
                        file_format=TextFileFormat(),
                    )
                )
                continue

            if not _exists(source):
                raise PatchError(f"file not found: {operation.path}")
            if not source.is_file():
                raise PatchError(f"path is not a regular file: {operation.path}")

            if operation.action == "delete":
                planned.append(
                    _PlannedOperation(
                        operation=operation,
                        source=source,
                        original_digest=_digest(source),
                        original_mode=source.stat().st_mode,
                    )
                )
                continue

            if operation.action == "update":
                snapshot = read_text_file(source)
                updated = apply_update(snapshot.content, operation.hunks)
                if destination is not None and _exists(destination):
                    raise PatchError(f"move destination already exists: {operation.move_to}")
                planned.append(
                    _PlannedOperation(
                        operation=operation,
                        source=source,
                        destination=destination,
                        original_digest=snapshot.digest,
                        original_mode=snapshot.mode,
                        content=updated,
                        file_format=snapshot.file_format,
                    )
                )
                continue

            raise PatchError(f"unknown patch action: {operation.action}")
        except PathResolutionError as exc:
            raise PatchOperationError(operation_index, str(exc)) from exc
        except (OSError, UnicodeError) as exc:
            raise PatchOperationError(
                operation_index,
                f"could not inspect {operation.path}: {exc}",
            ) from exc
        except PatchError as exc:
            raise PatchOperationError(operation_index, str(exc)) from exc

    return planned


def _verify_original(planned: _PlannedOperation) -> None:
    if planned.original_digest is None:
        if _exists(planned.source):
            raise PatchError(f"file appeared while patch was prepared: {planned.operation.path}")
        return
    if not _exists(planned.source):
        raise PatchError(f"file disappeared while patch was prepared: {planned.operation.path}")
    if _digest(planned.source) != planned.original_digest:
        raise PatchError(f"file changed while patch was prepared: {planned.operation.path}")


def apply_patch_text(patch_text: str, *, root: str | Path | None = None, allow_absolute: bool = False, dry_run: bool = False) -> PatchResult:
    """Apply a patch and return one result record per file operation."""
    operations = parse_patch(patch_text)
    root_path = Path(root or Path.cwd()).resolve()

    try:
        planned = _plan_operations(
            operations,
            root=root_path,
            allow_absolute=allow_absolute,
        )
    except PatchError as exc:
        error = str(exc)
        failed_index = (
            exc.operation_index if isinstance(exc, PatchOperationError) else 0
        )
        return PatchResult(
            operations=_not_applied_results(operations, failed_index, error),
            error=error,
        )

    if dry_run:
        return PatchResult(
            operations=[
                _operation_result(operation.operation, "would apply")
                for operation in planned
            ]
        )

    results: list[PatchOperationResult] = []
    for index, item in enumerate(planned):
        operation = item.operation
        try:
            _verify_original(item)
            if operation.action == "add":
                write_text_file(
                    item.source,
                    item.content or "",
                    file_format=item.file_format,
                )
            elif operation.action == "delete":
                item.source.unlink()
            elif operation.action == "update":
                if item.destination is not None:
                    if _exists(item.destination):
                        raise PatchError(
                            f"move destination appeared while patch was prepared: "
                            f"{operation.move_to}"
                        )
                    write_text_file(
                        item.destination,
                        item.content or "",
                        file_format=item.file_format,
                        mode=item.original_mode,
                    )
                    item.source.unlink()
                else:
                    write_text_file(
                        item.source,
                        item.content or "",
                        file_format=item.file_format,
                        mode=item.original_mode,
                    )
            else:
                raise PatchError(f"unknown patch action: {operation.action}")
            results.append(_operation_result(operation, "applied"))
        except (PatchError, OSError, UnicodeError) as exc:
            message = str(exc)
            results.append(_operation_result(operation, "failed", message))
            for remaining in planned[index + 1:]:
                results.append(
                    _operation_result(
                        remaining.operation,
                        "not applied",
                        "not applied because an earlier operation failed",
                    )
                )
            return PatchResult(operations=results, error=message)

    return PatchResult(operations=results)


@tool(alias="code", filesystem=True)
async def apply_patch(patch: str, *, ctx: BeforeToolCallCtx) -> str:
    """Apply a text patch to files under the agent's current working directory."""
    max_chars = ctx.run.agent.config.get(max_patch_chars)
    if len(patch) > max_chars:
        return f"PATCH ERROR: patch is too large; maximum size is {max_chars} characters"

    try:
        async with ctx.run.agent._filesystem_lock:
            result = await asyncio.to_thread(
                apply_patch_text,
                patch,
                root=Path.cwd(),
                allow_absolute=ctx.run.agent.config.get(allow_absolute_paths),
            )
    except PatchError as exc:
        return f"PATCH ERROR: {exc}"
    return result.render()


__all__ = [
    "FileOp",
    "Hunk",
    "PatchError",
    "PatchOperationResult",
    "PatchResult",
    "apply_patch",
    "apply_patch_guidance",
    "apply_patch_text",
    "apply_update",
    "max_patch_chars",
    "parse_patch",
]
