"""RSSProvider — pozyskiwanie artykułów z feedów RSS/Atom przez feedparser."""

import asyncio
from datetime import datetime, timezone
from time import mktime

import feedparser

from adhd_briefing.models import Article
from adhd_briefing.sources.base import SourceProvider
from adhd_briefing.sources.text import strip_html


class RSSProvider(SourceProvider):
    """Parsuje feed RSS/Atom. feedparser jest sync → owinięty w to_thread."""

    async def fetch(self, url: str) -> list[Article]:
        try:
            feed = await asyncio.to_thread(feedparser.parse, url)
        except Exception:
            return []

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
