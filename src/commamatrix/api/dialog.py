from __future__ import annotations

from abc import ABC
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Optional
from pydantic import BaseModel, Field


DEFAULT_PLATFORM = 'unknown'


class DialogItemType(StrEnum):
    INPUT = 'input'
    IMAGE_INPUT = 'image_input'
    FILE_INPUT = 'file_input'
    OUTPUT = 'output'
    IMAGE_OUTPUT = 'image_output'
    FILE_OUTPUT = 'file_output'
    TOOL_CALL = 'tool_call'
    TOOL_CALL_RESULT = 'tool_call_result'


class DialogRole(StrEnum):
    SYSTEM = 'system'
    DEVELOPER = 'developer'
    USER = 'user'
    ASSISTANT = 'assistant'
    TOOL = 'tool'


class DialogOrigin(ABC, BaseModel):
    """
    A set of field-value pairs encoding some kind of communication channel.
    Any context has a 'platform', additinal fields may appear.

    Usage:
    class TelegramChatContext(DialogOrigin):
        platform = 'telegram'
        chat_id: int
    """
    model_config = {'frozen': True}
    platform: str = DEFAULT_PLATFORM

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not getattr(cls, '__abstractmethods__', None):
            ORIGIN_REGISTRY[cls.__name__] = cls


ORIGIN_REGISTRY: dict[str, type[DialogOrigin]] = {}


class DialogItem(BaseModel):
    """
    An atomic event in dialog. One row in database. One 'content' block.
    Corresponds to LLMResponseBlock abstraction
    (for TOOL_CALL/TOOL_CALL_RESULT/IMAGE_*/FILE_* content is serialized object JSON)
    """
    item_id: Optional[int] = None
    content: str
    item_type: DialogItemType
    user: str
    """
    platform-specific identifier of user that triggered a chain of events.
     
    examples: 'tg:11111', 'vk:22334455'
    """
    role: DialogRole
    origin: DialogOrigin
    previous_item_id: Optional[int] = None
    external_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    meta: dict[str, Any] = Field(default_factory=lambda: {})

