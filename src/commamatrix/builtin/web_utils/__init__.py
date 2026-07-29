# builtin/web_utils/__init__.py

"""Built-in web search tools.

Importing this package makes ``web_utils.search`` available as an agent tool.
"""

from __future__ import annotations

from . import instructions, tools
from .security import validate_url
from .tools import search, search_max_limit, search_max_output_chars, search_timeout

__all__ = [
    "instructions",
    "search",
    "search_max_limit",
    "search_max_output_chars",
    "search_timeout",
    "tools",
    "validate_url",
]
