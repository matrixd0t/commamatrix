# builtin/data_analysis.py

"""Guidance for data analysis tasks."""

from __future__ import annotations

from ...components.instruction import InstructionCtx, instruction


@instruction(priority=20)
def data_analysis_guidance(_ctx: InstructionCtx) -> str:
    """Set a reproducible and assumption-aware analysis workflow."""
    return """
# Data analysis mode
- Inspect the available data and schema before drawing conclusions.
- State important assumptions, missing values, filters, units, and definitions used in calculations.
- Use executable tools for non-trivial calculations and validate results with sanity checks.
- Separate observed data, derived metrics, estimates, and interpretations in the final answer.
- Report limitations and avoid implying causation from correlation alone.
"""


__all__ = ["data_analysis_guidance"]
