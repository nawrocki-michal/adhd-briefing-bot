"""Testy jednostkowe warstwy SourceProvider (bez sieci — mocki)."""

import pytest

from adhd_briefing.models import Article
from adhd_briefing.sources import RSSProvider, ScraperProvider, get_provider
from adhd_briefing.sources.factory import fetch_articles
from adhd_briefing.sources.text import strip_html

# --- strip_html ---


def test_strip_html_removes_tags():
    assert strip_html("<p>Hello <b>world</b></p>") == "Hello world"


def test_strip_html_unescapes_entities():
    assert strip_html("Tom &amp; Jerry") == "Tom & Jerry"


def test_strip_html_empty():
    assert strip_html("") == ""


def test_strip_html_drops_scripts():
    assert "alert" not in strip_html("<div>ok<script>alert(1)</script></div>")


# --- get_provider auto-detekcja ---


@pytest.mark.parametrize(
    "url,expected_rss",
    [
        ("https://example.com/feed", True),
        ("https://example.com/rss.xml", True),
        ("https://blog.example.com/atom.xml", True),
        ("https://www.oreilly.com/radar/some-article/", False),
        ("https://evilmartians.com/chronicles/some-post", False),
    ],
)
def test_get_provider_classification(url, expected_rss):
    provider = get_provider(url)
    assert isinstance(provider, RSSProvider) == expected_rss


# --- RSSProvider z mockiem feedparser ---

SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Test Feed</title>
  <item>
    <title>First &amp; Best</title>
    <link>https://example.com/a</link>
    <description>&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;</description>
    <pubDate>Wed, 01 Jan 2025 12:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Second</title>
    <link>https://example.com/b</link>
    <description>Plain text</description>
  </item>
</channel></rss>"""


async def test_rss_provider_parses_entries(monkeypatch):
    async def _dl(self, url):
        return SAMPLE_RSS

    monkeypatch.setattr(RSSProvider, "_download", _dl)

    articles = await RSSProvider().fetch("https://example.com/feed")
    assert len(articles) == 2
    assert articles[0].title == "First & Best"
    assert articles[0].content == "Hello world"  # HTML wyczyszczony
    assert articles[0].url == "https://example.com/a"
    assert articles[0].published_at is not None
    assert articles[1].published_at is None


async def test_rss_provider_empty_on_garbage(monkeypatch):
    async def _dl(self, url):
        return "<html><body>not a feed</body></html>"

    monkeypatch.setattr(RSSProvider, "_download", _dl)
    assert await RSSProvider().fetch("https://example.com") == []


async def test_rss_provider_empty_on_download_failure(monkeypatch):
    async def _dl(self, url):
        return None

    monkeypatch.setattr(RSSProvider, "_download", _dl)
    assert await RSSProvider().fetch("https://example.com/feed") == []


# --- ScraperProvider z mockiem httpx + trafilatura ---

SAMPLE_HTML = """<html><head><title>Real Article Title</title></head>
<body><nav>menu</nav><article><p>To jest główna treść artykułu o znaczeniu.</p>
<p>Drugi akapit z konkretną informacją.</p></article><footer>stopka</footer></body></html>"""


async def test_scraper_provider_extracts_clean_text(monkeypatch):
    class _FakeResp:
        text = SAMPLE_HTML

        def raise_for_status(self):
            pass

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return _FakeResp()

    monkeypatch.setattr("adhd_briefing.sources.scraper.httpx.AsyncClient", _FakeClient)

    articles = await ScraperProvider().fetch("https://example.com/article")
    assert len(articles) == 1
    art = articles[0]
    assert "główna treść" in art.content
    assert "menu" not in art.content  # nav usunięty
    assert "stopka" not in art.content  # footer usunięty
    assert art.title == "Real Article Title"


async def test_scraper_provider_empty_on_http_error(monkeypatch):
    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            raise RuntimeError("connection failed")

    monkeypatch.setattr("adhd_briefing.sources.scraper.httpx.AsyncClient", _FakeClient)
    assert await ScraperProvider().fetch("https://example.com") == []


# --- fetch_articles fallback ---


async def test_fetch_articles_falls_back_to_rss(monkeypatch):
    """Strona bez wykrytego feedu → RSSProvider wprost (krok 3) zwraca artykuł."""

    async def _no_feed(url, **kwargs):
        return None

    async def _rss_hit(self, url):
        return [Article(url=url, title="t", content="c", source_url=url)]

    monkeypatch.setattr("adhd_briefing.sources.factory.discover_feed", _no_feed)
    monkeypatch.setattr(RSSProvider, "fetch", _rss_hit)

    articles = await fetch_articles("https://example.com/article")
    assert len(articles) == 1
    assert articles[0].title == "t"


async def test_fetch_articles_discovers_feed(monkeypatch):
    """Strona → auto-discovery znajduje feed → RSSProvider na feedzie."""

    async def _discover(url, **kwargs):
        return "https://example.com/feed.xml"

    async def _rss(self, url):
        if "feed" in url:
            return [Article(url="https://a", title="z feedu", content="c", source_url=url)]
        return []

    monkeypatch.setattr("adhd_briefing.sources.factory.discover_feed", _discover)
    monkeypatch.setattr(RSSProvider, "fetch", _rss)

    articles = await fetch_articles("https://example.com/blog")
    assert len(articles) == 1
    assert articles[0].title == "z feedu"
