# ADHD Briefing App — instrukcje dla Claude

## Kontekst projektu

Portfolio project pokazujący umiejętności techniczne (multi-agent AI) rekruterowi.
Właściciel: PM rozwijający umiejętności techniczne, z ADHD — jednocześnie główny użytkownik.
Cel: działający, self-hostable bot na GitHubie, który realnie rozwiązuje codzienny problem.

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

### Bug #5 — DispatcherNode musi być węzłem (nie edge function)
`Send()` można zwrócić tylko z węzła, nie z conditional edge.

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

## Kolejność implementacji MVP (Faza C)

1. `SourceProvider` (RSS + trafilatura) — **zacząć od tego, największe ryzyko**
2. Znormalizowany schemat SQLite + migracje
3. `OnboardingGraph` z SqliteSaver i interrupt()
4. `BriefingGraph` z Send() fan-out i reducerami
5. Scheduler (APScheduler + SqliteJobStore)
6. Telegram bot integration
7. Dockerfile, .env.example, README

## Pliki projektu

- `brainstorming/adhd-app-brainstorming.md` — pełny brainstorming, model CRA
- `docs/architecture.md` — szczegółowa architektura, pełny DDL, kod snippety
- `docs/progress.md` — tracker postępów (aktualizuj po każdym ukończonym kroku)

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

- Przed implementacją czegokolwiek z LangGraph: sprawdź context7 (`/websites/langchain_oss_python_langgraph`)
- Po każdym ukończonym kroku: zaktualizuj `docs/progress.md`
- SourceProvider testuj na rzeczywistych URL-ach użytkownika, nie mockach
- Nie łącz OnboardingGraph z BriefingGraph — to świadoma decyzja architektoniczna
- Faza C (Capture) jako MVP — nie implementuj faz R i A dopóki C nie działa
