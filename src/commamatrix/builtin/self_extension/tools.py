# builtin/self_extension/tools.py

"""Self-modification tools - manage agent extensions at runtime."""

from __future__ import annotations

import asyncio
import os
import platform
import sys
from pathlib import Path
from typing import Literal

from ...components.hook import BeforeToolCallCtx
from ...components.instruction import InstructionCtx, instruction
from ...components.tool import tool

_GUIDES_PATH = (Path(__file__).parent / "guides").resolve()


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
- Call self_extension.read_guide() without sections for the general guide
- Call self_extension.read_guide(sections=[...]) for the relevant detailed guides
- Steps: layout -> abstractions and contracts -> logic -> implementation
- Example usage: make @instruction to save a note about specific user, or a @tool for new action / capability
- Use self_extension.manage to activate new capabilities
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
async def read_guide(sections: list[str] = []) -> str:
    """Read the general extension guide or selected detailed guide sections.

    ``sections`` defaults to an empty list.
    Call this tool once without sections first to read ``main.md``.
    Then call it again with one or more section names when the implementation requires more detail.
    Detailed guides contain links to the relevant library source files.
    """
    version = sys.version_info
    environment = (
        f"CommaMatrix path: {Path(__file__).resolve().parents[2]}\n"
        f"Platform: {platform.system()} {platform.release()} | "
        f"Python {version.major}.{version.minor}.{version.micro} | "
        f"CWD: {os.getcwd()}\n\n"
    )
    paths: list[Path] = []
    for section in sections or ["main"]:
        filename = section if section.endswith(".md") else f"{section}.md"
        path = (_GUIDES_PATH / filename).resolve()
        if path.parent != _GUIDES_PATH or path.suffix != ".md":
            return environment + f"Invalid guide section: {section}"
        paths.append(path)

    try:
        content = "\n\n".join(
            await asyncio.gather(*(
                asyncio.to_thread(path.read_text, encoding="utf-8") for path in paths
            ))
        )
        return environment + content
    except FileNotFoundError as exc:
        return environment + f"Guide section not found: {exc.filename}"
