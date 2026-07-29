# builtin/web_utils/tools.py

"""Web search tool."""

from __future__ import annotations

import asyncio
import json

from ddgs import DDGS

from ...components.config import ConfigField
from ...components.hook import BeforeToolCallCtx
from ...components.tool import tool

search_max_limit = ConfigField[int](
    name="web_utils.search_max_limit",
    default=50,
    description="Maximum number of search results allowed.",
)

search_timeout = ConfigField[int](
    name="web_utils.search_timeout",
    default=10,
    description="Timeout in seconds for a single DDGS text search.",
)

search_max_output_chars = ConfigField[int](
    name="web_utils.search_max_output_chars",
    default=20_000,
    description="Maximum character count for the search tool output.",
)


async def do_search(query: str, limit: int, sites: list[str] | None, timeout: int, max_output: int) -> str:
    query = query.strip()
    if not query:
        return "Error: query must not be empty."

    # When sites filter is active, fetch more results to have enough after filtering
    fetch_limit = limit * 5 if sites else limit

    def _do_search() -> list[dict[str, str]]:
        return DDGS(timeout=timeout).text(query, max_results=fetch_limit)

    try:
        results = await asyncio.to_thread(_do_search)
    except Exception as exc:
        return f"Error: web search failed: {exc}"

    if not results:
        return "No search results found for the query."

    if sites:
        sites_lower = [s.lower() for s in sites]
        matched = []
        for r in results:
            if len(matched) >= limit:
                break
            url = (r.get("href") or r.get("url") or "").lower()
            if any(site in url for site in sites_lower):
                matched.append(r)
        while len(matched) < limit:
            matched.append(results.pop(0))
        results = matched[:limit]
    else:
        results = results[:limit]

    blocks: list[str] = []
    for r in results:
        title = (r.get("title") or "").strip()
        url = r.get("href") or r.get("url") or ""
        snippet = (r.get("body") or "").strip()
        if not url:
            continue
        parts: list[str] = []
        if title:
            parts.append(f"### {title}")
        parts.append(url)
        if snippet:
            parts.append(f"\n{snippet}")
        blocks.append("\n".join(parts))

    if not blocks:
        return "No search results found for the query."

    output = "\n\n---\n\n".join(blocks)
    if len(output) > max_output:
        output = output[:max_output] + "\n\n[truncated]"
    return output


@tool(alias="web")
async def search(query: str, limit: int = 5, sites: list[str] | None = None, *, ctx: BeforeToolCallCtx) -> str:
    """Search the web and return formatted results.

    Args:
        query: Search query string.
        limit: Maximum number of results to return.
        sites: Optional list of url fragments to prioritize results (example: 'pypi')
    """

    config = ctx.run.agent.config

    if isinstance(limit, str):
        try:
            limit = int(limit.strip())
        except ValueError:
            return "Error: limit must be an integer."
    if not isinstance(limit, int):
        return "Error: limit must be an integer."

    if isinstance(sites, str):
        try:
            parsed_sites = json.loads(sites)
        except json.JSONDecodeError:
            return "Error: sites must be a JSON array of strings."
        if not isinstance(parsed_sites, list) or not all(
            isinstance(site, str) for site in parsed_sites
        ):
            return "Error: sites must be a JSON array of strings."
        sites = parsed_sites
    elif sites is not None and (
        not isinstance(sites, list) or not all(isinstance(site, str) for site in sites)
    ):
        return "Error: sites must be a list of strings."

    max_limit = config.get(search_max_limit)
    if limit < 1:
        return f"Error: limit must be between 1 and {max_limit}."
    return await do_search(
        query=query,
        limit=min(limit, max_limit),
        sites=sites,
        timeout=config.get(search_timeout),
        max_output=config.get(search_max_output_chars),
    )
