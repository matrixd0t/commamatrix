# builtin/self_modif/tools.py

"""Self-modification tools - manage agent extensions at runtime."""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

import aiofiles

from ...components.config import ConfigField
from ...components.hook import BeforeRunCtx, BeforeToolCallCtx, before_run
from ...components.tool import tool

_GUIDE_PATH = str(Path(__file__).parent / "guide.md")

guide_path = ConfigField[str](
    name="self_modif.guide_path",
    default=_GUIDE_PATH,
    description="Path to the extension authoring guide file.",
)


def _ensure_plugins_directory() -> None:
    Path.cwd().joinpath("commamatrix_plugins").mkdir(parents=True, exist_ok=True)


@before_run
def ensure_plugins_directory(_ctx: BeforeRunCtx) -> None:
    """Ensure the standard workspace for self-written extensions exists."""
    _ensure_plugins_directory()


@tool(alias="self_modif")
async def add_extension(module_or_path: str, *, ctx: BeforeToolCallCtx) -> str:
    """Activate an import name or filesystem path as an agent extension."""
    if not module_or_path:
        return "Error: an extension module or path is required."
    try:
        handled = await ctx.run.agent.add_extensions(module_or_path)
    except Exception as exc:
        return f"Failed to add extension '{module_or_path}': {exc}"
    if not handled:
        return f"Failed to add extension '{module_or_path}'."
    return f"Extension is active: {handled[0]}"


@tool(alias="self_modif")
async def remove_extension(module_or_path: str, *, ctx: BeforeToolCallCtx) -> str:
    """Deactivate an extension by import name or filesystem path."""
    if not module_or_path:
        return "Error: an extension module or path is required."
    try:
        handled = await ctx.run.agent.remove_extensions(module_or_path)
    except Exception as exc:
        return f"Failed to remove extension '{module_or_path}': {exc}"
    if not handled:
        return f"Extension '{module_or_path}' is not active."
    return f"Extension removed: {handled[0]}"


@tool(alias="self_modif")
async def reload_extension(module_or_path: str, *, ctx: BeforeToolCallCtx) -> str:
    """Reload an extension by import name or filesystem path after editing it."""
    if not module_or_path:
        return "Error: an extension module or path is required."
    try:
        handled = await ctx.run.agent.reload_extensions(module_or_path)
    except Exception as exc:
        return f"Failed to reload extension '{module_or_path}': {exc}"
    if not handled:
        return f"Failed to reload extension '{module_or_path}'."
    return f"Extension reloaded: {handled[0]}"


@tool(alias="self_modif")
async def list_extensions(*, ctx: BeforeToolCallCtx) -> str:
    """List the extension roots currently active for this agent."""
    scope = ctx.run.agent.extension_scope
    roots = [
        name
        for name in scope
        if not any(name != other and name.startswith(other + ".") for other in scope)
    ]
    if not roots:
        return "No active extensions."
    return "Active extensions:\n" + "\n".join(f"- {name}" for name in roots)


@tool(alias="self_modif")
async def read_guide(ctx: BeforeToolCallCtx) -> str:
    """Return the extension guide together with runtime and installation information."""
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
