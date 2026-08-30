# ADHD Briefing App — instrukcje dla Claude

## Kontekst projektu

Projekt rozwijający umiejętności techniczne (multi-agent AI) na realnym, codziennym problemie.
Właściciel: PM rozwijający umiejętności techniczne, z ADHD — jednocześnie główny użytkownik.
Cel: działający, self-hostable bot na GitHubie, który realnie rozwiązuje codzienny problem.

## ⚡ Aktualny stan (2026-08-30) — CZYTAJ NAJPIERW

**MVP Faza C działa end-to-end lokalnie, z automatyczną codzienną dostawą.** Telegram bot:
`/start` (onboarding) → briefing **codziennie o wybranej godzinie** (albo `/briefing` na żądanie):
feedy → Haiku → ADHD-friendly briefing. Treści po **angielsku**. Jakość mierzona evalem: **~94–98/100**
(wariancja 2-case golden setu; neutral prompt niezmieniony od wdrożenia wariantu C).

- **Pełny stan + następne kroki:** `docs/progress.md`
- **Jak uruchomić / mapa projektu / komendy:** `docs/dev-guide.md`
- **Wytyczne treści + rubryka evals:** `docs/adhd-content-guidelines.md`

**Zrobione:** M0 bootstrap, M1 SourceProvider (+auto-discovery RSS), M2 SQLite, M3 BriefingGraph+CLI,
M4 Telegram+Onboarding, i18n→EN, M3.5 eval harness + A/B promptów, M4.6 zarządzanie źródłami
(`/sources` `/addsource` `/removesource`) + inbox jednorazowy, tone-as-user-choice (presety
`neutral`/`warm`/`direct`) + read-time per artykuł, M6 README+Dockerfile+LICENSE, obserwowalność
kosztów LLM, **M5 scheduler (codzienna dostawa timezone-aware + catch-up + `/time`)**.
126/126 testów, ruff bez nowych ustaleń.

**Nierozstrzygnięte / następne:** (1) 🔴 **hosting always-on** (Fly.io vs Oracle VM vs własny sprzęt —
Vercel odrzucony) — **jedyna rzecz między nami a botem 24/7**, (2) przeklik M5 na żywo,
(3) Batch API (−50%) dla briefingów ze schedulera.

> ⚠️ **Stan na koniec sesji 2026-08-30 — START TUTAJ NASTĘPNYM RAZEM:**
> - **Zrobione dziś:** M5 scheduler — `src/adhd_briefing/scheduler.py` (`BriefingScheduler`),
>   komenda `/time`, `db.set_schedule()`, wpięcie w `post_init`/`post_shutdown`, catch-up
>   po restarcie, `_deliver_briefing()` wyodrębnione z handlera `/briefing`. 31 nowych testów.
> - **Do przeklikania na żywo (NIE zrobione):** (a) M5 — `/time`, briefing sam o wybranej
>   godzinie, restart bota po tej godzinie → czy przychodzi catch-up z „⏰ Catching up";
>   (b) zaległe z poprzedniej sesji: ton + read-time (`/tone warm` → `/briefing`).
>   Odpal: `PYTHONPATH=src .venv/bin/python -m adhd_briefing.bot`.
> - **Następny milestone:** 🔴 **decyzja hostingowa** (Fly.io / Oracle Always Free / własny sprzęt).
>   Kod i Dockerfile są gotowe — nie wymagają przeróbek pod żaden z tych wariantów.

**Konwencja uruchamiania:** testy przez `pytest` (ma `pythonpath=["src"]`); moduły przez
`PYTHONPATH=src .venv/bin/python -m adhd_briefing.<bot|cli>` lub `-m evals.<run|prompt_variants>`.

## Stack techniczny (decyzje ostateczne)

| Element | Wybór | Uwaga |
|---|---|---|
| Framework agentów | LangGraph (Python) | Pokazuje grafy stanów, Send(), interrupt() |
| Język | Python | Ekosystem AI |
| Delivery | Telegram Bot API | python-telegram-bot |
| Storage | SQLite | Zero konfiguracji, WAL mode |
| Checkpointer | SqliteSaver | NIE MemorySaver — gubi stan po restarcie |
| Scheduler | APScheduler (MemoryJobStore, joby z bazy) | Per-user timezone-aware; patrz Bug #7 |
| Fetch | feedparser (RSS) + trafilatura (fallback) | Auto-detect RSS vs strona |
| LLM | Claude API | Summarizer node |

## Architektura — dwa oddzielne grafy

### OnboardingGraph
Konwersacyjny, human-in-the-loop. Triggered przez `/start`.
`TopicsNode → SourcesNode → ScheduleNode → ConfirmNode`
Każdy węzeł używa `interrupt()` + czeka na input użytkownika.

