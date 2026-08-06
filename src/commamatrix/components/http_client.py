# components/http_client.py

from __future__ import annotations

from typing import TYPE_CHECKING

from httpx2 import AsyncClient

from .config import ConfigField
from ..core.classes.lifecycle_registry import lifecycle_component
from ..core.classes.service import AbstractService

if TYPE_CHECKING:
    from ..core.agent.agent import Agent


HTTP_BASE_HEADERS: dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip",
    "Connection": "keep-alive",
}

http_default_headers = ConfigField[dict[str, str] | None](
    name="http_default_headers",
    default=None,
    description="Extra headers merged into the agent HTTP client defaults",
)

http_timeout = ConfigField[int](
    name="http_timeout",
    default=120,
    description="Default timeout in seconds for the agent HTTP client",
)


@lifecycle_component(key="http_client", priority=350, after="file_storage")
class HttpClient(AbstractService):
    """Own the shared lazy HTTP client for one agent."""

    def __init__(self, agent: Agent) -> None:
        super().__init__(agent)
        self._client: AsyncClient | None = None

    @property
    def client(self) -> AsyncClient:
        if self._client is None:
            headers = dict(HTTP_BASE_HEADERS)
            extra = self.config.get(http_default_headers)
            if extra:
                headers.update(extra)
            self._client = AsyncClient(
                headers=headers,
                follow_redirects=True,
                timeout=self.config.get(http_timeout),
            )
            self.logger.info("Shared HTTP client initialized timeout=%s", self.config.get(http_timeout))
        return self._client

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            self.logger.info("Shared HTTP client closed")


__all__ = [
    "HTTP_BASE_HEADERS",
    "HttpClient",
    "http_default_headers",
    "http_timeout",
]
