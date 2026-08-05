# builtin/self_extension/tools.py

"""Self-modification tools - manage agent extensions at runtime."""

from __future__ import annotations

import asyncio
import os
import platform
import sys
from pathlib import Path
from typing import Literal

from ...components.config import ConfigField
from ...components.hook import BeforeToolCallCtx
from ...components.instruction import InstructionCtx, instruction
from ...components.tool import tool

_GUIDE_PATH = str(Path(__file__).parent / "readme.md")

guide_path = ConfigField[str](
    name="self_extension.guide_path",
    default=_GUIDE_PATH,
    description="Path to the extension authoring guide file.",
)


@instruction(priority=-200)
def self_extension_when_and_why(ctx: InstructionCtx) -> str:
    """Explain how to persist reusable behavior as an extension."""
    return '''
# Self-extension
Use this when:
- User wants stuff you can't or don't know how to do
- User suggests some behaviour / capability to be reused / persisted for future
- !!!Do NOT refuse to do stuff until 100% sure you can't make an extension to do it!!!
How to use:
- Suggest to write an extension, if user accepts, proceed to following
- Call readme
- Steps: layout -> abstractions and contracts -> logic -> implementation
- Example usage: make @instruction to save a note about specific user, or a @tool for new action / capability
- Use manage_extension to activate new capabilities
'''


@tool(alias="self_extension", filesystem=True)
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


@tool(alias="self_extension", filesystem=True)
async def read_guide(ctx: BeforeToolCallCtx) -> str:
    """Returns self-modification guide together with runtime and installation information."""
    path = ctx.run.agent.config.get(guide_path)
    version = sys.version_info
    environment = (
        f"CommaMatrix path: {Path(__file__).resolve().parents[2]}\n"
        f"Platform: {platform.system()} {platform.release()} | "
        f"Python {version.major}.{version.minor}.{version.micro} | "
        f"CWD: {os.getcwd()}\n\n"
    )
    try:
        content = await asyncio.to_thread(Path(path).read_text, encoding="utf-8")
        return environment + content
    except FileNotFoundError:
        return environment + f"Guide file not found: {path}"
