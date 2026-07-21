# builtin/llm_http_adapter/anthropic_messages.py

from __future__ import annotations

from json import dumps, loads
from typing import Any

from ...components.dialog import DialogItemType, DialogRole
from ...components.hook import BeforeLlmCallCtx
from ...components.llm_adapter import (
    LLMResponse,
    LLMResponseReasoningBlock,
    LLMResponseTextBlock,
    LLMResponseToolCallBlock,
    StopReason,
    Usage,
)
from .codec import ApiCodec, wire_meta


class AnthropicMessagesCodec(ApiCodec):
    protocol = "anthropic_messages"
    endpoint = "/v1/messages"

    @staticmethod
    def serialize_tools(ctx: BeforeLlmCallCtx) -> list[dict[str, Any]]:
        tm = ctx.run.agent.tool_manager
        return [{
            "name": tm.public_name(t),
            "description": t.schema.get("description", ""),
            "input_schema": t.schema.get("parameters", {}),
        } for t in ctx.tools]

    @staticmethod
    def _wire_value(item: Any) -> dict[str, Any] | None:
        llm_meta = item.meta.get("llm", {})
        if not isinstance(llm_meta, dict):
            return None
        wire = llm_meta.get("wire", {})
        if not isinstance(wire, dict):
            return None
        value = wire.get("value")
        return value if isinstance(value, dict) else None

    @staticmethod
    def _append_message(messages: list[dict[str, Any]], role: str, content: Any) -> None:
        if not messages or messages[-1]["role"] != role:
            messages.append({"role": role, "content": content})
            return

        existing = messages[-1]["content"]
        if not isinstance(existing, list):
            existing = [{"type": "text", "text": existing}]
            messages[-1]["content"] = existing
        if isinstance(content, list):
            existing.extend(content)
        else:
            existing.append({"type": "text", "text": content})

    async def build_request(self, *, model: str, ctx: BeforeLlmCallCtx) -> dict[str, Any]:
        messages: list[dict[str, Any]] = []
        system_parts: list[str] = []

        for item in ctx.dialog:
            try:
                if item.item_type is DialogItemType.INPUT and item.role is DialogRole.SYSTEM:
                    system_parts.append(item.content)
                    continue

                match item.item_type:
                    case DialogItemType.INPUT:
                        self._append_message(messages, item.role.value, item.content)

                    case DialogItemType.REASONING | DialogItemType.OUTPUT | DialogItemType.TOOL_CALL:
                        wire = self._wire_value(item)
                        if wire is not None:
                            self._append_message(messages, DialogRole.ASSISTANT.value, wire)
                            continue

                        if item.item_type is DialogItemType.REASONING:
                            continue
                        if item.item_type is DialogItemType.OUTPUT:
                            self._append_message(messages, DialogRole.ASSISTANT.value, {
                                "type": "text",
                                "text": item.content,
                            })
                            continue

                        cdata = loads(item.content)
                        self._append_message(messages, DialogRole.ASSISTANT.value, {
                            "type": "tool_use",
                            "id": cdata["tool_call_id"],
                            "name": cdata["tool_name"],
                            "input": cdata["tool_args"],
                        })

                    case DialogItemType.TOOL_CALL_RESULT:
                        cdata = loads(item.content)
                        self._append_message(messages, DialogRole.USER.value, {
                            "type": "tool_result",
                            "tool_use_id": cdata["tool_call_id"],
                            "content": cdata["content"] if isinstance(cdata["content"], str) else dumps(cdata["content"], ensure_ascii=False),
                        })

                    case DialogItemType.IMAGE_INPUT | DialogItemType.IMAGE_OUTPUT | DialogItemType.FILE_INPUT | DialogItemType.FILE_OUTPUT:
                        self._append_message(messages, DialogRole.USER.value, item.content)
            except (KeyError, TypeError, ValueError):
                continue

        request = {"model": model, "messages": messages, **ctx.llm_call_params}
        if system_parts:
            request["system"] = "\n\n".join(system_parts)
        if ctx.tools:
            request["tools"] = self.serialize_tools(ctx)
        return request

    def parse_response(self, body: dict[str, Any]) -> LLMResponse:
        response = LLMResponse(
            raw=body,
            model=body.get("model"),
            meta={
                "llm": {
                    "protocol": self.protocol,
                    "response_id": body.get("id"),
                    "turn_id": body.get("id"),
                }
            },
        )

        for content_block in body.get("content", ()):
            block_type = content_block.get("type")
            if block_type == "thinking":
                response.content.append(
                    LLMResponseReasoningBlock(
                        content=content_block.get("thinking", ""),
                        meta=wire_meta("anthropic_messages.content_block", content_block),
                    )
                )
            elif block_type == "text":
                response.content.append(
                    LLMResponseTextBlock(
                        content=content_block.get("text", ""),
                        meta=wire_meta("anthropic_messages.content_block", content_block),
                    )
                )
            elif block_type == "tool_use":
                response.content.append(
                    LLMResponseToolCallBlock(
                        tool_call_id=content_block["id"],
                        tool_name=content_block["name"],
                        tool_args=content_block.get("input", {}),
                        meta=wire_meta("anthropic_messages.content_block", content_block),
                    )
                )

        stop_reason = body.get("stop_reason")
        if stop_reason == "tool_use":
            response.stop_reason = StopReason.TOOL_USE
        elif stop_reason == "max_tokens":
            response.stop_reason = StopReason.LENGTH
        else:
            response.stop_reason = StopReason.END_TURN

        usage = body.get("usage")
        if usage:
            response.usage = Usage(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                cache_read_tokens=usage.get("cache_read_input_tokens", 0),
                cache_write_tokens=usage.get("cache_creation_input_tokens", 0),
            )
        return response