### BriefingGraph
Wsadowy, autonomiczny, fan-out/fan-in. Triggered przez cron lub `/briefing`.
`DispatcherNode → [FetchWorkerNode x N] → FilterNode → SummarizerNode → FormatterNode → DeliveryNode`

## KRYTYCZNE pułapki architektoniczne

### Bug #1 — reducer dla Send() fan-out (OBOWIĄZKOWE)
```python
# BriefingState — raw_articles MUSI mieć reducer
from typing import Annotated
import operator

class BriefingState(TypedDict):
    chat_id: str
    sources: list[str]
    raw_articles: Annotated[list[dict], operator.add]  # ← BEZ TEGO: InvalidUpdateError
    filtered_articles: list[dict]
    summarized_articles: list[dict]
    briefing: str
```

### Bug #2 — osobny thread_id per chat_id (OBOWIĄZKOWE)
```python
config = {"configurable": {"thread_id": str(chat_id)}}
# Inaczej stany użytkowników się zmieszają
```

### Bug #3 — SqliteSaver nie MemorySaver
```python
from langgraph.checkpoint.sqlite import SqliteSaver
checkpointer = SqliteSaver.from_conn_string("adhd.db")
```

### Bug #4 — WAL mode dla SQLite
```python
conn.execute("PRAGMA journal_mode=WAL")
```

### Bug #5 — NIEAKTUALNE dla LangGraph 1.x ⚠️
Architektura zakładała, że `Send()` wymaga osobnego węzła dispatcher. **W LangGraph 1.x
(zainstalowane 1.2.6) `Send()` zwraca się z funkcji routującej `add_conditional_edges`** —
tak jest zaimplementowane (`graphs/briefing.py`: `prepare` → conditional edge `dispatch` →
`fetch_worker`). Zweryfikowane przez context7. Bug #1–#4 nadal obowiązują.

### Bug #6 — BriefingGraph NIE może być checkpointowany (OBOWIĄZKOWE)
BriefingGraph jest wsadowy i bezstanowy (brak `interrupt()`). Kompilowany z trwałym
checkpointerem + stałym `thread_id` akumulował stan między uruchomieniami: reducer
`operator.add` na `raw_articles` dokładał fetch każdego `/briefing` do poprzednich
(stan spuchł do 128 art., wracały stare/usunięte źródła). `raw_articles: []` z initial
state NIE czyści — reducer robi `stare + [] = stare`.
```python
# bot.py — briefing BEZ checkpointera (onboarding go potrzebuje, briefing nie):
app.bot_data["briefing"] = build_briefing_graph(db, summarizer)  # ŻADNEGO checkpointer=
```
Dedup między dniami zapewnia tabela `seen_articles`, nie checkpoint. Tylko OnboardingGraph
(HITL) używa checkpointera.

### Bug #7 — APScheduler: `replace_existing` nie działa przed `start()` (OBOWIĄZKOWE)
Dopóki scheduler nie wystartował, `add_job()` odkłada joby do `_pending_jobs`, gdzie
`replace_existing=True` jest **ignorowane** — ten sam `id` się dubluje, a dwa joby to dwie
dostawy briefingu. `BriefingScheduler.sync_user()` robi więc `unschedule()` **przed** `add_job()`.
```python
self.unschedule(chat_id)          # ← bez tego duplikat, gdy sync poleci przed start()
self.scheduler.add_job(..., id=job_id(chat_id), replace_existing=True)
```
Druga pułapka tego samego pakietu: `AsyncIOScheduler.shutdown()` tylko *planuje* zamknięcie przez
`call_soon_threadsafe` — zaraz po powrocie `scheduler.running` wciąż jest `True`. Dlatego
`BriefingScheduler.shutdown()` jest `async` i oddaje sterowanie pętli (`await asyncio.sleep(0)`),
inaczej PTB zamknąłby pętlę w trakcie zamykania schedulera.

### Scheduler — MemoryJobStore, NIE SQLAlchemyJobStore (świadome odejście od architektury)
`docs/architecture.md` zakładał trwały jobstore. Odrzucone: harmonogram ma już trwałe źródło prawdy
(`users.briefing_time`/`users.timezone`), więc jobstore byłby jego drugą kopią (dryf przy każdej
zmianie godziny) i wymuszałby joby jako funkcje modułowe zamiast domknięć na `db`. Joby są
**odtwarzane z bazy** przy starcie (`sync_all`) i punktowo (`sync_user`) po `/start`, `/time`
i zmianach źródeł. Trwałość, której faktycznie potrzebujemy, daje `briefing_runs`:
idempotencja (jeden briefing per user per dzień, data liczona **w strefie użytkownika**)
+ catch-up briefingu pominiętego przy wyłączonym bocie. Ręczny `/briefing` **nie** zapisuje
`briefing_runs` — to rejestr schedulera.

