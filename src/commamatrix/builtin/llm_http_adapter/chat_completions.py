# builtin/llm_http_adapter/chat_completions.py

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
    resolve_file_uri,
)
from .codec import ApiCodec, wire_meta


class ChatCompletionsCodec(ApiCodec):
    protocol = "chat_completions"
    endpoint = "/chat/completions"

    @staticmethod
    def serialize_tools(ctx: BeforeLlmCallCtx) -> list[dict[str, Any]]:
        tm = ctx.run.agent.tool_manager
        return [{"type": "function", "function": {**t.schema, "name": tm.public_name(t)}} for t in ctx.tools]

    @staticmethod
    def _llm_meta(item: Any) -> dict[str, Any]:
        meta = item.meta.get("llm", {})
        return meta if isinstance(meta, dict) else {}

    @classmethod
    def _wire_reasoning(cls, item: Any) -> tuple[str, Any] | None:
        wire = cls._llm_meta(item).get("wire", {})
        if not isinstance(wire, dict):
            return None
        field = wire.get("field")
        if not isinstance(field, str):
            return None
        return field, wire.get("value", item.content)

    @staticmethod
    def _append_text(message: dict[str, Any], content: str) -> None:
        previous = message.get("content")
        if not previous:
            message["content"] = content
        elif content:
            message["content"] = f"{previous}{content}"

    @classmethod
    def _response_wire(cls, source_item: Any) -> dict[str, Any] | None:
        wire = cls._llm_meta(source_item).get("response_wire", {})
        if not isinstance(wire, dict):
            return None
        value = wire.get("value")
        return value if isinstance(value, dict) else None

    async def build_request(self, *, model: str, ctx: BeforeLlmCallCtx) -> dict[str, Any]:
        messages: list[dict[str, Any]] = []
        assistant_message: dict[str, Any] | None = None
        assistant_wire = False

        def flush_assistant() -> None:
            nonlocal assistant_message, assistant_wire
            if assistant_message is not None:
                messages.append(assistant_message)
                assistant_message = None
                assistant_wire = False

        def get_assistant(source_item: Any | None = None) -> dict[str, Any]:
            nonlocal assistant_message, assistant_wire
            if assistant_message is None:
                raw_message = self._response_wire(source_item) if source_item is not None else None
                assistant_message = dict(raw_message) if raw_message is not None else {
                    "role": "assistant",
                    "content": None,
                }
                assistant_wire = raw_message is not None
            if assistant_message is None:
                raise RuntimeError("Assistant message was not initialized")
            return assistant_message

        for item in ctx.dialog:
            try:
                match item.item_type:
                    case DialogItemType.REASONING:
                        wire_reasoning = self._wire_reasoning(item)
                        if wire_reasoning is None:
                            continue
                        field, value = wire_reasoning
                        assistant = get_assistant(item)
                        if not assistant_wire:
                            assistant[field] = value

                    case DialogItemType.OUTPUT:
                        if item.role is not DialogRole.ASSISTANT:
                            flush_assistant()
                            messages.append({"role": item.role.value, "content": item.content})
                            continue
                        assistant = get_assistant(item)
                        if not assistant_wire:
                            self._append_text(assistant, item.content)

                    case DialogItemType.INPUT:
                        flush_assistant()
                        messages.append({"role": item.role.value, "content": item.content})

                    case DialogItemType.IMAGE_INPUT | DialogItemType.IMAGE_OUTPUT:
                        flush_assistant()
                        uri = await resolve_file_uri(ctx.run.agent.file_storage, item)
                        if not uri:
                            continue
                        messages.append({
                            "role": "user",
                            "content": [{"type": "image_url", "image_url": {"url": uri, "detail": "auto"}}],
                        })

                    case DialogItemType.FILE_INPUT | DialogItemType.FILE_OUTPUT:
                        flush_assistant()
                        uri = await resolve_file_uri(ctx.run.agent.file_storage, item)
                        if not uri:
                            continue
                        messages.append({
                            "role": "user",
                            "content": [{"type": "file", "file": {"url": uri}}],
                        })

                    case DialogItemType.TOOL_CALL:
                        cdata = loads(item.content)
                        call = {
                            "id": cdata["tool_call_id"],
                            "type": "function",
                            "function": {
                                "name": cdata["tool_name"],
                                "arguments": dumps(cdata["tool_args"], ensure_ascii=False),
                            },
                        }
                        assistant = get_assistant(item)
                        if not assistant_wire:
                            assistant.setdefault("tool_calls", []).append(call)

                    case DialogItemType.TOOL_CALL_RESULT:
                        flush_assistant()
                        cdata = loads(item.content)
                        content = cdata["content"]
                        if not isinstance(content, str):
                            content = dumps(content, ensure_ascii=False)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": cdata["tool_call_id"],
                            "content": content,
                        })
            except (KeyError, TypeError, ValueError):
                continue

        flush_assistant()
        request = {"model": model, "messages": messages, **ctx.llm_call_params}
        if ctx.tools:
            request["tools"] = self.serialize_tools(ctx)
        return request

    def parse_response(self, body: dict[str, Any]) -> LLMResponse:
        choice = body["choices"][0]
        message = choice["message"]
        response = LLMResponse(
            raw=body,
            model=body.get("model"),
            meta={
                "llm": {
                    "protocol": self.protocol,
                    "response_id": body.get("id"),
                    "turn_id": body.get("id"),
                    "wire": {
                        "kind": "chat_completions.assistant_message",
                        "value": message,
                    },
                }
            },
        )
        finish_reason = choice.get("finish_reason")
        if finish_reason == "tool_calls":
            response.stop_reason = StopReason.TOOL_USE
        elif finish_reason in ("length", "max_tokens"):
            response.stop_reason = StopReason.LENGTH
        else:
            response.stop_reason = StopReason.END_TURN

        reasoning_field = next(
            (field for field in ("reasoning_content", "reasoning") if field in message),
            None,
        )
        if reasoning_field is not None:
            reasoning_value = message[reasoning_field]
            if isinstance(reasoning_value, str):
                reasoning_content = reasoning_value
            elif isinstance(reasoning_value, dict):
                reasoning_content = str(
                    reasoning_value.get("summary", reasoning_value.get("content", ""))
                )
            else:
                reasoning_content = str(reasoning_value)
            response.content.append(
                LLMResponseReasoningBlock(
                    content=reasoning_content,
                    meta=wire_meta(
                        "chat_completions.assistant_field",
                        reasoning_value,
                        field=reasoning_field,
                    ),
                )
            )

        content = message.get("content")
        if content:
            if not isinstance(content, str):
                content = dumps(content, ensure_ascii=False)
            response.content.append(LLMResponseTextBlock(content=content))

        for tc in message.get("tool_calls", ()):
            response.content.append(LLMResponseToolCallBlock(
                tool_call_id=tc["id"],
                tool_name=tc["function"]["name"],
                tool_args=loads(tc["function"]["arguments"]),
                meta=wire_meta("chat_completions.tool_call", tc),
            ))

        usage = body.get("usage")
        if usage:
            response.usage = Usage(
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                reasoning_tokens=usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0),
            )
        return response
