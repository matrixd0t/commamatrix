# builtin/automation.py

"""Guidance for multi-step operational tasks."""

from __future__ import annotations

from ...components.instruction import InstructionCtx, instruction


@instruction(priority=20)
def automation_guidance(_ctx: InstructionCtx) -> str:
    """Set a deliberate workflow for actions with side effects."""
    return """
# Automation mode
- Turn the request into explicit steps and identify actions with side effects before executing them.
- Prefer idempotent operations, preserve existing data, and avoid destructive changes without clear authorization.
- Use available tools rather than claiming an action was completed, and verify important outcomes afterward.
- If a required choice or permission is missing, ask before taking the consequential action.
- Summarize completed actions, skipped actions, and any follow-up needed.
"""


__all__ = ["automation_guidance"]