### Dodatkowy fix (M4.5) — RSSProvider pobiera feed przez httpx z UA przeglądarki
feedparser z domyślnym UA bywa blokowany (403) przez Substack/O'Reilly → feed wracał pusty.
Pobieramy przez `httpx` z UA przeglądarki, potem parsujemy tekst. Patrz `sources/rss.py`.

## Schemat SQLite (znormalizowany — nie upraszczaj)

Tabele: `users`, `briefings`, `articles`, `seen_articles`, `actions`, `briefing_runs`
Szczegółowy DDL w `docs/architecture.md`.
`briefing_runs` zapewnia idempotencję schedulera (jeden briefing per user per dzień).

## Abstrakcje (nie łam ich)

```python
class SourceProvider(ABC):      # RSSProvider | ScraperProvider
class NotificationService(ABC): # TelegramNotifier | (przyszłość: WhatsApp)
```

## Co musi być w repo od dnia 1

- `.env.example` — bez tego nikt nie postawi
- `README.md` z akapitem tłumaczącym dlaczego LangGraph dla liniowego pipeline
- `Dockerfile`
- `pyproject.toml`
- Rate limiting dla Claude API (zapobiega 429 przy wielu źródłach)

## Kolejność implementacji MVP (Faza C) — STATUS

1. ✅ `SourceProvider` (RSS + trafilatura + auto-discovery)
2. ✅ Znormalizowany schemat SQLite
3. ✅ `OnboardingGraph` z AsyncSqliteSaver i interrupt()
4. ✅ `BriefingGraph` z Send() fan-out i reducerami
5. ✅ Scheduler (APScheduler + MemoryJobStore odtwarzany z bazy — patrz wyżej)
6. ✅ Telegram bot integration
7. ✅ Dockerfile + README (decyzja hostingowa nadal otwarta)

Aktualny tracker: `docs/progress.md`.

## Pliki projektu

- `brainstorming/adhd-app-brainstorming.md` — pełny brainstorming, model CRA
- `docs/architecture.md` — szczegółowa architektura, pełny DDL, kod snippety
- `docs/progress.md` — tracker postępów (aktualizuj po każdym ukończonym kroku)
- `docs/dev-guide.md` — setup, komendy, mapa projektu, gdzie są prompty
- `docs/adhd-content-guidelines.md` — wytyczne treści ADHD + rubryka evals
- `evals/` — eval harness (golden set, judge, A/B promptów) — NIE w pytest (realne LLM calls)
  - ⚠️ Harness ma też **osobne, samodzielne repo** `adhd-summary-evals` (prywatne, pod firmę).
    `evals/` tutaj jest **źródłem prawdy dla bota**; tamto to snapshot, nie zależność. Zmiana
    rubryki/golden setu → zsynchronizuj ręcznie (szczegóły w `docs/progress.md`, M3.5).

## Narzędzia i skille

### Context7 — używaj zawsze przed implementacją z SDK
LangGraph library ID: `/websites/langchain_oss_python_langgraph` (1429 snippetów, High reputation)
Wywołanie: najpierw `resolve-library-id`, potem `query-docs`.

### Dostępne skille projektu
- `product-brainstorming` — do dalszego brainstormingu faz R i A

### Dostępne skille OMC (przez `/oh-my-claudecode:<name>`)
- `planner` — rozpisanie planu implementacji przed kodowaniem
- `executor` — implementacja (użyj `model=opus` dla złożonych węzłów LangGraph)
- `architect` — przegląd architektoniczny (read-only)
- `debugger` — gdy coś nie działa
- `verifier` — weryfikacja przed zgłoszeniem zadania jako done

## Konwencje pracy

- Przed implementacją czegokolwiek z LangGraph/SDK: sprawdź context7 (`/websites/langchain_oss_python_langgraph`)
- Po każdym ukończonym kroku: zaktualizuj `docs/progress.md`
- **Treści i UI bota po angielsku** (user komunikuje się po polsku, ale produkt jest EN)
- **Zmiana promptu summarizera → zmierz evalem** (`evals/run.py summarizer`); nie commituj „na czuja"
- SourceProvider testuj na rzeczywistych URL-ach użytkownika, nie mockach
- Nie łącz OnboardingGraph z BriefingGraph — to świadoma decyzja architektoniczna
- Faza C (Capture) jako MVP — nie implementuj faz R i A dopóki C nie działa
- Commit per milestone (user tak woli); sekrety tylko w `.env` (nigdy w `.env.example`)
