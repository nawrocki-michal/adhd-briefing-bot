"""Benchmark SourceProvider na realnych URL-ach (gate GO/NO-GO dla M1).

Uruchomienie:
    .venv/bin/python tests/benchmark_sources.py

Wynik: raport jakości ekstrakcji per URL + werdykt. Wymaga sieci.
"""

import asyncio
import sys

from adhd_briefing.sources import get_provider
from adhd_briefing.sources.factory import fetch_articles

# Realne źródła użytkownika (strony artykułów — testują głównie scraper)
REAL_URLS = [
    "https://www.oreilly.com/radar/the-pms-playbook-for-shipping-ai-features-that-actually-work-in-production/",
    "https://blog.ravi-mehta.com/p/prioritization-vs-curation",
    "https://newsletter.weskao.com/p/fundamentals-how-to-share-your-point",
    "https://www.a16z.news/p/everything-is-recorded-now",
    "https://evilmartians.com/chronicles/ai-assisted-engineers-are-burning-out-is-this-fine",
]

# Próg: artykuł uznajemy za poprawnie wyciągnięty, jeśli ma tytuł i >= MIN_CHARS treści
MIN_CHARS = 400


async def benchmark_url(url: str) -> dict:
    provider = type(get_provider(url)).__name__
    try:
        articles = await fetch_articles(url)
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "provider": provider, "ok": False, "error": str(exc)}

    if not articles:
        return {"url": url, "provider": provider, "ok": False, "error": "brak artykułów"}

    art = articles[0]
    chars = len(art.content or "")
    ok = bool(art.title) and chars >= MIN_CHARS
    return {
        "url": url,
        "provider": provider,
        "ok": ok,
        "n_articles": len(articles),
        "title": (art.title or "")[:80],
        "chars": chars,
        "preview": " ".join((art.content or "").split())[:200],
    }


async def main() -> int:
    print("=" * 80)
    print("BENCHMARK SourceProvider — gate GO/NO-GO dla M1")
    print("=" * 80)

    results = await asyncio.gather(*(benchmark_url(u) for u in REAL_URLS))

    passed = 0
    for r in results:
        status = "✅ OK" if r["ok"] else "❌ FAIL"
        print(f"\n{status}  [{r['provider']}]  {r['url']}")
        if r.get("error"):
            print(f"    błąd: {r['error']}")
        else:
            print(f"    tytuł:  {r['title']}")
            print(f"    znaki:  {r['chars']}  (artykułów: {r['n_articles']})")
            print(f"    podgląd: {r['preview']}...")
        passed += int(r["ok"])

    total = len(results)
    print("\n" + "=" * 80)
    print(f"WYNIK: {passed}/{total} źródeł wyciągnięto poprawnie (próg {MIN_CHARS} znaków)")
    verdict = "GO ✅" if passed >= total - 1 else "NO-GO ❌ — przemyśl scraper / RSS-only"
    print(f"WERDYKT: {verdict}")
    print("=" * 80)
    return 0 if passed >= total - 1 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
