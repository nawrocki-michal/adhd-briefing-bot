"""Testy auto-discovery feedu RSS (bez sieci — _download zmockowany)."""


from adhd_briefing.sources.discovery import discover_feed

SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Feed</title>
  <item><title>A</title><link>https://x/a</link></item>
</channel></rss>"""


async def test_discover_from_link_tag(monkeypatch):
    html = (
        '<html><head>'
        '<link rel="alternate" type="application/rss+xml" href="/feed.xml">'
        "</head></html>"
    )

    async def _dl(url, timeout):
        return html if url == "https://site.com/blog" else None

    monkeypatch.setattr("adhd_briefing.sources.discovery._download", _dl)
    assert await discover_feed("https://site.com/blog") == "https://site.com/feed.xml"


async def test_discover_resolves_absolute_href(monkeypatch):
    html = (
        '<html><head>'
        '<link rel="alternate" type="application/atom+xml" '
        'href="https://cdn.site.com/atom">'
        "</head></html>"
    )

    async def _dl(url, timeout):
        return html if url.startswith("https://site.com") else None

    monkeypatch.setattr("adhd_briefing.sources.discovery._download", _dl)
    assert await discover_feed("https://site.com") == "https://cdn.site.com/atom"


async def test_discover_fallback_common_path(monkeypatch):
    async def _dl(url, timeout):
        if url == "https://site.com":
            return "<html><head></head></html>"  # brak <link>
        if url == "https://site.com/feed":
            return SAMPLE_RSS
        return None

    monkeypatch.setattr("adhd_briefing.sources.discovery._download", _dl)
    assert await discover_feed("https://site.com") == "https://site.com/feed"


async def test_discover_returns_none_when_nothing(monkeypatch):
    async def _dl(url, timeout):
        return "<html><head></head></html>" if url == "https://x.com" else None

    monkeypatch.setattr("adhd_briefing.sources.discovery._download", _dl)
    assert await discover_feed("https://x.com") is None
