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

### Następny krok — M2 (warstwa SQLite)
- [ ] Znormalizowany schemat SQLite + migracje (aiosqlite, WAL, dedup, idempotencja)

### MVP — Faza C (Capture)
- [x] **M0** — repo (`git init`, `.gitignore`, `pyproject.toml`, `.env.example`, `config.py`), `pip install -e .` OK
- [x] **M1** — `SourceProvider` (RSS + trafilatura) zbudowany i przetestowany
  - 14/14 testów jednostkowych zielonych (`tests/test_sources.py`)
  - **Benchmark GATE: GO ✅ 5/5** realnych URL-i (`docs/source-benchmark.md`)
- [ ] Znormalizowany schemat SQLite z migracjami
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
