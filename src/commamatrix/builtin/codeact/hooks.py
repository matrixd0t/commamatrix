# builtin/codeact/hooks.py

"""AgentLifecycle hooks for CodeAct — global kill switch and tool filtering."""

from __future__ import annotations

from ...components.config import ConfigField
from ...components.hook import (
    BeforeLlmCallCtx,
    before_llm_call,
)
from ...components.tool import ToolDescriptor
from .rpc.server import is_codeact_internal
from .service import CodeActService

CODEACT_ENABLED_KEY = "codeact-enabled"
"""Key set on RunCtx.chain_state when CodeAct is active for the conversation."""

codeact_enabled = ConfigField[bool](
    name="codeact.enabled",
    default=True,
    description="Global CodeAct switch. When False, all CodeAct tools are hidden.",
)


def _is_visible_in_codeact(descriptor: ToolDescriptor) -> bool:
    """Return True if a descriptor should be visible to LLM when CodeAct IS active."""
    if not is_codeact_internal(descriptor):
        return False
    return True


def _is_visible_outside_codeact(descriptor: ToolDescriptor) -> bool:
    """Return True if a descriptor should be visible to LLM when CodeAct is NOT active."""
    if not is_codeact_internal(descriptor):
        return True
    return descriptor.meta.get("always_visible", False)


@before_llm_call
async def expose_codeact_tools(ctx: BeforeLlmCallCtx) -> None:
    """Filter tools based on CodeAct state."""
    codeact = ctx.run.agent.services.get(CodeActService)
    if codeact is None:
        return

    codeact_active = codeact.config.get(codeact_enabled) and ctx.run.chain_state.get(CODEACT_ENABLED_KEY)

    if codeact_active:
        index_tools = [t for t in ctx.tools if not is_codeact_internal(t)]
        codeact.rebuild_index(index_tools, ctx.run)
        ctx.tools = [t for t in ctx.tools if _is_visible_in_codeact(t)]
    else:
        ctx.tools = [t for t in ctx.tools if _is_visible_outside_codeact(t)]
