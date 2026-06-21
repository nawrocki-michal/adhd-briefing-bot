# Dev Guide — jak uruchomić i wrócić do projektu

Praktyczny przewodnik: setup, komendy, mapa projektu. Stan: MVP Faza C działa lokalnie.

## Setup (jednorazowo)

```bash
cd /Users/michalnawrocki/Desktop/Claude/ADHD
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env        # i uzupełnij sekrety (patrz niżej)
```

`.env` (ignorowany przez git) wymaga:
- `TELEGRAM_BOT_TOKEN` — z @BotFather (Telegram: /newbot)
- `ANTHROPIC_API_KEY` — z console.anthropic.com
- reszta ma sensowne defaulty (`DB_PATH`, `DEFAULT_TIMEZONE`, `BRIEFING_MAX_ARTICLES`,
  `SUMMARIZER_MODEL=claude-haiku-4-5-20251001`, `LLM_CONCURRENCY`)

> ⚠️ `.env.example` jest commitowany — NIGDY nie wpisuj tam realnych sekretów. Sekrety tylko w `.env`.

## Komendy

```bash
# Testy (niezależne od editable install dzięki pythonpath=src w pyproject)
.venv/bin/python -m pytest -q
.venv/bin/ruff check src/ evals/

# CLI briefing (vertical slice — bez Telegrama, drukuje do stdout)
PYTHONPATH=src .venv/bin/python -m adhd_briefing.cli --chat-id me --sources "https://blog.ravi-mehta.com,https://evilmartians.com"

# Telegram bot (polling, always-on dopóki proces żyje)
PYTHONPATH=src .venv/bin/python -m adhd_briefing.bot
# Komendy bota: /start (onboarding), /briefing (briefing teraz),
#   /sources /addsource <url…> /removesource <nr|url> (stałe źródła — inkrementalnie),
#   oraz: wklej linki bez komendy → trafiają do inboxa, dostarczane w najbliższym briefingu

# Evals (wymagają ANTHROPIC_API_KEY, robią realne wywołania — kosztują)
PYTHONPATH=src .venv/bin/python -m evals.run validate        # czy eval odróżnia dobre/złe (oczek. 8/8)
PYTHONPATH=src .venv/bin/python -m evals.run summarizer       # baseline jakości realnego summarizera
PYTHONPATH=src .venv/bin/python -m evals.prompt_variants      # A/B wariantów promptu
```

> Po każdym lokalnym uruchomieniu CLI/bota powstaje `adhd.db` (+ `-wal`/`-shm`) — ignorowane przez git.

## Mapa projektu

```
src/adhd_briefing/
├── config.py            # ustawienia z .env (pydantic-settings)
├── models.py            # dataclass Article
├── sources/             # M1 + M4.5 — pozyskiwanie treści
│   ├── base.py          #   SourceProvider (ABC)
│   ├── rss.py           #   RSSProvider (httpx + feedparser; UA przeglądarki!)
│   ├── scraper.py       #   ScraperProvider (trafilatura)
│   ├── discovery.py     #   auto-discovery feedu (link rel=alternate + /feed)
│   ├── factory.py       #   fetch_articles() — strona→feed→RSS, fallback scraper
│   └── text.py          #   strip_html
├── db/                  # M2 — SQLite
│   ├── schema.sql       #   6 tabel (users, briefings, articles, seen_articles, actions, briefing_runs)
│   └── database.py      #   async aiosqlite, WAL, dedup, idempotencja
├── llm/
│   └── summarizer.py    # Claude Haiku, structured outputs, _SYSTEM = prompt (wariant C, 98/100)
├── graphs/
│   ├── state.py         #   BriefingState (reducer!), OnboardingState
│   ├── briefing.py      #   M3 — async graf + format_briefing()
│   └── onboarding.py    #   M4 — interrupt() HITL + parsery
├── notify/
│   ├── base.py          #   NotificationService (ABC)
│   └── telegram.py      #   TelegramNotifier (Markdown→plain fallback)
├── cli.py               # M3 — ręczne uruchomienie briefingu
└── bot.py               # M4 — Telegram entry pointy (/start, /briefing)

evals/                   # M3.5 — eval harness (NIE w pytest; realne LLM calls)
├── golden_set.py        #   syntetyczne źródła + warianty (good + bad)
├── judge.py             #   LLM-as-judge (Sonnet 4.6) + overall_score (gated, ważony)
├── checks.py            #   deterministyczne auto-checki (długość/format)
├── run.py               #   validate | summarizer
└── prompt_variants.py   #   A/B wariantów promptu

tests/                   # pytest (57, bez sieci/LLM — wszystko mockowane)
docs/                    # architecture.md, adhd-content-guidelines.md, progress.md, dev-guide.md, source-benchmark.md
```

## Gdzie są prompty
- **Summarizer** (jak AI streszcza): `src/adhd_briefing/llm/summarizer.py` → `_SYSTEM`
- **Judge** (jak AI ocenia jakość): `evals/judge.py` → `_SYSTEM`
- Warianty A/B: `evals/prompt_variants.py`
- Tekst konwersacyjny bota: `graphs/onboarding.py`, `graphs/briefing.py`, `bot.py`

> Zmieniasz prompt summarizera? Odpal `evals/run.py summarizer` (i/lub `prompt_variants.py`)
> żeby zmierzyć czy 98/100 rośnie czy spada.

## Pętla iteracji jakości (jak pracujemy nad promptami)
1. Zmień prompt / dodaj wariant w `evals/prompt_variants.py`
2. `python -m evals.prompt_variants` → porównaj wyniki
3. Wdroż zwycięzcę do `summarizer.py` `_SYSTEM`
4. `python -m evals.run summarizer` → potwierdź wynik
5. `pytest` + `ruff` + commit

## Kluczowe decyzje techniczne (dlaczego tak)
- **Dwa osobne grafy** (Onboarding konwersacyjny vs Briefing wsadowy) — świadomy wybór, patrz `architecture.md`.
- **LangGraph 1.x:** `Send()` zwracany z funkcji routującej conditional edge (nie z osobnego węzła).
- **RSSProvider** pobiera feed przez httpx z UA przeglądarki — domyślny UA feedparsera bywa blokowany (403).
- **Reducer** `Annotated[list, operator.add]` na `raw_articles` — wymagany przy Send() fan-out.
- **AsyncSqliteSaver** + `thread_id` per chat_id — stan onboardingu przeżywa restart, userzy się nie mieszają.
- Pełny opis pułapek: `CLAUDE.md` + `docs/architecture.md`.
```
