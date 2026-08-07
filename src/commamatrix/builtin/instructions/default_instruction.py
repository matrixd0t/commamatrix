# builtin/default_instruction.py

"""Default context shared by the built-in presets."""

from __future__ import annotations

from ...components.instruction import InstructionCtx, instruction


@instruction(priority=100)
def default_instruction(_ctx: InstructionCtx) -> str:
    """Identify the runtime environment to the model."""
    return "# Environment\nYou operate in `commamatrix` agentic environment (see github.com/matrixd0t/commamatrix)"


__all__ = ["default_instruction"]
