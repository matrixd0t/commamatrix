# api/__init__.py

from .dialog import DialogItem, DialogOrigin, DialogItemType, DialogRole, ORIGIN_REGISTRY
from .connector import Connector, CONNECTOR_REGISTRY, ConnectorRegistry, ListensEvents, OnEvent
from .storage import Storage
from .file_storage import FileStorage
from .llm_adapter import (
    LLMAdapter, LLMResponse, LLMResponseTextBlock, LLMResponseImageBlock, LLMResponseFileBlock, LLMResponseToolCallBlock, LLMResponseBlock,
    StopReason, ToolCall, ToolCallResult, LLMError, LLMResponseError, LLMTruncatedError,
)
from .config import ConfigField
from ..core.extension_runtime import ExtensionSource, ExtensionDescriptor, ExtensionRuntime
from .tool import tool, ToolSource, ToolDescriptor, DEFAULT_TOOL_SEARCH_AMOUNT
from .hooks import (
    Hook, HookEventType, HookDescriptor, HookSource,
    RunCtx,
    OnParsedCtx, on_parsed,
    BeforeRunCtx, before_run,
    BeforeLlmCallCtx, before_llm_call,
    BeforeToolCallCtx, before_tool_call,
    AfterToolCallCtx, after_tool_call,
    AfterLlmCallCtx, after_llm_call,
    BeforeSendCtx, before_send,
    OnErrorCtx, on_error,
    AfterRunCtx, after_run
)

__all__ = [
    'DialogItem', 'DialogOrigin', 'DialogItemType', 'DialogRole', 'ORIGIN_REGISTRY',
    'Connector', 'CONNECTOR_REGISTRY', 'ConnectorRegistry', 'ListensEvents', 'OnEvent',
    'Storage', 'FileStorage',
    'LLMAdapter', 'LLMResponse', 'LLMResponseTextBlock', 'LLMResponseImageBlock', 'LLMResponseFileBlock', 'LLMResponseToolCallBlock', 'LLMResponseBlock',
    'StopReason', 'ToolCall', 'ToolCallResult', 'LLMError', 'LLMResponseError', 'LLMTruncatedError',
    'ConfigField',
    'ExtensionSource', 'ExtensionDescriptor', 'ExtensionRuntime',
    'tool', 'ToolSource', 'ToolDescriptor', 'DEFAULT_TOOL_SEARCH_AMOUNT',
    'Hook', 'HookEventType', 'HookDescriptor', 'HookSource', 'RunCtx',
    'OnParsedCtx', 'on_parsed',
    'BeforeRunCtx', 'before_run',
    'BeforeLlmCallCtx', 'before_llm_call',
    'BeforeToolCallCtx', 'before_tool_call',
    'AfterToolCallCtx', 'after_tool_call',
    'AfterLlmCallCtx', 'after_llm_call',
    'BeforeSendCtx', 'before_send',
    'OnErrorCtx', 'on_error',
    'AfterRunCtx', 'after_run'
]
