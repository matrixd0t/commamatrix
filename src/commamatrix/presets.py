# presets.py

"""Named extension bundles for composing CommaMatrix agents."""

from .utils import FP


essentials = [
    f"{FP}.builtin.llm_http_adapter",
    f"{FP}.builtin.codeact",
    f"{FP}.builtin.self_extension",
    f"{FP}.builtin.web_utils",
    f"{FP}.builtin.data_tools",
    f"{FP}.builtin.multi_dialog",
    f"{FP}.builtin.http_connector"
]

__all__ = [
    "essentials"
]

