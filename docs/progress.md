# ADHD Briefing App — Progress

**Ostatnia aktualizacja:** 2026-06-21
**Status:** MVP Faza C (Capture) działa end-to-end + eval harness. Pozostało: hosting, scheduler, packaging.

---

## TL;DR — gdzie jesteśmy

Działający Telegram bot: `/start` (konwersacyjny onboarding) → `/briefing` (pobiera feedy
Twoich źródeł, streszcza przez Claude Haiku, dostarcza ADHD-friendly briefing). Treści po
**angielsku**. Jakość streszczeń mierzona evalem (LLM-as-judge): **98/100** po A/B promptów.
Wszystko lokalne — **brak jeszcze hostingu (always-on) i automatycznego schedulera**.

**Jak uruchomić / wrócić do projektu:** patrz `docs/dev-guide.md`.

---

## Zrobione

### Faza przygotowawcza
- [x] Brainstorming — model CRA (Capture, Retrieval, Action) — `brainstorming/adhd-app-brainstorming.md`
- [x] Architektura + przegląd architektoniczny — `docs/architecture.md` (krytyczne pułapki #1–#5)
- [x] Context7 MCP aktywny; plan MVP — `.omc/plans/mvp-faza-c-capture.md`

### MVP — Faza C (Capture) — DZIAŁA
- [x] **M0** — bootstrap: `pyproject.toml`, `.gitignore`, `.env.example`, `config.py` (pydantic-settings)
- [x] **M1** — `SourceProvider` (RSS + trafilatura), auto-detekcja + fallback
  - Benchmark GATE GO 5/5 realnych URL-i (`docs/source-benchmark.md`)
- [x] **M2** — warstwa SQLite (`db/schema.sql` + `db/database.py`): 6 tabel, WAL, dedup, idempotencja
- [x] **M3** — `BriefingGraph` + CLI: async, Send() fan-out + reducer, Haiku summarizer, dedup
- [x] **M4** — Telegram bot + `OnboardingGraph`: interrupt() HITL, AsyncSqliteSaver, thread_id per user
  - **przetestowany na żywo na Telegramie — działa**
- [x] **M4.5** — auto-discovery RSS (`sources/discovery.py`) + fix pobierania feedów przez httpx (UA)
- [x] **i18n** — całość treści + UI bota przełączone na angielski

### Jakość — prompty + evalsy (M3.5)
- [x] Wytyczne ADHD (`docs/adhd-content-guidelines.md`) → rubryka 9 wymiarów
- [x] Eval harness (`evals/`): syntetyczny golden set, LLM-as-judge (Sonnet 4.6), auto-checki, runner
  - eval zwalidowany: discrimination 8/8 (odróżnia dobre warianty od złych)
- [x] Iteracja promptu mierzona evalem: **84 → 87 → 93**
- [x] A/B 3 wariantów promptu (skill `finalize-agent-prompt`): **C kontrastywny 96.5** > baseline 94.8 > A 93.5 > B 92.0
  - wykryta i naprawiona kontaminacja evala (przykład w wariancie używał case'a z golden setu)
  - wdrożony wariant C → standardowy eval **98/100**

### Zarządzanie źródłami + inbox jednorazowy (M4.6)
- [x] **Stałe źródła — inkrementalnie:** `/sources` (lista), `/addsource <url…>` (doklej, dedup),
  `/removesource <nr|url>`. DB: `add_sources`/`remove_source` (read-modify-write listy JSON).
  Domyka lukę: dotąd jedyną drogą był `/start`, który **nadpisywał** całą listę.
- [x] **Inbox jednorazowy (capture):** bare-paste linku (bez komendy) → kolejka `pending_articles`
  → dostarczane w najbliższym briefingu, potem czyszczone (one-shot). Tabela `pending_articles`.
  - pobierane przez **`fetch_single`** (ScraperProvider wprost — omija auto-discovery feedu, które
    dla URL-a konkretnego artykułu zwracało posty całej witryny zamiast tego tekstu)
  - artykuły z inboxa są **pinned**: omijają filtr `seen_articles` (wklejone świadomie), ale po
    dostawie trafiają do `seen` (nie wrócą w dziennym briefingu śledzonego źródła)
  - oba strumienie (stałe źródła + inbox) wpadają do jednego briefingu; `prepare` doczytuje inbox z DB
  - ⚠️ do czasu M5 „o wybranej godzinie" = przy ręcznym `/briefing`; scheduler dołoży automatyzm bez zmian w tej logice

**Stan testów:** 69/69 pytest zielonych (było 57; +12 dla źródeł/inboxa), ruff czysty.

---

## Do zrobienia (decyzje + następne kroki)

### 🔴 Decyzja: hosting (always-on) — NIEROZSTRZYGNIĘTE
Cel: bot ma działać 24/7, nie tylko lokalnie.
- **Vercel odrzucony** — serverless/bezstanowy, brak trwałego dysku, timeouty funkcji (wymagałby
  przepisania: webhook + Postgres + cron). Nie pasuje do always-on stateful bota.
- Realne opcje (ten sam kod + Dockerfile, **zero przeróbek**):
  - **Fly.io** — deploy kontenera + persistent volume; karta do weryfikacji. Dobre do portfolio (deploy+kontener).
  - **Oracle Cloud Always Free VM** — $0 forever, własna VM (ARM); karta; więcej setupu (ssh/docker).
  - **Własny sprzęt 24/7** (RPi/stary laptop) — w 100% darmowe, zero kart; minus: musi być włączone.
- Rozstrzygnięcie: portfolio/nauka → Fly.io; ma po prostu działać → własny sprzęt; $0 forever → Oracle.
- ⚠️ Trwałość: zostajemy przy SQLite na trwałym dysku/volume (zero zmian w kodzie).

### 🟡 Decyzja: feature tonu (ustalona, do implementacji)
- **tone-as-user-choice** — user wybiera ton w onboardingu: 3 presety `neutral` / `warm` / `direct`.
  Wymaga: pytanie w onboardingu + kolumna `users.tone` + parametr promptu summarizera.
- **read-time** per artykuł w formacie briefingu (≈200 wpm; przybliżone dla feedów).

### Następne milestone'y (kolejność wg rekomendacji)
- [ ] **tone-as-user-choice + read-time** (domyka decyzję produktową)
- [ ] **M5 — Scheduler** — automatyczny codzienny briefing (APScheduler + SQLAlchemyJobStore,
  timezone-aware, idempotencja przez tabelę `briefing_runs` — już w schemacie)
- [ ] **M6 — README + Dockerfile** — self-hostable repo na GitHub; README z akapitem tradeoff o LangGraph
- [ ] (opcjonalnie) rozszerzenie golden setu + A/B presetów tonu w evalu

### Przyszłe fazy (poza MVP)
- [ ] Faza R — Retrieval (kalendarz historii, search) — tabele `briefings`/`articles` już gotowe
- [ ] Faza A — Action (sugestie akcji per artykuł, gamifikacja, tygodniowa retrospektywa) — tabela `actions` gotowa
- [ ] WhatsApp jako drugi `NotificationService` provider

---

## Niuanse / długi techniczny (do zapamiętania)
- **O'Reilly auto-discovery** łapie feed *podcastu* (pierwszy `<link rel=alternate>`), nie Radar.
  Do dopracowania: preferować główny feed nad podcastem.
- **Email case** w evalu: Haiku czasem powtarza main_outcome w pierwszym bullecie — limit modelu,
  nie warto overfittować na 2-elementowym golden secie.
- Editable install (`pip install -e .`) bywa kapryśny w sandboxie → testy używają `pythonpath=["src"]`,
  a uruchomienia modułów: `PYTHONPATH=src .venv/bin/python -m ...`.
