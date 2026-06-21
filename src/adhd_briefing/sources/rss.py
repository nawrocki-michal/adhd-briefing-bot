"""RSSProvider — pozyskiwanie artykułów z feedów RSS/Atom przez feedparser."""

import asyncio
from datetime import datetime, timezone
from time import mktime

import feedparser
import httpx

from adhd_briefing.models import Article
from adhd_briefing.sources.base import SourceProvider
from adhd_briefing.sources.text import strip_html

_USER_AGENT = "Mozilla/5.0 (compatible; ADHDBriefingBot/0.1)"


class RSSProvider(SourceProvider):
    """Parsuje feed RSS/Atom.

    Feed pobieramy przez httpx z UA przeglądarki (wiele serwisów — Substack,
    O'Reilly — blokuje domyślny UA feedparsera 403), a treść parsujemy feedparserem
    (sync → owinięty w to_thread).
    """

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout

    async def fetch(self, url: str) -> list[Article]:
        text = await self._download(url)
        if text is None:
            return []

        feed = await asyncio.to_thread(feedparser.parse, text)
        # bozo=1 oznacza problem z parsowaniem; akceptujemy jeśli są wpisy
        if not getattr(feed, "entries", None):
            return []

        articles: list[Article] = []
        for entry in feed.entries:
            articles.append(
                Article(
                    url=entry.get("link", url),
                    title=strip_html(entry.get("title", "")),
                    content=self._extract_content(entry),
                    source_url=url,
                    published_at=self._parse_date(entry),
                )
            )
        return articles

    @staticmethod
    def _extract_content(entry) -> str:
        raw = ""
        if entry.get("content"):
            raw = entry["content"][0].get("value", "")
        elif entry.get("summary"):
            raw = entry["summary"]
        return strip_html(raw)

    @staticmethod
    def _parse_date(entry) -> datetime | None:
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed:
            return datetime.fromtimestamp(mktime(parsed), tz=timezone.utc)
        return None

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
