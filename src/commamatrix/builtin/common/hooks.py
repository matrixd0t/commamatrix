# builtin/common/hooks.py

"""Common hooks shared across all agents."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace

from ...api.hooks import BeforeLlmCallCtx, before_llm_call


@before_llm_call(priority=-1000)
def disambiguate_tool_names(ctx: BeforeLlmCallCtx) -> None:
    """Rewrite exported_name to alias.name when multiple tools share the same name.

    Creates new ToolDescriptor instances with updated exported_name.
    ToolManager.resolve() checks exported_name, so LLM tool calls
    using dotted names will resolve correctly.

    Skipped when CodeAct is active — in CodeAct mode tools are resolved
    via dotted alias imports and unique descriptor ids, so LLM-visible
    name disambiguation is unnecessary.
    """
    if ctx.run.state.get('codeact-enabled'):  # builtin.codeact.CODACT_ENABLED_KEY
        return

    buckets: dict[str, list[int]] = defaultdict(list)
    for i, d in enumerate(ctx.tools):
        buckets[d.name].append(i)

    for name, indices in buckets.items():
        if len(indices) < 2:
            continue
        for i in indices:
            d = ctx.tools[i]
            dotted = f"{d.alias}.{d.name}"
            if d.exported_name != dotted:
                ctx.tools[i] = replace(d, exported_name=dotted)
