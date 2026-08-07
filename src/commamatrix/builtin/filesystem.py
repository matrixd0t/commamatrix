# builtin/filesystem.py

"""Shared filesystem context for tools that can inspect or change files."""

from __future__ import annotations

import asyncio
import platform
import sys
from pathlib import Path

from ..components.dialog import DialogItem, DialogItemType, DialogRole
from ..components.hook import BeforeLlmCallCtx, before_llm_call
from ..components.instruction import InstructionCtx, instruction
from ..utils import allow_absolute_paths

_AGENTS_FILE = "agents.md"


@instruction(priority=-180)
def filesystem_context(ctx: InstructionCtx) -> str | None:
    """Describe the process filesystem context when filesystem tools are active."""
    descriptors = ctx.run.agent.tool_manager.descriptors
    if not any(descriptor.meta.get("filesystem") for descriptor in descriptors):
        return None

    absolute_paths = ctx.run.agent.config.get(allow_absolute_paths)
    version = sys.version_info
    lines = [
        f"CWD: {Path.cwd().resolve()}",
        f"Platform: {platform.system()} {platform.release()} ({sys.platform})",
        f"Python: {version.major}.{version.minor}.{version.micro}",
        "Relative paths are resolved from CWD.",
        (
            "Absolute paths are allowed."
            if absolute_paths
            else "Absolute paths are forbidden."
        ),
        "Text-file tools preserve existing encoding, BOM, line-ending style, and file mode when updating a file.",
        "Use agents.md in CWD for durable notes, rules, instructions, and permanent behavior; and update it in case YOU think something should change.",
    ]
    return "\n".join(lines)


@before_llm_call(after="add_instructions")
async def add_agents_file(ctx: BeforeLlmCallCtx) -> None:
    """Add the workspace's durable agent rules as a separate system item."""
    path = Path.cwd() / _AGENTS_FILE
    try:
        content = await asyncio.to_thread(path.read_text, encoding="utf-8")
    except (OSError, UnicodeError):
        return
    content = content.strip()
    if not content:
        return

    system_index = next(
        (index for index, item in enumerate(ctx.dialog) if item.role is DialogRole.SYSTEM),
        None,
    )
    insert_at = system_index + 1 if system_index is not None else 0
    ctx.dialog.insert(
        insert_at,
        DialogItem(
            content=content,
            item_type=DialogItemType.INPUT,
            role=DialogRole.SYSTEM,
            origin=ctx.run.origin,
        ),
    )


__all__ = ["add_agents_file", "filesystem_context"]
