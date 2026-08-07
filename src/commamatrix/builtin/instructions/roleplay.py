# builtin/roleplay.py

"""Guidance for character-driven conversations."""

from __future__ import annotations

from ...components.instruction import InstructionCtx, instruction


@instruction(priority=20)
def roleplay_guidance(_ctx: InstructionCtx) -> str:
    """Set continuity and boundary expectations for roleplay."""
    return """
# Roleplay mode
- Stay consistent with the requested character, setting, tone, and established story facts.
- Prefer engaging in-world responses; do not break character unless the user asks for an out-of-character answer.
- Track continuity across turns and ask a concise clarifying question when an important detail is missing.
"""


__all__ = ["roleplay_guidance"]
