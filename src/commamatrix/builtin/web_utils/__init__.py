# builtin/web_utils/__init__.py

"""Built-in web search and extraction tools.

Importing this package makes ``web_utils.search`` and ``web_utils.fetch``
available as agent tools.
"""

from __future__ import annotations

from . import instructions, tools
from .security import validate_url
from .tools import (
    fetch,
    fetch_max_output_chars,
    fetch_max_redirects,
    fetch_max_response_bytes,
    fetch_timeout,
    search,
    search_max_limit,
    search_max_output_chars,
    search_timeout,
)

__all__ = [
    "fetch",
    "fetch_max_output_chars",
    "fetch_max_redirects",
    "fetch_max_response_bytes",
    "fetch_timeout",
    "instructions",
    "search",
    "search_max_limit",
    "search_max_output_chars",
    "search_timeout",
    "tools",
    "validate_url",
]
