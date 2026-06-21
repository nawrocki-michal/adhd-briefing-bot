"""Modele danych współdzielone w aplikacji."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Article:
    """Pojedynczy artykuł wyciągnięty ze źródła (RSS lub scraper)."""

    url: str
    title: str
    content: str
    source_url: str
    published_at: datetime | None = None
