# Plan implementacji — MVP Faza C (Capture)

**Projekt:** ADHD Briefing App
**Data:** 2026-06-21
**Tryb:** Vertical slice najpierw, async wszędzie
**Stack:** Python 3.11+ · LangGraph · python-telegram-bot v20+ · SQLite · APScheduler · trafilatura · Claude API

---

## Requirements Summary

Zbudować działający MVP Fazy C (Capture): bot który zbiera artykuły z RSS/URL źródeł użytkownika, filtruje duplikaty, streszcza przez Claude API i dostarcza ADHD-friendly briefing (max 5 artykułów) na Telegram — cron o ustalonej godzinie + `/briefing` on-demand. Onboarding konwersacyjny przez Telegram.

**Strategia:** Vertical slice najpierw. Najpierw udowadniamy że briefing ma wartość (SourceProvider → Filter → Summarize → Format, uruchamiane z CLI na realnych URL-ach), dopiero potem dokładamy Telegram, onboarding i scheduler.

**Decyzja async:** Cały stack async (`AsyncSqliteSaver`, async nodes, `AsyncIOScheduler`) — spójne z python-telegram-bot v20+ i APScheduler AsyncIOScheduler.

---

## Milestone 0 — Bootstrap repo (0.5 dnia)

Pliki do utworzenia:
- `pyproject.toml` — deps: `langgraph`, `langgraph-checkpoint-sqlite`, `python-telegram-bot>=20`, `apscheduler`, `feedparser`, `trafilatura`, `anthropic`, `aiosqlite`, `python-dotenv`, `pydantic-settings`; dev: `pytest`, `pytest-asyncio`, `ruff`
- `.gitignore` — `.env`, `*.db`, `*.db-wal`, `*.db-shm`, `__pycache__`, `.venv`
- `.env.example` — `TELEGRAM_BOT_TOKEN=`, `ANTHROPIC_API_KEY=`, `DB_PATH=adhd.db`, `DEFAULT_TIMEZONE=Europe/Warsaw`, `BRIEFING_MAX_ARTICLES=5`
- `src/adhd_briefing/__init__.py`, `src/adhd_briefing/config.py` (pydantic-settings ładujące `.env`)

**Acceptance:**
- [ ] `git init` wykonane; `git status` czysty po `.gitignore`
- [ ] `pip install -e .` przechodzi bez błędów
- [ ] `python -c "from adhd_briefing.config import settings"` ładuje config z `.env`

---

## Milestone 1 — SourceProvider (RSS + trafilatura) ⚠️ NAJWAŻNIEJSZE (1.5 dnia)

To największe ryzyko techniczne. Budujemy i benchmarkujemy PRZED jakimkolwiek kodem grafów.

Pliki:
- `src/adhd_briefing/models.py` — `@dataclass Article` (url, title, content, published_at, source_url)
- `src/adhd_briefing/sources/base.py` — `class SourceProvider(ABC)` z `async def fetch(self, url: str) -> list[Article]`
- `src/adhd_briefing/sources/rss.py` — `RSSProvider` (feedparser; `feedparser.parse` jest sync → owinąć w `asyncio.to_thread`)
- `src/adhd_briefing/sources/scraper.py` — `ScraperProvider` (trafilatura; `httpx.AsyncClient` do pobrania HTML, `trafilatura.extract` w `asyncio.to_thread`)
- `src/adhd_briefing/sources/factory.py` — `get_provider(url) -> SourceProvider` (auto-detect: spróbuj RSS, fallback scraper)
- `tests/benchmark_sources.py` — skrypt benchmarkujący na realnych URL-ach
- `tests/test_sources.py` — testy jednostkowe (mock RSS feed, mock HTML)

**Auto-detekcja (factory):** pobierz nagłówki/treść; jeśli `Content-Type` to `application/rss+xml`/`atom+xml` lub feedparser zwraca wpisy → RSS; w przeciwnym razie scraper.

**Benchmark (krytyczny gate):** uruchomić na realnych URL-ach użytkownika + z brainstormingu (techcrunch.com, producthunt.com). Ocenić ręcznie: czy trafilatura wyciąga czysty tekst (bez nav/footer/reklam)?

**Acceptance:**
- [ ] `RSSProvider.fetch()` zwraca >=1 `Article` z poprawnym title+content dla feedu RSS
- [ ] `ScraperProvider.fetch()` zwraca `Article` z czystym tekstem (manualna ocena: <10% szumu) dla min. 3 realnych URL bez RSS
- [ ] `get_provider()` poprawnie klasyfikuje RSS vs stronę dla 5 testowych URL-i
- [ ] Każdy provider obsługuje błąd (timeout, 404, malformed) zwracając `[]` zamiast rzucać wyjątek
- [ ] `tests/test_sources.py` przechodzi (`pytest tests/test_sources.py`)
- [ ] Raport benchmarku zapisany w `docs/source-benchmark.md` z werdyktem GO/NO-GO

