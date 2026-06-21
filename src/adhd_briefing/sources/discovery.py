"""Auto-discovery feedu RSS/Atom z adresu strony.

Pozwala użytkownikowi podać zwykły adres bloga (np. homepage Substacka lub nawet
pojedynczy artykuł — strony zwykle linkują feed publikacji), a agent sam znajdzie
adres feedu. Kolejność: <link rel="alternate"> w HTML → typowe ścieżki (/feed, ...).
"""

import asyncio
from html.parser import HTMLParser
from urllib.parse import urljoin

import feedparser
import httpx

_USER_AGENT = "Mozilla/5.0 (compatible; ADHDBriefingBot/0.1)"
_FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/feed+json")
_COMMON_PATHS = ("/feed", "/rss", "/feed.xml", "/rss.xml", "/atom.xml")


class _FeedLinkParser(HTMLParser):
    """Zbiera href-y z <link rel="alternate" type="application/rss+xml">."""

    def __init__(self) -> None:
        super().__init__()
        self.feeds: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag != "link":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        if "alternate" in a.get("rel", "").lower() and a.get("type", "").lower() in _FEED_TYPES:
            if a.get("href"):
                self.feeds.append(a["href"])


async def discover_feed(url: str, *, timeout: float = 15.0) -> str | None:
    """Zwraca URL feedu dla danej strony albo None."""
    html = await _download(url, timeout)
    if html:
        parser = _FeedLinkParser()
        try:
            parser.feed(html)
        except Exception:
            parser.feeds = []
        if parser.feeds:
            return urljoin(url, parser.feeds[0])

    # Fallback: typowe ścieżki feedu (zweryfikowane realnym parsowaniem).
    base = url.rstrip("/")
    for suffix in _COMMON_PATHS:
        candidate = base + suffix
        if await _is_feed(candidate, timeout):
            return candidate
    return None


async def _download(url: str, timeout: float) -> str | None:
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers={"User-Agent": _USER_AGENT}
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text
    except Exception:
        return None


async def _is_feed(url: str, timeout: float) -> bool:
    text = await _download(url, timeout)
    if not text:
        return False
    parsed = await asyncio.to_thread(feedparser.parse, text)
    return bool(getattr(parsed, "entries", None))
