# ADHD Briefing App — Architektura Techniczna

**Data:** 2026-06-21  
**Źródło:** Przegląd architektoniczny OMC Architect Agent  
**Status:** Draft v1 — przed implementacją

---

## Decyzje architektoniczne

### Dwa oddzielne grafy LangGraph

**OnboardingGraph** i **BriefingGraph** pozostają osobne. Uzasadnienie:

- Onboarding jest konwersacyjny, interaktywny, human-in-the-loop — czeka na input użytkownika między węzłami (`interrupt()` + checkpointer). Sterowany zdarzeniem `/start`.
- Briefing jest wsadowy, autonomiczny, fan-out/fan-in, harmonogramowany. Bez człowieka w pętli.

Połączenie ich zmusiłoby jeden schemat stanu do obsługi dwóch niekompatybilnych przepływów.

**⚠️ Ważne dla README:** Briefing pipeline (Fetch→Filter→Summarize→Format→Deliver) to prosta linia — LangGraph jest tu technicznie przesadą. Musi być akapit w README tłumaczący świadomą decyzję:
- Send() fan-out dla równoległego fetchowania
- Checkpoint-resume po awarii (bez ponownych wywołań LLM)
- Wspólna abstrakcja z Onboardingiem (SqliteSaver, state model)

Bez tego akapitu wygląda jak resume-driven development. Z nim — świadoma decyzja inżynierska.

---

## Grafy LangGraph

### OnboardingGraph

```
/start
  │
  ▼
TopicsNode        ← pyta o zainteresowania, czeka na input [interrupt()]
  │
  ▼
SourcesNode       ← zbiera źródła URL/RSS, waliduje, czeka na /done [interrupt()]
  │
  ▼
ScheduleNode      ← ustala godzinę + strefę czasową [interrupt()]
  │
  ▼
ConfirmNode       ← potwierdza setup, zapisuje do SQLite, opcjonalny /briefing preview
  │
END
```

### BriefingGraph

```
START
  │
  ▼
DispatcherNode              ← zwraca [Send("fetch_source", {"url": url}) for url in sources]
  │                           (wymagany węzeł przed Send() — nie można tego zrobić z edge function)
  ├──► FetchWorkerNode      ← równolegle per źródło (RSS lub trafilatura fallback)
  ├──► FetchWorkerNode
  └──► FetchWorkerNode
  │
  ▼ (fan-in — reducer scala wyniki)
FilterNode                  ← usuwa duplikaty i już widziane artykuły
  │
  ├── [brak nowych] ──► "Nothing new today" ──► DeliveryNode ──► END
  │
  ▼
SummarizerNode              ← TL;DR + główny outcome per artykuł (Claude API)
  │                           izolacja awarii per wywołanie LLM
  ▼
FormatterNode               ← składa ADHD-friendly briefing (max 5 artykułów)
  │
  ▼
DeliveryNode                ← wysyła przez NotificationService (Telegram)
  │
END
```

---

## State — krytyczne poprawki

### BriefingState

```python
from typing import Annotated
import operator

class BriefingState(TypedDict):
    chat_id: str
    sources: list[str]
    raw_articles: Annotated[list[dict], operator.add]   # WYMAGANY reducer dla Send() fan-out
    filtered_articles: list[dict]
    summarized_articles: list[dict]
    briefing: str
```

**⚠️ Bug #1 bez reducera:** Przy Send() fan-oucie każda równoległa gałąź zapisuje do tego samego klucza stanu. Bez `Annotated[list[dict], operator.add]` LangGraph rzuci `InvalidUpdateError`. To najczęstszy błąd przy pierwszym użyciu Send().

### OnboardingState

```python
class OnboardingState(TypedDict):
    chat_id: str
    topics: list[str]
    sources: list[str]
    briefing_time: str        # "07:30"
    timezone: str             # "Europe/Warsaw" — wymagane dla poprawnego schedulingu
    setup_complete: bool
```

---

## Persistence — SqliteSaver (nie MemorySaver)

```python
from langgraph.checkpoint.sqlite import SqliteSaver

checkpointer = SqliteSaver.from_conn_string("adhd.db")
onboarding_graph = onboarding_workflow.compile(checkpointer=checkpointer)
briefing_graph = briefing_workflow.compile(checkpointer=checkpointer)
```

**Dlaczego:** `MemorySaver` gubi stan przy restarcie bota. Onboarding w toku → reset. `SqliteSaver` zapewnia durable execution i wzmacnia wybór SQLite jako jedynego storage.

**Ważne:** Użyj osobnego `thread_id` per `chat_id` — inaczej stany użytkowników się zmieszają:
```python
config = {"configurable": {"thread_id": str(chat_id)}}
```

---

## SQLite — znormalizowany schemat

Obecny single-table schema nie pokrywa faz R i A. Normalizacja teraz — retrofit jest drogi.