**Decyzja gate:** Jeśli trafilatura zawodzi na realnych źródłach → zatrzymać się i przemyśleć (inny scraper / ograniczenie do RSS-only). Nie iść dalej z wadliwym fundamentem.

---

## Milestone 2 — Warstwa SQLite (1 dzień)

Pliki:
- `src/adhd_briefing/db/schema.sql` — pełny znormalizowany DDL z `docs/architecture.md` (users, briefings, articles, seen_articles, actions, briefing_runs)
- `src/adhd_briefing/db/database.py` — `async` połączenie przez `aiosqlite`, `PRAGMA journal_mode=WAL`, inicjalizacja schematu, helpery: `mark_seen()`, `is_seen()`, `save_briefing()`, `record_run()`/`is_run_done()`

**Uwaga:** `aiosqlite` dla danych aplikacji; `AsyncSqliteSaver` (LangGraph) trzyma własne tabele checkpointów w tej samej bazie `adhd.db`. WAL mode obowiązkowy dla równoczesnych zapisów scheduler+bot.

**Acceptance:**
- [ ] `init_db()` tworzy wszystkie 6 tabel; `PRAGMA journal_mode` zwraca `wal`
- [ ] `mark_seen(chat_id, url)` + `is_seen(chat_id, url)` działają (dedup per użytkownik)
- [ ] `is_run_done(chat_id, date)` zwraca True po `record_run()` — idempotencja
- [ ] Testy dedup i idempotencji przechodzą

---

## Milestone 3 — Vertical slice: BriefingGraph + CLI (2 dni)

To moment pierwszego działającego efektu — briefing generowany z CLI, bez Telegrama.

