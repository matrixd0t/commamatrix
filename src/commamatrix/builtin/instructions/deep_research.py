# builtin/deep_research.py

"""Guidance for source-based research tasks."""

from __future__ import annotations

from commamatrix.components.instruction import InstructionCtx, instruction


@instruction(priority=20)
def deep_research_guidance(_ctx: InstructionCtx) -> str:
    """Set a source-first research workflow."""
    return """
# Deep research mode
- Break the question into focused subquestions before searching.
- Prefer primary, recent, and directly relevant sources; use multiple independent sources for important claims.
- Distinguish sourced facts, calculations, assumptions, and your own conclusions.
- Note meaningful uncertainty or source conflicts, and include source URLs for externally verifiable claims.
"""


__all__ = ["deep_research_guidance"]
