# presets.py

"""Named extension bundles for composing CommaMatrix agents."""

from .utils import FP


essentials = [
    f"{FP}.builtin.llm_http_adapter",
    f"{FP}.builtin.codeact",
    f"{FP}.builtin.self_extension",
    f"{FP}.builtin.web_utils",
    f"{FP}.builtin.data_tools",
    f"{FP}.builtin.storage_utils",
    f"{FP}.builtin.multi_dialog",
    # f"{FP}.builtin.multi_user",
    f"{FP}.builtin.http_connector",
    f"{FP}.builtin.subagent",
    f"{FP}.builtin.planner",
]

__all__ = [
    "essentials"
]

