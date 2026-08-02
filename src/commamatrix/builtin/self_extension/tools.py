# builtin/self_extension/tools.py

"""Self-modification tools - manage agent extensions at runtime."""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Literal

import aiofiles

from ...components.config import ConfigField
from ...components.hook import BeforeRunCtx, BeforeToolCallCtx, before_run
from ...components.instruction import InstructionCtx, instruction
from ...components.tool import tool
from ...core.agent.agent import plugins_dir
from ...utils import commamatrix_dir

_GUIDE_PATH = str(Path(__file__).parent / "guide.md")

guide_path = ConfigField[str](
    name="self_extension.guide_path",
    default=_GUIDE_PATH,
    description="Path to the extension authoring guide file.",
)


def _ensure_plugins_dir(ctx: BeforeRunCtx) -> None:
    config = ctx.run.agent.config
    root = (
        Path.cwd()
        / config.get(commamatrix_dir)
        / config.get(plugins_dir)
    )
    root.mkdir(parents=True, exist_ok=True)


@before_run
def ensure_plugins_dir(ctx: BeforeRunCtx) -> None:
    """Ensure the standard workspace for self-written extensions exists."""
    _ensure_plugins_dir(ctx)


@instruction(priority=-200)
def self_modification_when_and_why(ctx: InstructionCtx) -> str:
    """Explain how to persist reusable behavior as an extension."""
    return '''
# Self-modification: when and why
If some behavior should be reused in future runs, persist it with self-modification instead of using it only in the current task.
- For a permanent response rule, workflow rule, or piece of context, write an @instruction that returns the text to include in the system prompt.
- For a reusable action or capability, write a @tool.
- Use manage_extension after changing the current agent's add-ons. Do not persist one-off task details.
'''


@tool(alias="self_extension")
async def manage(module_or_path: str, action: Literal["add", "remove", "reload"], *, ctx: BeforeToolCallCtx) -> str:
    """Add, remove, or reload an extension by import name or filesystem path."""
    if not module_or_path:
        return "Error: an extension module or path is required."
    method = {
        "add": ctx.run.agent.add_extensions,
        "remove": ctx.run.agent.remove_extensions,
        "reload": ctx.run.agent.reload_extensions,
    }[action]
    try:
        handled = await method(module_or_path)
    except Exception as exc:
        return f"Failed to {action} extension '{module_or_path}': {exc}"
    if not handled:
        return f"Failed to {action} extension '{module_or_path}'."
    verb = {"add": "active", "remove": "removed", "reload": "reloaded"}[action]
    return f"Extension {verb}: {handled[0]}\n"


@tool(alias="self_extension")
async def list_all(*, ctx: BeforeToolCallCtx) -> str:
    """List the extension roots currently active for this agent."""
    scope = ctx.run.agent.extension_scope
    roots = [name for name in scope if not any(name != other and name.startswith(other + ".") for other in scope)]
    if not roots:
        return "No active extensions."
    return "Active extension modules:\n" + "\n".join(f"- {name}" for name in roots)


@tool(alias="self_extension")
async def guide(ctx: BeforeToolCallCtx) -> str:
    """Returns self-modification (extension) guide together with runtime and installation information."""
    path = ctx.run.agent.config.get(guide_path)
    version = sys.version_info
    environment = (
        f"CommaMatrix path: {Path(__file__).resolve().parents[2]}\n"
        f"Platform: {platform.system()} {platform.release()} | "
        f"Python {version.major}.{version.minor}.{version.micro} | "
        f"CWD: {os.getcwd()}\n\n"
    )
    try:
        async with aiofiles.open(path, encoding="utf-8") as f:
            return environment + await f.read()
    except FileNotFoundError:
        return environment + f"Guide file not found: {path}"
