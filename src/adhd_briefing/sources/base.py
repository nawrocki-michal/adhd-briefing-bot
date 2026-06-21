"""Abstrakcja SourceProvider — wspólny interfejs dla RSS i scrapera."""

from abc import ABC, abstractmethod

from adhd_briefing.models import Article


class SourceProvider(ABC):
    """Pozyskuje artykuły z pojedynczego URL źródła.

    Implementacje MUSZĄ być odporne na błędy: timeout, 404, malformed content
    zwracają pustą listę zamiast rzucać wyjątek. Izolacja awarii per źródło jest
    krytyczna — jedno wadliwe źródło nie może wywrócić całego briefingu.
    """

    @abstractmethod
    async def fetch(self, url: str) -> list[Article]:
        """Zwraca listę artykułów z danego URL (pustą przy błędzie)."""
        ...
