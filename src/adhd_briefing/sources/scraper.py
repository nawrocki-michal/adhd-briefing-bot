"""ScraperProvider — fallback dla stron bez RSS, przez trafilatura."""

import asyncio

import httpx
import trafilatura

from adhd_briefing.models import Article
from adhd_briefing.sources.base import SourceProvider

_USER_AGENT = "Mozilla/5.0 (compatible; ADHDBriefingBot/0.1; +https://github.com)"


class ScraperProvider(SourceProvider):
    """Pobiera HTML (httpx async) i wyciąga czysty tekst (trafilatura w to_thread)."""

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout

    async def fetch(self, url: str) -> list[Article]:
        html = await self._download(url)
        if not html:
            return []

        text = await asyncio.to_thread(
            trafilatura.extract,
            html,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
        )
        if not text:
            return []

        title = await asyncio.to_thread(self._extract_title, html)
        return [
            Article(
                url=url,
                title=title or url,
                content=text,
                source_url=url,
            )
        ]

    async def _download(self, url: str) -> str | None:
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers={"User-Agent": _USER_AGENT},
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.text
        except Exception:
            return None

    @staticmethod
    def _extract_title(html: str) -> str | None:
        try:
            meta = trafilatura.extract_metadata(html)
        except Exception:
            return None
        return getattr(meta, "title", None) if meta else None
