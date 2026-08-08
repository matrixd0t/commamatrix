# builtin/web_utils/__init__.py

"""Built-in web search tools.

Importing this package makes ``web_utils.search`` available as an agent tool.
"""

from __future__ import annotations

from . import instructions, tools
from .security import validate_url
from .tools import (
    search,
    web_search_max_limit,
    web_search_max_output_chars,
    web_search_timeout,
)

__all__ = [
    "instructions",
    "search",
    "tools",
    "validate_url",
    "web_search_max_limit",
    "web_search_max_output_chars",
    "web_search_timeout",
]
