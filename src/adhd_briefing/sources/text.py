"""Pomocnicze funkcje tekstowe — czyszczenie HTML z fragmentów RSS."""

from html.parser import HTMLParser
from html import unescape


class _TextExtractor(HTMLParser):
    """Zbiera czysty tekst z fragmentu HTML, pomijając tagi skryptów/styli."""

    _SKIP = {"script", "style"}

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skipping = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._SKIP:
            self._skipping = True

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP:
            self._skipping = False

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self._parts.append(data)

    def text(self) -> str:
        return " ".join("".join(self._parts).split())


def strip_html(raw: str) -> str:
    """Zamienia fragment HTML (np. RSS summary) na czysty tekst."""
    if not raw:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(raw)
        return parser.text()
    except Exception:
        # Fallback: surowy unescape, gdyby parser się wyłożył
        return " ".join(unescape(raw).split())
