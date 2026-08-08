# builtin/llm_http_adapter/chat_completions.py

from __future__ import annotations

from json import dumps, loads
from typing import Any

from ...components.dialog import DialogItemType, DialogRole
from ...components.file_storage import DataType
from ...components.hook import BeforeLlmCallCtx
from ...components.llm_adapter import (
    LLM,
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


class ChatCompletionsCodec(ApiCodec):
    protocol = "chat_completions"
    endpoint = "/chat/completions"
    can_stream = True

    @staticmethod
    def serialize_tools(ctx: BeforeLlmCallCtx) -> list[dict[str, Any]]:
        tm = ctx.run.agent.tool_manager
        result = []
        for tool in ctx.tools:
            function = dict(tool.schema)
            function.pop("type", None)
            function["name"] = tm.public_name(tool)
            result.append({"type": "function", "function": function})
        return result

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

    async def build_request(self, *, model: LLM | str, ctx: BeforeLlmCallCtx) -> dict[str, Any]:
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
                        rendered = await self._file_context(ctx, item)
                        if rendered is None:
                            continue
                        if rendered.data_type is DataType.TEXT:
                            messages.append({"role": "user", "content": rendered.content})
                            continue
                        messages.append({
                            "role": "user",
                            "content": [{"type": "image_url", "image_url": {"url": rendered.content, "detail": "auto"}}],
                        })

                    case DialogItemType.FILE_INPUT | DialogItemType.FILE_OUTPUT:
                        flush_assistant()
                        rendered = await self._file_context(ctx, item)
                        if rendered is None:
                            continue
                        if rendered.data_type is DataType.TEXT:
                            messages.append({"role": "user", "content": rendered.content})
                            continue
                        messages.append({
                            "role": "user",
                            "content": [{"type": "file", "file": {"url": rendered.content}}],
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
        request = {"model": self._model_name(model), "messages": messages, **ctx.llm_call_params}
        if ctx.reasoning is not None:
            request["reasoning_effort"] = ctx.reasoning
        if ctx.tools:
            request["tools"] = self.serialize_tools(ctx)
        return request

    def parse_response(self, body: dict[str, Any]) -> LLMResponse:
        choice = body["choices"][0]
        message = choice["message"]
        response = LLMResponse(
            raw=body,
            meta={
                "llm": {
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
            (field for field in ("reasoning_content", "reasoning_level") if field in message),
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

    def enable_streaming(self, body: dict[str, Any]) -> dict[str, Any]:
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
        return body

    def parse_stream_event(self, event_type: str | None, data: dict[str, Any], acc: dict[str, Any]) -> StreamDelta | LLMResponseBlock | None:
        choices = data.get("choices")
        usage = data.get("usage")
        response_id = data.get("id")
        model = data.get("llm")
        if response_id:
            acc["response_id"] = response_id
        if model:
            acc["llm"] = model

        if not choices and usage is not None:
            acc["usage"] = Usage(
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                reasoning_tokens=usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0),
            )
            return None

        if not choices:
            return None

        choice = choices[0]
        delta = choice.get("delta", {})
        finish_reason = choice.get("finish_reason")

        text = delta.get("content")
        if text:
            acc.setdefault("text_buf", "")
            acc["text_buf"] += text
            return StreamDelta(content=text, delta_type="text")

        for field_name in ("reasoning_content", "reasoning_level"):
            reasoning_val = delta.get(field_name)
            if reasoning_val is None:
                continue
            if isinstance(reasoning_val, str):
                acc.setdefault("reasoning_buf", "")
                acc["reasoning_buf"] += reasoning_val
                acc.setdefault("reasoning_field", field_name)
                return StreamDelta(content=reasoning_val, delta_type="reasoning_level")
            if isinstance(reasoning_val, dict):
                text_val = reasoning_val.get("summary", reasoning_val.get("content", ""))
                if text_val:
                    acc.setdefault("reasoning_buf", "")
                    acc["reasoning_buf"] += str(text_val)
                    acc.setdefault("reasoning_field", field_name)
                    return StreamDelta(content=str(text_val), delta_type="reasoning_level")

        tool_calls = delta.get("tool_calls")
        if tool_calls:
            tc_acc = acc.setdefault("tool_calls", {})
            for tc in tool_calls:
                idx = tc.get("index", 0)
                entry = tc_acc.get(idx)
                if entry is None:
                    entry = {"id": tc.get("id", ""), "name": "", "args_buf": ""}
                    tc_acc[idx] = entry
                if tc.get("id"):
                    entry["id"] = tc["id"]
                fn = tc.get("function", {})
                if fn.get("name"):
                    entry["name"] = fn["name"]
                arguments = fn.get("arguments", "")
                if arguments:
                    entry["args_buf"] += arguments
            tc = tool_calls[-1]
            idx = tc.get("index", 0)
            entry = tc_acc[idx]
            fn = tc.get("function", {})
            return StreamDelta(
                content=fn.get("arguments", ""),
                delta_type="tool_call",
                meta={
                    "tool_call_id": entry["id"],
                    "tool_name": entry["name"],
                    "tool_call_index": idx,
                },
            )

        if finish_reason:
            stop_reason = StopReason.END_TURN
            if finish_reason == "tool_calls":
                stop_reason = StopReason.TOOL_USE
            elif finish_reason in ("length", "max_tokens"):
                stop_reason = StopReason.LENGTH
            acc["stop_reason"] = stop_reason
            return None

        return None

    def flush_stream(self, acc: dict[str, Any]) -> tuple[list[LLMResponseBlock], StreamEnd]:
        blocks: list[LLMResponseBlock] = []

        text_buf = acc.get("text_buf", "")
        reasoning_buf = acc.get("reasoning_buf", "")

        wire_assistant: dict[str, Any] = {"role": "assistant"}
        if reasoning_buf:
            field = acc.get("reasoning_field", "reasoning_content")
            wire_assistant[field] = reasoning_buf
        if text_buf:
            wire_assistant["content"] = text_buf

        tc_acc = acc.get("tool_calls", {})
        if tc_acc:
            wire_tool_calls = []
            for idx in sorted(tc_acc):
                entry = tc_acc[idx]
                wire_tool_calls.append({
                    "id": entry["id"],
                    "type": "function",
                    "function": {
                        "name": entry["name"],
                        "arguments": entry["args_buf"],
                    },
                })
            wire_assistant["tool_calls"] = wire_tool_calls

        if reasoning_buf:
            field = acc.get("reasoning_field", "reasoning_content")
            blocks.append(LLMResponseReasoningBlock(
                content=reasoning_buf,
                meta=wire_meta("chat_completions.assistant_field", reasoning_buf, field=field),
            ))

        if text_buf:
            blocks.append(LLMResponseTextBlock(
                content=text_buf,
                meta=wire_meta("chat_completions.assistant_message", wire_assistant),
            ))

        for idx in sorted(tc_acc):
            entry = tc_acc[idx]
            try:
                tool_args = loads(entry["args_buf"]) if entry["args_buf"] else {}
            except (ValueError, TypeError):
                tool_args = {}
            blocks.append(LLMResponseToolCallBlock(
                tool_call_id=entry["id"],
                tool_name=entry["name"],
                tool_args=tool_args,
                meta=wire_meta("chat_completions.tool_call", entry),
            ))

        end = StreamEnd(
            stop_reason=acc.get("stop_reason", StopReason.END_TURN),
            usage=acc.get("usage"),
        )
        return blocks, end
