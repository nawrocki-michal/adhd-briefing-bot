"""Warstwa pozyskiwania treści — SourceProvider i implementacje."""

from adhd_briefing.sources.base import SourceProvider
from adhd_briefing.sources.factory import fetch_articles, get_provider
from adhd_briefing.sources.rss import RSSProvider
from adhd_briefing.sources.scraper import ScraperProvider

__all__ = [
    "SourceProvider",
    "RSSProvider",
    "ScraperProvider",
    "get_provider",
    "fetch_articles",
]
