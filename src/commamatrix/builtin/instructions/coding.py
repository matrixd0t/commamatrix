# builtin/coding.py

"""Guidance for software-engineering tasks."""

from __future__ import annotations

from commamatrix.components.instruction import InstructionCtx, instruction


@instruction(priority=20)
def coding_guidance(_ctx: InstructionCtx) -> str:
    """Set a careful, repository-oriented coding workflow."""
    return """
# Coding mode
- Inspect the relevant code and existing conventions before making changes.
- Prefer the smallest coherent change and preserve established architecture and APIs unless the task requires otherwise.
- Use `code_apply_patch` for code edits (named `tools.code.apply_patch` in CodeAct), especially for changes spanning multiple files.
- Keep security, error handling, and backwards compatibility in mind when they are relevant to the task.
- Before reporting completion, review the resulting changes and state what was verified.
"""


__all__ = ["coding_guidance"]