```sql
-- Użytkownicy
CREATE TABLE users (
    chat_id     TEXT PRIMARY KEY,
    topics      TEXT,           -- JSON list
    sources     TEXT,           -- JSON list
    briefing_time TEXT,         -- "07:30"
    timezone    TEXT,           -- "Europe/Warsaw"
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Historia briefingów (faza R — kalendarz)
CREATE TABLE briefings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     TEXT REFERENCES users(chat_id),
    date        DATE NOT NULL,
    status      TEXT DEFAULT 'sent',  -- sent | read | skipped
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Artykuły (faza R — retrieval, faza A — akcje)
CREATE TABLE articles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    briefing_id     INTEGER REFERENCES briefings(id),
    url             TEXT NOT NULL,
    title           TEXT,
    summary         TEXT,          -- TL;DR bullets
    main_outcome    TEXT,          -- główny komunikat
    action_suggestion TEXT,        -- co możesz z tym zrobić
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Widziane artykuły (deduplication)
CREATE TABLE seen_articles (
    chat_id     TEXT REFERENCES users(chat_id),
    url         TEXT NOT NULL,
    seen_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, url)
);

-- Akcje użytkownika (faza A — gamifikacja)
CREATE TABLE actions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id  INTEGER REFERENCES articles(id),
    chat_id     TEXT REFERENCES users(chat_id),
    completed   BOOLEAN DEFAULT FALSE,
    completed_at DATETIME
);

-- Idempotencja schedulera
CREATE TABLE briefing_runs (
    chat_id     TEXT REFERENCES users(chat_id),
    run_date    DATE NOT NULL,
    status      TEXT,           -- running | completed | failed
    PRIMARY KEY (chat_id, run_date)
);
```

**Włącz WAL mode** dla lepszej wydajności przy równoczesnych zapisach:
```python
conn.execute("PRAGMA journal_mode=WAL")
```

---

## Scheduler — największa architektoniczna dziura

APScheduler + SqliteJobStore, per-user timezone-aware triggers.

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

scheduler = AsyncIOScheduler(
    jobstores={"default": SQLAlchemyJobStore(url="sqlite:///adhd.db")}
)

# Dodaj job per użytkownik podczas onboardingu
scheduler.add_job(
    send_briefing,
    trigger="cron",
    hour=7, minute=30,
    timezone="Europe/Warsaw",
    args=[chat_id],
    id=f"briefing_{chat_id}",
    replace_existing=True
)
```

**Idempotencja:** Przed uruchomieniem grafu sprawdź tabelę `briefing_runs` — jeden briefing per użytkownik per dzień.

---

## SourceProvider — największe ryzyko techniczne

Założenie że RSS + trafilatura niezawodnie wyciągnie czysty tekst z dowolnych URL-i jest **niezweryfikowane**. To największe ryzyko przed pisaniem grafów.

```python
class SourceProvider(ABC):
    @abstractmethod
    async def fetch(self, url: str) -> list[Article]:
        ...

class RSSProvider(SourceProvider):
    async def fetch(self, url: str) -> list[Article]:
        # feedparser
        ...

class ScraperProvider(SourceProvider):
    async def fetch(self, url: str) -> list[Article]:
        # trafilatura fallback
        ...

def get_provider(url: str) -> SourceProvider:
    # auto-detect RSS vs strona
    ...
```

**Zbuduj i przetestuj `SourceProvider` jako pierwszą rzecz** — zanim napiszesz jakikolwiek kod grafów. Benchmark: czy trafilatura wyciąga czysty tekst z rzeczywistych URL-i użytkownika?

---

## NotificationService — abstrakcja delivery

```python
class NotificationService(ABC):
    @abstractmethod
    async def send(self, chat_id: str, message: str) -> None:
        ...

class TelegramNotifier(NotificationService):
    async def send(self, chat_id: str, message: str) -> None:
        # python-telegram-bot
        ...

# Przyszłość: WhatsAppNotifier, EmailNotifier
```

---

## Co musi być w repo od dnia 1

| Element | Dlaczego |
|---|---|
| `.env.example` | Każdy AI project musi go mieć — bez tego nikt nie postawi |
| `README.md` z tradeoff akapitem | Tłumaczy dlaczego LangGraph dla liniowego pipeline |
| `Dockerfile` | Self-hosted bez Dockera = tarcie |
| `requirements.txt` / `pyproject.toml` | Standardowe |
| Rate limiting dla Claude API | Zapobiega błędom 429 przy wielu źródłach |
| Error handling w FetcherNode | Co gdy RSS feed nie odpowiada? |

---

## Plan pierwszego tygodnia (rekomendacja agenta)

1. **Dzień 1-2:** Zbuduj i przetestuj `SourceProvider` — benchmark na rzeczywistych URL-ach
2. **Dzień 3:** Znormalizowany schemat SQLite + migracje
3. **Dzień 4:** `OnboardingGraph` z `SqliteSaver` i `interrupt()`
4. **Dzień 5:** `BriefingGraph` z poprawnym `Send()` fan-out i reducerami
5. **Dzień 6:** Scheduler (APScheduler + SqliteJobStore)
6. **Dzień 7:** `.env.example`, Dockerfile, README z tradeoff akapitem

---

## Następne fazy (poza MVP)

- **Faza R (Retrieval):** Kalendarz z historią briefingów, search po treści, "co już wiem na ten temat"
- **Faza A (Action):** Sugestie akcji per artykuł, check-off gamifikacja, tygodniowa retrospektywa
- **Personalizacja:** Agent uczy się z odhaczonych akcji
- **Social accountability:** Opcjonalny buddy system (ADHD research: zewnętrzna odpowiedzialność działa lepiej)
- **WhatsApp provider** jako drugi NotificationService
