# builtin/llm_http_adapter/responses.py

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


class ResponsesCodec(ApiCodec):
    protocol = "responses"
    endpoint = "/responses"
    can_stream = True

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
    def _tool_result_content(content: Any) -> str:
        return content if isinstance(content, str) else dumps(content, ensure_ascii=False)

    @staticmethod
    def _extract_reasoning_text(item: dict[str, Any]) -> str:
        summary = item.get("summary", ())
        text = "\n".join(
            part.get("text", "")
            for part in summary
            if isinstance(part, dict) and part.get("type") == "summary_text"
        )
        if not text:
            content_parts = item.get("content", ())
            text = "\n".join(
                part.get("text", "")
                for part in content_parts
                if isinstance(part, dict) and part.get("type") == "reasoning_text"
            )
        return text

    async def build_request(self, *, model: LLM | str, ctx: BeforeLlmCallCtx) -> dict[str, Any]:
        input_items: list[dict[str, Any]] = []

        for item in ctx.dialog:
            try:
                match item.item_type:
                    case DialogItemType.REASONING | DialogItemType.TOOL_CALL:
                        wire = self._wire_value(item)
                        if wire is not None:
                            input_items.append(wire)
                            continue
                        if item.item_type is DialogItemType.REASONING:
                            continue
                        cdata = loads(item.content)
                        input_items.append({
                            "type": "function_call",
                            "call_id": cdata["tool_call_id"],
                            "name": cdata["tool_name"],
                            "arguments": dumps(cdata["tool_args"], ensure_ascii=False),
                        })

                    case DialogItemType.OUTPUT:
                        wire = self._wire_value(item)
                        if wire is not None:
                            input_items.append(wire)
                        else:
                            input_items.append({
                                "role": item.role.value,
                                "content": item.content,
                            })

                    case DialogItemType.INPUT:
                        input_items.append({
                            "role": item.role.value,
                            "content": item.content,
                        })

                    case DialogItemType.TOOL_CALL_RESULT:
                        cdata = loads(item.content)
                        output = self._tool_result_content(cdata["content"])
                        input_items.append({
                            "type": "function_call_output",
                            "call_id": cdata["tool_call_id"],
                            "output": output,
                        })

                    case DialogItemType.IMAGE_INPUT | DialogItemType.IMAGE_OUTPUT:
                        rendered = await self._file_context(ctx, item)
                        if rendered is None:
                            continue
                        if rendered.data_type is DataType.TEXT:
                            input_items.append({
                                "role": DialogRole.USER.value,
                                "content": rendered.content,
                            })
                        else:
                            input_items.append({
                                "role": DialogRole.USER.value,
                                "content": [{
                                    "type": "input_image",
                                    "image_url": rendered.content,
                                }],
                            })

                    case DialogItemType.FILE_INPUT | DialogItemType.FILE_OUTPUT:
                        rendered = await self._file_context(ctx, item)
                        if rendered is None:
                            continue
                        if rendered.data_type is DataType.TEXT:
                            input_items.append({
                                "role": DialogRole.USER.value,
                                "content": rendered.content,
                            })
                        else:
                            input_items.append({
                                "role": DialogRole.USER.value,
                                "content": [{
                                    "type": "input_file",
                                    "filename": rendered.name,
                                    "file_url": rendered.content,
                                }],
                            })
            except (KeyError, TypeError, ValueError):
                continue

        request: dict[str, Any] = {"model": self._model_name(model), "input": input_items, **ctx.llm_call_params}
        if ctx.reasoning is not None:
            request["reasoning"] = {"effort": ctx.reasoning}
        if ctx.tools:
            request["tools"] = self.serialize_tools(ctx)
        return request

    def parse_response(self, body: dict[str, Any]) -> LLMResponse:
        response = LLMResponse(raw=body)

        for output_item in body.get("output", ()):
            item_type = output_item.get("type")
            if item_type == "reasoning":
                summary = output_item.get("summary", ())
                summary_text = "\n".join(
                    part.get("text", "")
                    for part in summary
                    if isinstance(part, dict) and part.get("type") == "summary_text"
                )
                if not summary_text:
                    content_parts = output_item.get("content", ())
                    summary_text = "\n".join(
                        part.get("text", "")
                        for part in content_parts
                        if isinstance(part, dict) and part.get("type") == "reasoning_text"
                    )
                response.content.append(
                    LLMResponseReasoningBlock(
                        content=summary_text,
                        meta=wire_meta("responses.output_item", output_item),
                    )
                )
            elif item_type == "message":
                texts = [
                    part.get("text", "")
                    for part in output_item.get("content", ())
                    if isinstance(part, dict) and part.get("type") == "output_text"
                ]
                text = "".join(texts)
                if text:
                    response.content.append(
                        LLMResponseTextBlock(
                            content=text,
                            meta=wire_meta("responses.output_item", output_item),
                        )
                    )
            elif item_type == "function_call":
                arguments = output_item.get("arguments", "{}")
                tool_args = loads(arguments) if isinstance(arguments, str) else arguments
                response.content.append(
                    LLMResponseToolCallBlock(
                        tool_call_id=output_item.get("call_id", output_item.get("id", "")),
                        tool_name=output_item["name"],
                        tool_args=tool_args,
                        meta=wire_meta("responses.output_item", output_item),
                    )
                )

        status = body.get("status")
        idetails = body.get("incomplete_details", {})
        if status == "incomplete" or idetails and idetails.get("reason") == "max_output_tokens":
            response.stop_reason = StopReason.LENGTH
        elif any(isinstance(block, LLMResponseToolCallBlock) for block in response.content):
            response.stop_reason = StopReason.TOOL_USE
        else:
            response.stop_reason = StopReason.END_TURN

        usage = body.get("usage")
        if usage:
            response.usage = Usage(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                cache_read_tokens=usage.get("input_tokens_details", {}).get("cached_tokens", 0),
                reasoning_tokens=usage.get("output_tokens_details", {}).get("reasoning_tokens", 0),
            )
        return response

    @staticmethod
    def serialize_tools(ctx: BeforeLlmCallCtx) -> list[dict[str, Any]]:
        tm = ctx.run.agent.tool_manager
        return [{"type": "function", **t.schema, "name": tm.public_name(t)} for t in ctx.tools]

    def parse_stream_event(self, event_type: str | None, data: dict[str, Any], acc: dict[str, Any]) -> StreamDelta | LLMResponseBlock | None:
        etype = data.get("type", event_type)

        if etype == "response.created":
            response_obj = data.get("response", {})
            acc["response_id"] = response_obj.get("id", "")
            acc["llm"] = response_obj.get("llm", "")
            return None

        if etype == "response.output_text.delta":
            text = data.get("delta", "")
            acc.setdefault("text_buf", "")
            acc["text_buf"] += text
            return StreamDelta(content=text, delta_type="text")

        if etype == "response.content_part.delta":
            text = data.get("delta", "")
            acc.setdefault("text_buf", "")
            acc["text_buf"] += text
            return StreamDelta(content=text, delta_type="text")

        if etype == "response.reasoning.delta":
            text = data.get("delta", "")
            acc.setdefault("reasoning_buf", "")
            acc["reasoning_buf"] += text
            return StreamDelta(content=text, delta_type="reasoning")

        if etype == "response.reasoning_text.delta":
            text = data.get("delta", "")
            acc.setdefault("reasoning_buf", "")
            acc["reasoning_buf"] += text
            return StreamDelta(content=text, delta_type="reasoning")

        if etype == "response.reasoning_summary_text.delta":
            text = data.get("delta", "")
            acc.setdefault("reasoning_buf", "")
            acc["reasoning_buf"] += text
            return StreamDelta(content=text, delta_type="reasoning")

        if etype == "response.output_item.added":
            item = data.get("item", {})
            if item.get("type") == "function_call":
                item_id = item.get("id", "")
                tc_acc = acc.setdefault("tool_calls", {})
                entry = tc_acc.setdefault(item_id, {"args_buf": ""})
                entry.update({
                    "id": item_id,
                    "call_id": item.get("call_id", ""),
                    "name": item.get("name", ""),
                })
            return None

        if etype == "response.function_call_arguments.delta":
            item_id = data.get("item_id", "")
            tc_acc = acc.setdefault("tool_calls", {})
            entry = tc_acc.setdefault(item_id, {"args_buf": "", "id": item_id})
            delta = data.get("delta", "")
            entry["args_buf"] += delta
            return StreamDelta(
                content=delta,
                delta_type="tool_call",
                meta={
                    "tool_call_id": entry.get("call_id", item_id),
                    "tool_name": entry.get("name", ""),
                },
            )

        if etype == "response.output_item.done":
            item = data.get("item", {})
            item_type = item.get("type")
            if item_type == "function_call":
                item_id = item.get("id", "")
                tc_acc = acc.setdefault("tool_calls", {})
                entry = tc_acc.setdefault(item_id, {})
                entry.update({
                    "id": item_id,
                    "call_id": item.get("call_id", entry.get("call_id", "")),
                    "name": item.get("name", entry.get("name", "")),
                })
                args_buf = entry.get("args_buf", item.get("arguments", "{}"))
                try:
                    tool_args = loads(args_buf) if isinstance(args_buf, str) else args_buf
                except (ValueError, TypeError):
                    tool_args = {}
                return LLMResponseToolCallBlock(
                    tool_call_id=item.get("call_id", item_id),
                    tool_name=item.get("name", ""),
                    tool_args=tool_args,
                    meta=wire_meta("responses.output_item", item),
                )
            if item_type == "message":
                acc.setdefault("completed_message_ids", []).append(item.get("id", ""))
            if item_type == "reasoning":
                reasoning_text = self._extract_reasoning_text(item)
                if not reasoning_text:
                    reasoning_text = acc.get("reasoning_buf", "")
                if reasoning_text:
                    acc["yielded_reasoning"] = True
                    return LLMResponseReasoningBlock(
                        content=reasoning_text,
                        meta=wire_meta("responses.output_item", item),
                    )
                acc.setdefault("completed_reasoning_ids", []).append(item.get("id", ""))
            return None

        if etype == "response.done":
            response_obj = data.get("response", {})
            acc["response"] = response_obj
            return None

        if etype == "response.completed":
            response_obj = data.get("response", {})
            acc["response"] = response_obj
            return None

        return None

    def flush_stream(self, acc: dict[str, Any]) -> tuple[list[LLMResponseBlock], StreamEnd]:
        blocks: list[LLMResponseBlock] = []
        response_obj = acc.get("response", {})
        yielded_reasoning = acc.get("yielded_reasoning", False)

        for output_item in response_obj.get("output", ()):
            item_type = output_item.get("type")
            if item_type == "reasoning" and not yielded_reasoning:
                summary_text = self._extract_reasoning_text(output_item)
                if summary_text:
                    blocks.append(LLMResponseReasoningBlock(
                        content=summary_text,
                        meta=wire_meta("responses.output_item", output_item),
                    ))
            elif item_type == "message":
                texts = [
                    part.get("text", "")
                    for part in output_item.get("content", ())
                    if isinstance(part, dict) and part.get("type") == "output_text"
                ]
                text = "".join(texts)
                if text:
                    blocks.append(LLMResponseTextBlock(
                        content=text,
                        meta=wire_meta("responses.output_item", output_item),
                    ))

        stop_reason = StopReason.END_TURN
        status = response_obj.get("status")
        idetails = response_obj.get("incomplete_details", {})
        if status == "incomplete" or (idetails and idetails.get("reason") == "max_output_tokens"):
            stop_reason = StopReason.LENGTH

        usage_data = response_obj.get("usage", {})
        usage = Usage(
            input_tokens=usage_data.get("input_tokens", 0),
            output_tokens=usage_data.get("output_tokens", 0),
            cache_read_tokens=usage_data.get("input_tokens_details", {}).get("cached_tokens", 0),
            reasoning_tokens=usage_data.get("output_tokens_details", {}).get("reasoning_tokens", 0),
        ) if usage_data else None

        end = StreamEnd(
            stop_reason=stop_reason,
            usage=usage,
        )
        return blocks, end