Pliki:
- `src/adhd_briefing/graphs/state.py` — `BriefingState(TypedDict)` z **`raw_articles: Annotated[list[dict], operator.add]`** (Bug #1)
- `src/adhd_briefing/llm/summarizer.py` — async Claude API call (model `claude-haiku-4-5-20251001` dla streszczeń — tani, szybki), TL;DR + main_outcome per artykuł; **rate limiting** (semafor np. `asyncio.Semaphore(3)`), retry na 429
- `src/adhd_briefing/graphs/briefing.py` — async BriefingGraph:
  - `dispatcher_node` → zwraca `[Send("fetch_worker", {"url": u, "chat_id": c}) for u in sources]` (Bug #5 — Send tylko z węzła)
  - `fetch_worker_node` (async, równoległy per źródło) → `{"raw_articles": [...]}`
  - `filter_node` → usuwa duplikaty i `is_seen`; conditional edge: brak nowych → krótki briefing "nic nowego"
  - `summarizer_node` → izolacja błędów per wywołanie LLM (try/except per artykuł)
  - `formatter_node` → ADHD-friendly, max 5 artykułów (`BRIEFING_MAX_ARTICLES`)
  - (vertical slice: zamiast `delivery_node` → zwróć string; delivery dochodzi w M4)
- `src/adhd_briefing/cli.py` — `python -m adhd_briefing.cli --sources url1,url2` → drukuje briefing do stdout

**Checkpointer:** `AsyncSqliteSaver.from_conn_string(DB_PATH)` jako async context manager, `await checkpointer.setup()`, `thread_id=str(chat_id)` (Bug #2, Bug #3).

**Context7 przed kodowaniem:** `/websites/langchain_oss_python_langgraph` — zweryfikować aktualne API `AsyncSqliteSaver`, `Send`, `interrupt`.

**Acceptance:**
- [ ] `python -m adhd_briefing.cli --sources <2 realne URL>` drukuje sformatowany briefing z max 5 artykułami
- [ ] Send() fan-out NIE rzuca `InvalidUpdateError` (reducer działa)
- [ ] Drugie uruchomienie z tym samym chat_id pokazuje mniej/zero artykułów (dedup `seen_articles` działa)
- [ ] Awaria jednego źródła (zły URL w liście) nie wywraca całego briefingu — pozostałe się streszczają
- [ ] Test grafu z mock providerami przechodzi (`pytest tests/test_briefing_graph.py`)

---

## Milestone 4 — Telegram + OnboardingGraph (2 dni)

Pliki:
- `src/adhd_briefing/notify/base.py` — `class NotificationService(ABC)` z `async def send(chat_id, message)`
- `src/adhd_briefing/notify/telegram.py` — `TelegramNotifier` (python-telegram-bot v20+, async)
- `src/adhd_briefing/graphs/onboarding.py` — OnboardingGraph: `TopicsNode → SourcesNode → ScheduleNode → ConfirmNode`, każdy z `interrupt()` + AsyncSqliteSaver; ConfirmNode zapisuje usera do SQLite
- `src/adhd_briefing/bot.py` — handlery: `/start` (→ OnboardingGraph), `/briefing` (→ BriefingGraph + delivery), obsługa tekstu jako resume po `interrupt()`
- Dodać `delivery_node` do BriefingGraph (wstrzyknięty `NotificationService`)

**Onboarding resume:** input użytkownika wznawia graf przez `graph.ainvoke(Command(resume=text), config)` z `thread_id=chat_id`.

**Acceptance:**
- [ ] `/start` prowadzi pełny onboarding (tematy → źródła → godzina → potwierdzenie) i zapisuje usera do `users`
- [ ] Stan onboardingu przeżywa restart bota (AsyncSqliteSaver — Bug #3) — wznawia od ostatniego węzła
- [ ] `/briefing` generuje i wysyła briefing na Telegram dla zarejestrowanego usera
- [ ] Dwóch userów równolegle nie miesza stanów (osobny `thread_id` — Bug #2)

---

## Milestone 5 — Scheduler (1 dzień)

Pliki:
- `src/adhd_briefing/scheduler.py` — `AsyncIOScheduler` + `SQLAlchemyJobStore(url="sqlite:///adhd.db")`, per-user cron job timezone-aware, `id=f"briefing_{chat_id}"`, `replace_existing=True`
- Integracja: ConfirmNode (M4) dodaje job; przed runem sprawdź `is_run_done()` (idempotencja, Bug — `briefing_runs`)

**Acceptance:**
- [ ] Job dodany podczas onboardingu odpala briefing o ustalonej godzinie w strefie usera (test: godzina za 2 min)
- [ ] Job przeżywa restart procesu (SQLAlchemyJobStore — durable)
- [ ] Podwójne odpalenie tego samego dnia NIE wysyła dwóch briefingów (`is_run_done`)
- [ ] Zmiana godziny przez usera aktualizuje job (`replace_existing`)

---

## Milestone 6 — Packaging & docs (0.5 dnia)

Pliki:
- `Dockerfile` — python:3.11-slim, `pip install -e .`, `CMD python -m adhd_briefing.bot`
- `README.md` — setup, **akapit tradeoff o LangGraph** (dlaczego graf dla liniowego pipeline: Send() fan-out, checkpoint-resume bez ponownych wywołań LLM, wspólna abstrakcja z onboardingiem), self-hosting instructions
- Zaktualizować `docs/progress.md`

**Acceptance:**
- [ ] `docker build` przechodzi; kontener startuje i łączy się z Telegram
- [ ] README zawiera akapit tradeoff (bez niego wygląda jak resume-driven development)
- [ ] `.env.example` kompletny; `git clone` + `docker build` + `.env` = działający bot

---

## Risks & Mitigations

| Ryzyko | Prawd. | Mitygacja |
|---|---|---|
| trafilatura nie wyciąga czystego tekstu z realnych stron | Wysokie | **Milestone 1 gate** — benchmark PRZED grafami; fallback RSS-only jeśli NO-GO |
| `InvalidUpdateError` przy Send() fan-out | Pewne bez reducera | `Annotated[list, operator.add]` na `raw_articles` (Bug #1) — w acceptance M3 |
| Konflikt event loop Telegram/APScheduler/SQLite | Średnie | Async wszędzie, jeden event loop, `aiosqlite` + `AsyncSqliteSaver` |
| Claude API 429 przy wielu źródłach | Średnie | Semafor + retry w summarizer (M3) |
| Stany userów się mieszają | Pewne bez thread_id | `thread_id=str(chat_id)` per user (Bug #2) — acceptance M4 |
| Podwójny briefing tego samego dnia | Średnie | tabela `briefing_runs` + `is_run_done` (M5) |
| Utrata stanu onboardingu po restarcie | Pewne z MemorySaver | `AsyncSqliteSaver` (Bug #3) — acceptance M4 |

---

## Verification Steps (end-to-end)

1. `pip install -e .` → import config OK
2. `pytest` → wszystkie testy zielone
3. `python -m adhd_briefing.cli --sources <realne URL>` → poprawny briefing (M3 gate)
4. `/start` na realnym bocie → onboarding zapisuje usera; restart bota → onboarding wznawia
5. `/briefing` → briefing dochodzi na Telegram
6. Scheduler: ustaw godzinę +2 min → briefing przychodzi automatycznie; drugie odpalenie tego dnia → brak duplikatu
7. `docker build && docker run` z `.env` → bot żyje

---

## Kolejność wykonania (zależności)

```
M0 Bootstrap
   └─► M1 SourceProvider ⚠️ (gate GO/NO-GO)
          └─► M2 SQLite
                 └─► M3 BriefingGraph + CLI  ◄── pierwszy działający efekt
                        ├─► M4 Telegram + Onboarding
                        │      └─► M5 Scheduler
                        └─────────────► M6 Packaging & docs
```

Szacowany czas: ~8.5 dnia roboczego (zgodne z planem tygodniowym w architecture.md).

---

## Pre-implementacyjny checklist

- [ ] Context7 sprawdzony dla każdego węzła LangGraph przed kodowaniem (`/websites/langchain_oss_python_langgraph`)
- [ ] User dostarczy 3-5 realnych URL-i swoich źródeł do benchmarku M1
- [ ] `progress.md` aktualizowany po każdym milestone
