# ADHD Briefing App — instrukcje dla Claude

## Kontekst projektu

Portfolio project pokazujący umiejętności techniczne (multi-agent AI) rekruterowi.
Właściciel: PM rozwijający umiejętności techniczne, z ADHD — jednocześnie główny użytkownik.
Cel: działający, self-hostable bot na GitHubie, który realnie rozwiązuje codzienny problem.

## ⚡ Aktualny stan (2026-06-21) — CZYTAJ NAJPIERW

**MVP Faza C działa end-to-end lokalnie.** Telegram bot: `/start` (onboarding) → `/briefing`
(feedy → Haiku → ADHD-friendly briefing). Treści po **angielsku**. Jakość mierzona evalem: **98/100**.

- **Pełny stan + następne kroki:** `docs/progress.md`
- **Jak uruchomić / mapa projektu / komendy:** `docs/dev-guide.md`
- **Wytyczne treści + rubryka evals:** `docs/adhd-content-guidelines.md`

**Zrobione:** M0 bootstrap, M1 SourceProvider (+auto-discovery RSS), M2 SQLite, M3 BriefingGraph+CLI,
M4 Telegram+Onboarding, i18n→EN, M3.5 eval harness + A/B promptów, **M4.6 zarządzanie źródłami
(`/sources` `/addsource` `/removesource`) + inbox jednorazowy (bare-paste linku → `pending_articles`
→ dostarczany w najbliższym briefingu, pinned/one-shot, pobierany `fetch_single`)**. 69/69 testów, ruff czysty.

**Nierozstrzygnięte / następne:** (1) 🔴 **hosting always-on** (Fly.io vs Oracle VM vs własny sprzęt —
Vercel odrzucony), (2) tone-as-user-choice + read-time, (3) M5 scheduler (odblokuje „briefing o godzinie"
— dziś inbox konsumuje ręczny `/briefing`), (4) M6 README+Dockerfile.

> ⚠️ **Stan na koniec sesji 2026-06-21:** M4.6 zaimplementowane, przetestowane (69/69) i ZACOMMITOWANE,
> ale **NIE przeklikane na żywym Telegramie** — pierwszy krok jutro: `/start` → `/addsource` → wklej link → `/briefing`.

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
| Scheduler | APScheduler + SqliteJobStore | Per-user timezone-aware |
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
5. ⬜ Scheduler (APScheduler + SQLAlchemyJobStore) — **M5, do zrobienia**
6. ✅ Telegram bot integration
7. ⬜ Dockerfile + README — **M6, do zrobienia** (+ decyzja hostingowa)

Aktualny tracker: `docs/progress.md`.

## Pliki projektu

- `brainstorming/adhd-app-brainstorming.md` — pełny brainstorming, model CRA
- `docs/architecture.md` — szczegółowa architektura, pełny DDL, kod snippety
- `docs/progress.md` — tracker postępów (aktualizuj po każdym ukończonym kroku)
- `docs/dev-guide.md` — setup, komendy, mapa projektu, gdzie są prompty
- `docs/adhd-content-guidelines.md` — wytyczne treści ADHD + rubryka evals
- `evals/` — eval harness (golden set, judge, A/B promptów) — NIE w pytest (realne LLM calls)

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
