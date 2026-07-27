# builtin/web_utils/tools.py

"""Web search and page extraction tools."""

from __future__ import annotations

import asyncio
from ddgs import DDGS
from typing import TYPE_CHECKING

from ...components.config import ConfigField
from ...components.hook import BeforeToolCallCtx
from ...components.tool import tool
from .security import validate_url

if TYPE_CHECKING:
    from httpx import AsyncClient

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

fetch_timeout = ConfigField[int](
    name="web_utils.fetch_timeout",
    default=30,
    description="Timeout in seconds for a single HTTP request during fetch.",
)

fetch_max_response_bytes = ConfigField[int](
    name="web_utils.fetch_max_response_bytes",
    default=5_242_880,
    description="Maximum byte count for a downloaded web page.",
)

fetch_max_output_chars = ConfigField[int](
    name="web_utils.fetch_max_output_chars",
    default=40_000,
    description="Maximum character count for the fetch tool output.",
)

fetch_max_redirects = ConfigField[int](
    name="web_utils.fetch_max_redirects",
    default=5,
    description="Maximum number of HTTP redirects to follow during fetch.",
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


def _extract_content(html: str) -> str:
    from trafilatura import extract
    return extract(html, output_format="markdown", include_links=True, include_tables=True) or ""


async def do_fetch(url: str, timeout: int, max_bytes: int, max_output: int, max_redirects: int, client: AsyncClient) -> str:
    url = url.strip()
    if not url:
        return "Error: url must not be empty."

    try:
        validate_url(url)
    except ValueError as exc:
        return f"Error: {exc}"

    current_url = url
    text: str | None = None

    for _ in range(max_redirects + 1):
        try:
            resp = await client.get(current_url, timeout=timeout, follow_redirects=False)
        except Exception as exc:
            return f"Error: HTTP request failed: {exc}"

        if resp.is_redirect:
            location = resp.headers.get("location")
            if not location:
                return "Error: redirect without Location header."
            next_url = str(resp.url.join(location))
            try:
                validate_url(next_url)
            except ValueError as exc:
                return f"Error: redirect target blocked — {exc}"
            current_url = next_url
            continue

        if resp.status_code >= 400:
            return f"Error: HTTP {resp.status_code}."

        content_length = resp.headers.get("content-length")
        if content_length and int(content_length) > max_bytes:
            return "Error: response exceeds the configured size limit."

        body = resp.content
        if len(body) > max_bytes:
            return "Error: response exceeds the configured size limit."

        charset = resp.charset_encoding or "utf-8"
        try:
            text = body.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            text = body.decode("utf-8", errors="replace")
        break

    if text is None:
        return "Error: too many redirects."

    content_type = (resp.headers.get("content-type") or "").lower()
    is_html = "html" in content_type or "xhtml" in content_type

    if is_html:
        try:
            markdown = await asyncio.to_thread(_extract_content, text)
        except Exception as exc:
            return f"Error: content extraction failed: {exc}"
        if not markdown:
            return "No readable content found at this URL."
        header = f"Source: {current_url}\n\n"
        output = header + markdown
    else:
        output = f"Source: {current_url}\nContent-Type: {content_type}\n\n```\n{text.strip()}\n```"

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

    if limit < 1:
        return f"Error: limit must be between 1 and {max_limit}."

    config = ctx.run.agent.config
    return await do_search(
        query=query,
        limit=min(limit, config.get(search_max_limit)),
        sites=sites,
        timeout=config.get(search_timeout),
        max_output=config.get(search_max_output_chars)
    )


@tool(alias="web")
async def fetch(url: str, *, ctx: BeforeToolCallCtx) -> str:
    """Fetch a web page and extract its main content as Markdown.

    Args:
        url: URL of the page to fetch (http or https).
    """
    config = ctx.run.agent.config
    return await do_fetch(
        url=url,
        timeout=config.get(fetch_timeout),
        max_bytes=config.get(fetch_max_response_bytes),
        max_output=config.get(fetch_max_output_chars),
        max_redirects=config.get(fetch_max_redirects),
        client=ctx.run.agent.http_client
    )



