"""Pluggable web search providers."""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class WebSearchResult:
    title: str
    body: str
    url: str


class WebSearchProvider(ABC):
    """Abstract web search interface."""

    @abstractmethod
    async def search(self, query: str, max_results: int = 3) -> list[WebSearchResult]:
        ...


class DuckDuckGoProvider(WebSearchProvider):
    """DuckDuckGo search via duckduckgo-search library."""

    async def search(self, query: str, max_results: int = 3) -> list[WebSearchResult]:
        from duckduckgo_search import DDGS

        loop = asyncio.get_event_loop()
        try:
            raw = await loop.run_in_executor(
                None,
                lambda: DDGS().text(query, max_results=max_results),
            )
        except Exception as e:
            logger.warning(f"DuckDuckGo search failed: {e}")
            return []

        return [
            WebSearchResult(
                title=r.get("title", ""),
                body=r.get("body", ""),
                url=r.get("href", ""),
            )
            for r in raw
        ]


_PROVIDERS: dict[str, type[WebSearchProvider]] = {
    "duckduckgo": DuckDuckGoProvider,
}


def create_web_search_provider(name: str = "duckduckgo") -> WebSearchProvider:
    """Factory for web search providers. Extend _PROVIDERS for new engines."""
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ValueError(f"Unknown web search provider: {name!r}. Available: {list(_PROVIDERS)}")
    return cls()
