# builtin/llm_http_adapter/responses.py

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


class ResponsesCodec(ApiCodec):
    protocol = "responses"
    endpoint = "/responses"

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

    async def build_request(self, *, model: str, ctx: BeforeLlmCallCtx) -> dict[str, Any]:
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

                    case DialogItemType.IMAGE_INPUT | DialogItemType.IMAGE_OUTPUT | DialogItemType.FILE_INPUT | DialogItemType.FILE_OUTPUT:
                        input_items.append({
                            "role": DialogRole.USER.value,
                            "content": item.content,
                        })
            except (KeyError, TypeError, ValueError):
                continue

        request = {"model": model, "input": input_items, **ctx.llm_call_params}
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
