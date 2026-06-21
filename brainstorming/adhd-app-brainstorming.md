# ADHD Briefing App — Brainstorming

**Data:** 2026-06-21  
**Cel portfolio:** Pokazanie umiejętności technicznych (multi-agent AI) rekruterowi  
**Kontekst:** PM rozwijający umiejętności techniczne, z ADHD — jest jednocześnie głównym użytkownikiem

---

## Problem

Osoby z ADHD zmagają się z:
- Nadmiarem bodźców i decentralizacją wiedzy
- Prokrastynacją i trudnością w kończeniu zadań
- Trudnością w skupieniu się na czytaniu i przetwarzaniu informacji
- Brakiem mostu między "przeczytałem coś ciekawego" a "zrobiłem z tym cokolwiek"

**Kluczowy insight:** tldr.tech działa na format — ale nie domyka pętli. Brakuje mostu między wiedzą a działaniem.

---

## Model CRA

### C — Capture
- Użytkownik podaje źródła które już śledzi (ufa im)
- Agent agreguje nowe treści z tych źródeł
- Codziennie rano dostarcza **ADHD-friendly briefing**:
  - TL;DR bullet points
  - Główny komunikat / outcome każdego artykułu
  - Max **5 artykułów** per briefing
- Dostawa: **Telegram** (cron o ustalonej godzinie + komenda `/briefing` on-demand)

### R — Retrieval
- **Kalendarz** z historią poprzednich dni
- Check-off na poziomie dnia (agent wie co przeczytane / nieprzeczytane)
- Możliwość powrotu do dowolnego dnia

### A — Action
- Do każdego artykułu **generyczne sugestie akcji** ("co możesz z tym zrobić")
- Użytkownik odhaczycha akcję gdy ją wykona → **gamifikacja**
- Co 7 dni **tygodniowa retrospektywa** — podsumowanie co zrobiono, motywacja do dalszej pracy

---

## Decyzje techniczne

| Decyzja | Wybór | Uzasadnienie |
|---|---|---|
| Framework agentów | **LangGraph** | Najlepiej pokazuje rozumienie grafów stanów |
| Język | **Python** | Ekosystem AI |
| Delivery | **Telegram** | Setup 2 min, markdown out of the box, łatwy do postawienia z GitHuba |
| Trigger | **Cron (user-defined time) + `/briefing`** | Elastyczność, jeden graf — dwa entry pointy |
| Źródła | **RSS + fallback scraper** | RSS = 90% przypadków; `trafilatura` jako fallback dla stron bez RSS |
| Storage | **SQLite** | Zero konfiguracji, działa lokalnie od razu po `git clone` |
| Onboarding | **Konwersacja z botem w Telegram** | AI-native, zero frontendu, low friction dla ADHD |
| Frontend | **Brak** | Cały UX przez Telegram |
| Dystrybucja | **GitHub, self-hosted** | Każdy może postawić lokalnie |
| Delivery abstraction | `NotificationService` z providerami | Telegram teraz, WhatsApp/inne jako PR #2 |

---

## Architektura LangGraph

### Graf: Briefing Pipeline

```
START
  │
  ▼
FetcherNode          ← pobiera artykuły z RSS/URL źródeł (równolegle via Send() API)
  │
  ▼
FilterNode           ← usuwa duplikaty i już widziane artykuły
  │                    [conditional edge: brak nowych → "nothing new today"]
  ▼
SummarizerNode       ← TL;DR + główny outcome per artykuł (Claude API)
  │
  ▼
FormatterNode        ← składa ADHD-friendly briefing (max 5 artykułów)
  │
  ▼
DeliveryNode         ← wysyła na Telegram
  │
END
```

### Graf: Onboarding Pipeline

```
/start
  │
  ▼
TopicsNode           ← pyta o zainteresowania użytkownika
  │
  ▼
SourcesNode          ← zbiera źródła (linki do stron lub RSS)
  │
  ▼
ScheduleNode         ← ustala godzinę dostarczania briefingu
  │
  ▼
ConfirmNode          ← potwierdza setup, opcjonalny preview (/briefing)
  │
END → zapisuje do SQLite
```

### State (Briefing)

```python
class BriefingState(TypedDict):
    sources: list[str]
    raw_articles: list[dict]
    filtered_articles: list[dict]
    summarized_articles: list[dict]
    briefing: str
    chat_id: str
```

### Storage Schema (SQLite)

```sql
users
├── chat_id         TEXT PRIMARY KEY
├── topics          TEXT (JSON list)
├── sources         TEXT (JSON list)
├── briefing_time   TEXT (e.g. "07:30")
└── last_seen       TEXT (JSON list of article URLs)
```

---

## Onboarding Flow (Telegram)

```
Użytkownik: /start

Bot: Cześć! Jestem twoim ADHD briefing assistant.
     Zacznijmy setup. Jakie tematy cię interesują?
     (np. "AI, product management, startupy")

Użytkownik: AI, no-code, growth hacking

Bot: Super. Teraz dodaj źródła które już czytasz.
     Możesz wkleić linki do stron lub RSS feeds.
     Wpisz /done gdy skończysz.

Użytkownik: https://techcrunch.com
            https://www.producthunt.com

Bot: O której chcesz dostawać briefing? (domyślnie 08:00)

Użytkownik: 7:30

Bot: Gotowe! Jutro o 7:30 dostaniesz pierwszego briefinga.
     Wpisz /briefing jeśli chcesz teraz podgląd.
```

---

## Co to pokazuje rekruterowi

- Multi-agent orchestration z LangGraph (grafy stanów, conditional edges, Send() API)
- Dwa osobne grafy: OnboardingAgent + BriefingAgent
- Integracje: Telegram Bot API, RSS parsing, web scraping
- Abstrakcja delivery (`NotificationService`) — rozszerzalność bez over-engineeringu
- State persistence (SQLite)
- Dual-trigger architecture (cron + on-demand)
- Self-hostable z GitHub — każdy może postawić

---

## Następne fazy (R i A — do brainstormingu osobno)

- **Retrieval:** Kalendarz z historią, search po treści, "co już wiem na ten temat"
- **Action:** Sugestie akcji per artykuł, check-off, gamifikacja, tygodniowa retrospektywa
- **Personalizacja:** Agent uczy się z odhaczonych akcji (które trwają <10 min preferowane?)
- **Social:** Opcjonalny buddy system dla zewnętrznej odpowiedzialności (ADHD research: działa lepiej niż self-accountability)
