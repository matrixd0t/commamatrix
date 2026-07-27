# components/llm_adapter.py

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from enum import StrEnum
from dataclasses import dataclass, field
from json import dumps, loads
from mimetypes import guess_type
from collections.abc import AsyncIterator
from typing import Any, TYPE_CHECKING
from httpx import HTTPError

from ..utils import to_jsonable
from ..core.classes.service import AbstractService
from ..core.classes.manager import ServiceInstanceManager
from ..core.classes.source import PythonServiceSource
from .dialog import DialogItem, DialogItemType, DialogRole, DialogOrigin

if TYPE_CHECKING:
    from .hook import BeforeLlmCallCtx
    from .file_storage import FileStorage
    from ..core.agent import Agent

LLM_ADAPTER_ATTRIBUTE = "__commamatrix_llm_adapter__"


class LLMError(Exception):
    ...


class LLMResponseError(LLMError):
    ...


class LLMTruncatedError(LLMError):
    ...


@dataclass(slots=True, kw_only=True)
class ToolCall:
    tool_call_id: str
    tool_name: str
    tool_args: dict[str, Any]

    def dump_json(self) -> str:
        return dumps(to_jsonable({"tool_call_id": self.tool_call_id, "tool_name": self.tool_name, "tool_args": self.tool_args}), ensure_ascii=False)


@dataclass(slots=True, kw_only=True)
class ToolCallResult:
    tool_call_id: str
    content: Any
    abort: bool = False

    @classmethod
    def aborted(cls, tool_call_id: str, reason: str) -> ToolCallResult:
        return cls(tool_call_id=tool_call_id, abort=True, content=f"Tool call aborted: {reason}")

    def dump_json(self) -> str:
        return dumps({"tool_call_id": self.tool_call_id, "content": to_jsonable(self.content)}, ensure_ascii=False)


class StopReason(StrEnum):
    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    LENGTH = "length"
    ERROR = "error"


@dataclass(slots=True, kw_only=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0


@dataclass(slots=True, kw_only=True)
class LLMResponseBlock(ABC):
    meta: dict[str, Any] = field(default_factory=dict)

    @abstractmethod
    def content_str(self) -> str: ...

    @abstractmethod
    def item_type(self) -> DialogItemType: ...

    def to_dialog_item(self, role: DialogRole, user: str, origin: DialogOrigin, previous_item_id: int | None = None) -> DialogItem:
        return DialogItem(
            content=self.content_str(),
            item_type=self.item_type(),
            role=role,
            user=user,
            origin=origin,
            previous_item_id=previous_item_id,
            meta=dict(self.meta),
        )


@dataclass(slots=True, kw_only=True)
class LLMResponseTextBlock(LLMResponseBlock):
    content: str

    def content_str(self) -> str:
        return self.content

    def item_type(self) -> DialogItemType:
        return DialogItemType.OUTPUT


@dataclass(slots=True, kw_only=True)
class LLMResponseImageBlock(LLMResponseBlock):
    ref: str
    ext: str
    content: bytes | None = None

    def content_str(self) -> str:
        return dumps({"image": {"ref": self.ref, "ext": self.ext}}, ensure_ascii=False)

    def item_type(self) -> DialogItemType:
        return DialogItemType.IMAGE_OUTPUT


@dataclass(slots=True, kw_only=True)
class LLMResponseFileBlock(LLMResponseBlock):
    ref: str
    ext: str
    content: bytes | None = None

    def content_str(self) -> str:
        return dumps({"file": {"ref": self.ref, "ext": self.ext}}, ensure_ascii=False)

    def item_type(self) -> DialogItemType:
        return DialogItemType.FILE_OUTPUT


@dataclass(slots=True, kw_only=True)
class LLMResponseReasoningBlock(LLMResponseBlock):
    content: str

    def content_str(self) -> str:
        return self.content

    def item_type(self) -> DialogItemType:
        return DialogItemType.REASONING


@dataclass(slots=True, kw_only=True)
class LLMResponseToolCallBlock(LLMResponseBlock):
    tool_call_id: str
    tool_name: str
    tool_args: dict[str, Any]

    def content_str(self) -> str:
        return dumps({"tool_call_id": self.tool_call_id, "tool_name": self.tool_name, "tool_args": self.tool_args}, ensure_ascii=False)

    def item_type(self) -> DialogItemType:
        return DialogItemType.TOOL_CALL


@dataclass(slots=True, kw_only=True)
class StreamDelta:
    content: str
    delta_type: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, kw_only=True)
