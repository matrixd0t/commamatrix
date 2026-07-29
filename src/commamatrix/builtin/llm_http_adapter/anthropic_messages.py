# builtin/llm_http_adapter/anthropic_messages.py

from __future__ import annotations

from json import dumps, loads
from typing import Any

from ...components.dialog import DialogItemType, DialogRole
from ...components.file_storage import FileContentType
from ...components.hook import BeforeLlmCallCtx
from ...components.llm_adapter import (
    LLMResponse,
    LLMResponseBlock,
    LLMResponseReasoningBlock,
    LLMResponseTextBlock,
    LLMResponseToolCallBlock,
    StopReason,
    StreamDelta,
    StreamEnd,
    Usage,
)
from .codec import ApiCodec, wire_meta


class AnthropicMessagesCodec(ApiCodec):
    protocol = "anthropic_messages"
    endpoint = "/v1/messages"
    can_stream = True

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

    @staticmethod
    def _data_uri_payload(uri: str) -> str:
        _, separator, payload = uri.partition(",")
        return payload if separator else uri

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

                    case DialogItemType.IMAGE_INPUT | DialogItemType.IMAGE_OUTPUT:
                        rendered = await self._file_context(
                            ctx,
                            item,
                            modalities=FileContentType.IMAGE,
                        )
                        if rendered is None:
                            continue
                        if rendered.modality is FileContentType.TEXT:
                            self._append_message(messages, DialogRole.USER.value, rendered.content)
                        else:
                            self._append_message(messages, DialogRole.USER.value, [{
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": rendered.mime_type,
                                    "data": self._data_uri_payload(rendered.content),
                                },
                            }])

                    case DialogItemType.FILE_INPUT | DialogItemType.FILE_OUTPUT:
                        rendered = await self._file_context(
                            ctx,
                            item,
                            modalities=FileContentType.FILE,
                        )
                        if rendered is None:
                            continue
                        if rendered.modality is FileContentType.TEXT:
                            self._append_message(messages, DialogRole.USER.value, rendered.content)
                        else:
                            self._append_message(messages, DialogRole.USER.value, [{
                                "type": "document",
                                "source": {
                                    "type": "base64",
                                    "media_type": rendered.mime_type,
                                    "data": self._data_uri_payload(rendered.content),
                                },
                            }])
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

    def parse_stream_event(
        self,
        event_type: str | None,
        data: dict[str, Any],
        acc: dict[str, Any],
    ) -> StreamDelta | LLMResponseBlock | None:
        msg_type = data.get("type")

        if msg_type == "message_start":
            message = data.get("message", {})
            acc["response_id"] = message.get("id", "")
            acc["model"] = message.get("model", "")
            msg_usage = message.get("usage", {})
            acc["usage"] = Usage(
                input_tokens=msg_usage.get("input_tokens", 0),
                output_tokens=0,
                cache_read_tokens=msg_usage.get("cache_read_input_tokens", 0),
                cache_write_tokens=msg_usage.get("cache_creation_input_tokens", 0),
            )
            return None

        if msg_type == "content_block_start":
            index = data.get("index", 0)
            block = data.get("content_block", {})
            block_type = block.get("type")
            acc["current_block"] = {"index": index, "type": block_type, "text_buf": ""}
            if block_type == "tool_use":
                acc["current_block"]["id"] = block.get("id", "")
                acc["current_block"]["name"] = block.get("name", "")
                acc["current_block"]["args_buf"] = ""
                return StreamDelta(
                    content="",
                    delta_type="tool_call",
                    meta={
                        "tool_call_id": block.get("id", ""),
                        "tool_name": block.get("name", ""),
                    },
                )
            return None

        if msg_type == "content_block_delta":
            delta = data.get("delta", {})
            delta_type = delta.get("type")
            if delta_type == "thinking_delta":
                text = delta.get("thinking", "")
                current = acc.get("current_block")
                if current:
                    current["text_buf"] += text
                return StreamDelta(content=text, delta_type="reasoning")
            if delta_type == "text_delta":
                text = delta.get("text", "")
                current = acc.get("current_block")
                if current:
                    current["text_buf"] += text
                return StreamDelta(content=text, delta_type="text")
            if delta_type == "input_json_delta":
                current = acc.get("current_block")
                if current:
                    partial_json = delta.get("partial_json", "")
                    current.setdefault("args_buf", "")
                    current["args_buf"] += partial_json
                    return StreamDelta(
                        content=partial_json,
                        delta_type="tool_call",
                        meta={
                            "tool_call_id": current.get("id", ""),
                            "tool_name": current.get("name", ""),
                        },
                    )
                return None
            return None

        if msg_type == "content_block_stop":
            current = acc.get("current_block")
            if current is None:
                return None
            block_type = current.get("type")
            if block_type == "tool_use":
                try:
                    tool_args = loads(current["args_buf"]) if current["args_buf"] else {}
                except (ValueError, TypeError):
                    tool_args = {}
                block = LLMResponseToolCallBlock(
                    tool_call_id=current["id"],
                    tool_name=current["name"],
                    tool_args=tool_args,
                    meta=wire_meta("anthropic_messages.tool_use", current),
                )
                acc["current_block"] = None
                return block
            if block_type in ("text", "thinking"):
                acc.setdefault("completed_blocks", []).append({
                    "type": block_type,
                    "text_buf": current.get("text_buf", ""),
                })
            acc["current_block"] = None
            return None

        if msg_type == "message_delta":
            delta = data.get("delta", {})
            stop = delta.get("stop_reason")
            if stop == "tool_use":
                acc["stop_reason"] = StopReason.TOOL_USE
            elif stop == "max_tokens":
                acc["stop_reason"] = StopReason.LENGTH
            else:
                acc["stop_reason"] = StopReason.END_TURN
            delta_usage = data.get("usage", {})
            prev = acc.get("usage")
            if prev:
                acc["usage"] = Usage(
                    input_tokens=prev.input_tokens,
                    output_tokens=delta_usage.get("output_tokens", prev.output_tokens),
                    cache_read_tokens=prev.cache_read_tokens,
                    cache_write_tokens=prev.cache_write_tokens,
                )
            else:
                acc["usage"] = Usage(
                    input_tokens=0,
                    output_tokens=delta_usage.get("output_tokens", 0),
                )
            return None

        return None

    def flush_stream(self, acc: dict[str, Any]) -> tuple[list[LLMResponseBlock], StreamEnd]:
        blocks: list[LLMResponseBlock] = []

        for block_data in acc.get("completed_blocks", []):
            block_type = block_data["type"]
            text_buf = block_data["text_buf"]
            if block_type == "thinking" and text_buf:
                blocks.append(LLMResponseReasoningBlock(
                    content=text_buf,
                    meta=wire_meta("anthropic_messages.content_block", {"type": "thinking", "thinking": text_buf}),
                ))
            elif block_type == "text" and text_buf:
                blocks.append(LLMResponseTextBlock(
                    content=text_buf,
                    meta=wire_meta("anthropic_messages.content_block", {"type": "text", "text": text_buf}),
                ))

        end = StreamEnd(
            stop_reason=acc.get("stop_reason", StopReason.END_TURN),
            usage=acc.get("usage"),
        )
        return blocks, end
