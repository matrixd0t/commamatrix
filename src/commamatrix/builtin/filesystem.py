# builtin/filesystem.py

"""Shared filesystem context for tools that can inspect or change files."""

from __future__ import annotations

import platform
import sys
from pathlib import Path

from ..components.instruction import InstructionCtx, instruction
from ..utils import allow_absolute_paths


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
    ]
    return "\n".join(lines)


__all__ = ["filesystem_context"]
