"""Auto-detekcja providera + orkiestracja z fallbackiem."""

from adhd_briefing.models import Article
from adhd_briefing.sources.base import SourceProvider
from adhd_briefing.sources.rss import RSSProvider
from adhd_briefing.sources.scraper import ScraperProvider

# Heurystyki URL wskazujące na feed RSS/Atom
_FEED_HINTS = ("/feed", "/rss", "atom.xml", "rss.xml", ".rss", "/feed/", "format=rss")


def get_provider(url: str) -> SourceProvider:
    """Wybiera providera na podstawie heurystyki URL (bez I/O).

    Pewność nie jest wymagana — fetch_articles() ma fallback na drugi provider.
    """
    lowered = url.lower()
    if any(hint in lowered for hint in _FEED_HINTS):
        return RSSProvider()
    return ScraperProvider()


async def fetch_articles(url: str) -> list[Article]:
    """Pobiera artykuły z URL, z fallbackiem na alternatywny provider.

    Jeśli zgadnięty provider zwróci pustą listę, próbujemy drugiego — strona
    mogła zostać błędnie sklasyfikowana (feed bez oczywistego URL / strona z RSS).
    """
    primary = get_provider(url)
    articles = await primary.fetch(url)
    if articles:
        return articles

    fallback = ScraperProvider() if isinstance(primary, RSSProvider) else RSSProvider()
    return await fallback.fetch(url)
