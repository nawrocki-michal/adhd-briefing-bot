# ADHD Briefing App — Progress

**Ostatnia aktualizacja:** 2026-06-21

---

## Co zostało zrobione

- [x] Brainstorming — model CRA (Capture, Retrieval, Action) zdefiniowany
- [x] Decyzje produktowe — format briefingu, gamifikacja, tygodniowa retrospektywa
- [x] Decyzje techniczne — Python + LangGraph, Telegram, SQLite, RSS + trafilatura
- [x] Architektura — dwa grafy (OnboardingGraph + BriefingGraph), znormalizowany schemat SQLite
- [x] Przegląd architektoniczny (OMC Architect Agent) — krytyczne pułapki zidentyfikowane
- [x] Instalacja Context7 MCP — aktywny po restarcie Claude Code
- [x] Struktura folderów projektu

### Pliki
- `brainstorming/adhd-app-brainstorming.md` — pełny brainstorming sesji
- `docs/architecture.md` — szczegółowa architektura techniczna

---

## Do zrobienia

### Następny krok — runda prompty + evalsy (M3.5), potem M5 (scheduler)
- [ ] Eval harness streszczeń (golden set, LLM-as-judge, A/B promptów)
- [ ] M5: scheduler (APScheduler + SqliteJobStore, timezone-aware, idempotencja)

### Model źródeł (ważna decyzja UX)
- Źródło = publikacja którą śledzisz (feed/blog), podane **raz** w onboardingu;
  agent codziennie sam wyłapuje **nowe** artykuły (dedup). User nic nie wkleja codziennie.
- Auto-discovery RSS: wklejasz dowolny URL (artykuł/homepage) → agent znajduje feed publikacji.

### MVP — Faza C (Capture)
- [x] **M0** — repo (`git init`, `.gitignore`, `pyproject.toml`, `.env.example`, `config.py`), `pip install -e .` OK
- [x] **M1** — `SourceProvider` (RSS + trafilatura) zbudowany i przetestowany
  - 14/14 testów jednostkowych zielonych (`tests/test_sources.py`)
  - **Benchmark GATE: GO ✅ 5/5** realnych URL-i (`docs/source-benchmark.md`)
- [x] **M2** — warstwa SQLite (`db/schema.sql` + `db/database.py`)
  - 6 znormalizowanych tabel, WAL mode, dedup per-user, idempotencja schedulera
  - 15/15 testów zielonych (`tests/test_database.py`)
- [x] **M3** — BriefingGraph + CLI (**pierwszy działający efekt**)
  - `graphs/state.py` (reducer Bug #1), `graphs/briefing.py` (async, Send() fan-out, conditional edge), `llm/summarizer.py` (Claude Haiku 4.5, structured outputs, semafor + retry), `cli.py`
  - LangGraph 1.x: Send() z funkcji routującej conditional edge (Bug #5 nieaktualny dla 1.x)
  - 8/8 testów grafu; **realny briefing po polsku z 5 URL-i przez Claude API**; dedup zweryfikowany na żywo
  - całość: 37/37 testów zielonych
- [x] **M4** — Telegram + OnboardingGraph
  - `notify/` (NotificationService + TelegramNotifier z fallbackiem Markdown→plain)
  - `graphs/onboarding.py` (interrupt() HITL, parsery, zapis usera), `bot.py` (/start, /briefing, on_text)
  - AsyncSqliteSaver z trwałym połączeniem (Bug #3), thread_id per user (Bug #2)
  - 14/14 nowych testów; **bot przetestowany na żywo na Telegramie — działa**
  - pytest: `pythonpath=["src"]` (niezależne od editable .pth); całość 51/51
- [x] **M4.5** — auto-discovery RSS + fix pobierania feedów
  - `sources/discovery.py` (link rel=alternate + fallback /feed); `fetch_articles` preferuje feed
  - **fix:** RSSProvider pobiera feed przez httpx z UA przeglądarki (feedparser z domyślnym UA był blokowany 403 → tylko 1 art.)
  - na żywo: 15-20 artykułów ze źródła (wcześniej 1); 57/57 testów, ruff czysty
- [ ] `OnboardingGraph` z `SqliteSaver` i `interrupt()`
- [ ] `BriefingGraph` z Send() fan-out i reducerami
- [ ] Scheduler (APScheduler + SqliteJobStore, timezone-aware)
- [ ] Telegram bot integration
- [ ] `Dockerfile`
- [ ] `README.md` z tradeoff akapitem o LangGraph

### Przyszłe fazy
- [ ] Faza R — Retrieval (kalendarz, historia, search)
- [ ] Faza A — Action (sugestie akcji, gamifikacja, tygodniowa retrospektywa)
- [ ] WhatsApp jako drugi NotificationService provider
