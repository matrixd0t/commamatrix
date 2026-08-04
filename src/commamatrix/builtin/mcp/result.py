# builtin/mcp/result.py

from __future__ import annotations

from typing import Any

from ...utils import to_jsonable


class MCPToolError(RuntimeError):
    """Raised when an MCP server returns an error tool result."""


def _content_value(content: Any) -> Any:
    content_type = getattr(content, "type", None)
    if content_type == "text" and isinstance(getattr(content, "text", None), str):
        return content.text
    if hasattr(content, "model_dump"):
        return content.model_dump(mode="json", by_alias=True, exclude_none=True)
    return to_jsonable(content)


def normalize_call_result(result: Any) -> Any:
    """Convert an MCP CallToolResult into a compact JSON-compatible value."""
    if getattr(result, "isError", getattr(result, "is_error", False)):
        text = [
            item.text
            for item in getattr(result, "content", ())
            if getattr(item, "type", None) == "text" and isinstance(getattr(item, "text", None), str)
        ]
        reason = "\n".join(text) or "MCP server returned an error"
        raise MCPToolError(reason)

    structured = getattr(result, "structuredContent", None)
    if structured is None:
        structured = getattr(result, "structured_content", None)

    content = [_content_value(item) for item in getattr(result, "content", ())]
    if structured is not None and content:
        return {
            "structured_content": to_jsonable(structured),
            "content": to_jsonable(content),
        }
    if structured is not None:
        return to_jsonable(structured)
    if not content:
        return ""
    if all(isinstance(item, str) for item in content):
        return "\n".join(content)
    return to_jsonable(content[0] if len(content) == 1 else content)


__all__ = ["MCPToolError", "normalize_call_result"]
