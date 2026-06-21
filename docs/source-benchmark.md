# SourceProvider — raport benchmarku (gate M1)

**Data:** 2026-06-21
**Werdykt:** **GO ✅ — 5/5 źródeł**
**Próg:** tytuł obecny + ≥400 znaków czystej treści

## Metoda

Benchmark (`tests/benchmark_sources.py`) uruchomiony na 5 realnych URL-ach użytkownika.
Wszystkie to strony artykułów (nie feedy RSS) → testują ścieżkę `ScraperProvider` (trafilatura 2.1.0),
która była identyfikowana w architekturze jako największe ryzyko techniczne.

## Wyniki

| Źródło | Provider | Znaki | Werdykt |
|---|---|---|---|
| oreilly.com/radar — PM's Playbook for Shipping AI | ScraperProvider | 12 550 | ✅ |
| blog.ravi-mehta.com — Prioritization vs Curation | ScraperProvider | 10 563 | ✅ |
| newsletter.weskao.com — How to share your POV | ScraperProvider | 5 933 | ✅ |
| a16z.news — Everything is Recorded Now | ScraperProvider | 7 476 | ✅ |
| evilmartians.com — AI-assisted engineers burning out | ScraperProvider | 19 402 | ✅ |

## Ocena jakości

- Tytuły wyciągane czysto (`trafilatura.extract_metadata`).
- Treść bez szumu nawigacji/stopki/reklam (podglądy zaczynają się od właściwego tekstu artykułu).
- `favor_precision=True` + `include_comments/tables=False` daje czysty tekst pod streszczanie LLM.

## Wniosek

Założenie architektury (RSS + trafilatura niezawodnie wyciąga czysty tekst) **zweryfikowane pozytywnie**
dla rzeczywistych źródeł użytkownika. Fundament Fazy C jest solidny — można budować grafy (M3).

Brak potrzeby planu awaryjnego RSS-only.