class StreamEnd:
    stop_reason: StopReason = StopReason.END_TURN
    usage: Usage | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, kw_only=True)
class LLMResponse:
    """Complete LLM response composed of typed content blocks
    with stop reason and usage statistics."""

    stop_reason: StopReason = StopReason.END_TURN
    content: list[LLMResponseBlock] = field(default_factory=list)
    usage: Usage | None = None
    raw: Any = None
    meta: dict[str, Any] = field(default_factory=dict)


class LLMAdapter(AbstractService):
    """
    Abstract LLM adapter.
    Subclasses implement ask_llm() as an async generator yielding
    StreamDelta, LLMResponseBlock, and StreamEnd events.
    """

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "__abstractmethods__", None):
            setattr(cls, LLM_ADAPTER_ATTRIBUTE, True)

    def ask_llm(self, ctx: BeforeLlmCallCtx, *, stream: bool = False) -> AsyncIterator[StreamDelta | LLMResponseBlock | StreamEnd]:
        raise NotImplementedError


class PythonLLMAdapterSource(PythonServiceSource):
    def __init__(self) -> None:
        super().__init__(base_type=LLMAdapter, marker_attribute=LLM_ADAPTER_ATTRIBUTE, id_prefix="llm_adapter")


class LLMAdapterManager(ServiceInstanceManager[LLMAdapter]):
    """
    Manages LLM adapter instances. Adapter selection logic is todo
    """

    base_type = LLMAdapter
    marker_attribute = LLM_ADAPTER_ATTRIBUTE
    id_prefix = "llm_adapter"

    def __init__(self, agent: Agent, **kwargs: object) -> None:
        super().__init__(agent, source=PythonLLMAdapterSource(), **kwargs)

    @property
    def _active(self) -> LLMAdapter:
        instances = self.instances
        if instances:
            return instances[0]
        raise RuntimeError("No LLM adapters registered")

    def ask_llm(self, ctx: BeforeLlmCallCtx, *, stream: bool = False) -> AsyncIterator[StreamDelta | LLMResponseBlock | StreamEnd]:
        return self._active.ask_llm(ctx, stream=stream)


def ext_to_mime(ext: str) -> str:
    mime_type, _ = guess_type(f"file.{ext}")
    if not mime_type and ext == "webp":
        return "image/webp"
    return mime_type or "application/octet-stream"


async def resolve_file_uri(storage: FileStorage | None, item: DialogItem) -> str:
    if storage is None:
        raise RuntimeError("FileStorage is required for image/file items")
    item_map = {
        DialogItemType.FILE_INPUT: "file",
        DialogItemType.FILE_OUTPUT: "file",
        DialogItemType.IMAGE_INPUT: "image",
        DialogItemType.IMAGE_OUTPUT: "image",
    }
    if item.item_type not in item_map:
        return ""
    try:
        data = loads(item.content).get(item_map[item.item_type], {})
        ref = str(data.get("ref", ""))
        ext = str(data.get("ext", "")).lstrip(".").lower()
        if not ref:
            return ""
        if ref.startswith("http"):
            try:
                rq = await storage.agent.http_client.head(ref, follow_redirects=True, timeout=30)
                rq.raise_for_status()
                return ref
            except HTTPError:
                return ""
        raw_bytes = await storage.get(ref)
        if not raw_bytes:
            return ""
        mime = ext_to_mime(ext) if ext else "application/octet-stream"
        return f"data:{mime};base64,{base64.b64encode(raw_bytes).decode('utf-8')}"
    except KeyError:
        return ""
