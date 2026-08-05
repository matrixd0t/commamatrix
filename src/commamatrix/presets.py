# presets.py

"""Named extension bundles for composing CommaMatrix agents."""

from .utils import FP


_minimal = [
    f"{FP}.builtin.instructions.default_instruction",
    f"{FP}.builtin.llm_http_adapter",
    f"{FP}.builtin.http_connector",
]

_assistant = [
    *_minimal,
    f"{FP}.builtin.web_utils",
    f"{FP}.builtin.data_tools",
    f"{FP}.builtin.storage_utils",
    f"{FP}.builtin.multi_dialog",
]


minimal = [*_minimal]

assistant = [*_assistant]


coding = [
    *assistant,
    f"{FP}.builtin.instructions.coding",
    f"{FP}.builtin.filesystem",
    f"{FP}.builtin.codeact",
    f"{FP}.builtin.apply_patch",
    f"{FP}.builtin.self_extension",
    f"{FP}.builtin.instructions.coding",
]

deep_research = [
    *assistant,
    f"{FP}.builtin.codeact",
    f"{FP}.builtin.subagent",
    f"{FP}.builtin.instructions.deep_research",
]

roleplay = [
    f"{FP}.builtin.llm_http_adapter",
    f"{FP}.builtin.http_connector",
    f"{FP}.builtin.multi_user",
    f"{FP}.builtin.instructions.roleplay",
]

data_analysis = [
    *assistant,
    f"{FP}.builtin.filesystem",
    f"{FP}.builtin.codeact",
    f"{FP}.builtin.instructions.data_analysis",
]

automation = [
    *assistant,
    f"{FP}.builtin.filesystem",
    f"{FP}.builtin.codeact",
    f"{FP}.builtin.planner",
    f"{FP}.builtin.self_extension",
    f"{FP}.builtin.instructions.automation",
]


__all__ = [
    "assistant",
    "automation",
    "coding",
    "data_analysis",
    "deep_research",
    "essentials",
    "minimal",
    "roleplay",
]
