"""Auto-detekcja providera + orkiestracja z fallbackiem."""

from adhd_briefing.models import Article
from adhd_briefing.sources.base import SourceProvider
from adhd_briefing.sources.discovery import discover_feed
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
    """Pobiera artykuły ze źródła, preferując feed RSS (model „śledzę źródło").

    Kolejność:
      1. URL wygląda jak feed → RSSProvider.
      2. Strona → znajdź feed (auto-discovery) → RSSProvider na feedzie.
      3. Może to feed bez oczywistego URL → RSSProvider wprost.
      4. Fallback: pojedyncza strona przez ScraperProvider.
    """
    # 1. Jawny feed po heurystyce URL.
    if isinstance(get_provider(url), RSSProvider):
        articles = await RSSProvider().fetch(url)
        if articles:
            return articles

    # 2. Strona — spróbuj znaleźć feed publikacji.
    feed_url = await discover_feed(url)
    if feed_url:
        articles = await RSSProvider().fetch(feed_url)
        if articles:
            return articles

    # 3. Może to jednak feed (bez oczywistego URL).
    articles = await RSSProvider().fetch(url)
    if articles:
        return articles

    # 4. Fallback: scraper pojedynczej strony.
    return await ScraperProvider().fetch(url)


async def fetch_single(url: str) -> list[Article]:
    """Pobiera DOKŁADNIE jedną stronę (model „streść mi ten artykuł").

    W przeciwieństwie do fetch_articles() NIE robi auto-discovery feedu — gdyby
    użytkownik wkleił link do konkretnego artykułu, discovery wróciłoby z najnowszymi
    postami całej witryny zamiast tego jednego tekstu. Tu zawsze scrapujemy ten URL.
    """
    return await ScraperProvider().fetch(url)
