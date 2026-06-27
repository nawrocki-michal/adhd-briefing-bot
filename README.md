# ADHD Briefing Bot

A self-hostable Telegram bot that turns the blogs and feeds you care about into a single, short, **ADHD-friendly daily briefing** — summarized by Claude, delivered where you already are.

It's built around a simple insight: people with ADHD don't have a *reading* problem, they have a *starting* and *filtering* problem. Ten open tabs never get read. One five-item briefing does. The bot does the filtering and summarizing so the only thing left is to read five short blurbs.

> Status: **MVP works end-to-end locally** (onboarding → fetch → summarize → deliver). Summary quality is measured with an LLM-as-judge eval harness (~94–98/100). Scheduler (automatic daily delivery) is the next milestone — today briefings are triggered on demand with `/briefing`.

---

## Why this project exists

This is a portfolio project. The goal was to build something I'd actually use every day while demonstrating real multi-agent / LLM engineering — not a toy demo:

- A **stateful, conversational onboarding** flow (human-in-the-loop) running on a different execution model than the **batch, autonomous briefing** pipeline.
- **Quality measured, not vibes-based**: every summarizer prompt change is scored by an eval harness before it ships.
- **Self-hostable from day one**: `.env.example`, `Dockerfile`, SQLite-on-a-volume — clone, set two secrets, run.

## Features

- 💬 **Conversational onboarding** (`/start`) — pick topics, sources, and a delivery time through a real back-and-forth, not a form.
- 📰 **Smart fetching** — give it any site URL; it auto-discovers the RSS feed, and falls back to full-text scraping when there's no feed.
- 🧠 **ADHD-friendly summaries** — Claude condenses each article into a scannable blurb with an estimated read time, guided by explicit content guidelines.
- 🎚️ **Tone as a user choice** — `neutral` / `warm` / `direct` presets (`/tone`), so the briefing matches how you like to be talked to.
- 🗂️ **Incremental source management** — `/sources`, `/addsource`, `/removesource` without re-running onboarding.
- 📥 **One-shot inbox** — paste any link (no command) and it's delivered in your next briefing, then forgotten.
- ✅ **Deduplication** — you never see the same article twice.

## Architecture

The system is two **deliberately separate** LangGraph graphs, because they have fundamentally different execution shapes:

### OnboardingGraph — conversational, human-in-the-loop
`TopicsNode → SourcesNode → ScheduleNode → ToneNode → ConfirmNode`
Each node uses LangGraph's `interrupt()` to pause and wait for the user's reply. State is persisted with `AsyncSqliteSaver` and a per-user `thread_id`, so an in-progress onboarding survives a bot restart and users never bleed into each other.

### BriefingGraph — batch, autonomous, fan-out/fan-in
`prepare → [fetch_worker × N] → filter → summarize → format`
Sources are fetched in parallel via LangGraph's `Send()` (returned from a conditional edge), then fanned back in through a reducer (`Annotated[list, operator.add]`) before filtering and summarizing. The graph produces the formatted briefing text; delivery to Telegram is handled by the `NotificationService` once the graph returns.

### "Why LangGraph for a mostly-linear pipeline?"

A fair question — the briefing flow is *almost* a straight line, and you could write it as a plain async function. LangGraph earns its place here for three concrete reasons:

1. **Parallel fan-out with a clean join.** Fetching N sources concurrently and merging the results is exactly what `Send()` + a reducer express declaratively — the alternative is hand-rolled `asyncio.gather` plus manual result-merging and error handling.
2. **Human-in-the-loop for free.** The onboarding graph's `interrupt()`/resume model and durable checkpointing are the hard part of any conversational flow; getting them from the framework (rather than building a state machine by hand) is the whole point.
3. **It's the showcase.** This is a portfolio piece about agent orchestration — modeling the work as explicit state graphs makes the design legible and is itself the thing being demonstrated.

The cost is honest: a framework dependency and some boilerplate. For this project the visibility and the HITL machinery are worth it; for a purely linear, single-source job they would not be.

A few architectural decisions are load-bearing and documented in [`CLAUDE.md`](CLAUDE.md) and [`docs/architecture.md`](docs/architecture.md): the briefing graph is **not** checkpointed (it's stateless; dedup lives in the `seen_articles` table), RSS feeds are fetched with a browser User-Agent (default feedparser UA gets 403'd by some hosts), and SQLite runs in WAL mode.

## Tech stack

| Concern | Choice |
|---|---|
| Agent framework | LangGraph (state graphs, `Send()`, `interrupt()`) |
| LLM | Claude (Haiku for summaries) via the Anthropic SDK |
| Delivery | Telegram Bot API (`python-telegram-bot`) |
| Storage | SQLite (WAL mode), zero-config |
| Fetching | `feedparser` (RSS) + `trafilatura` (full-text fallback) |
| Config | `pydantic-settings` (`.env`) |
| Quality | Custom eval harness with LLM-as-judge (Claude Sonnet) |

## Prerequisites

Before you start, make sure you have:

- **Python 3.11+** (or **Docker**, if you'd rather run it in a container — see [Run with Docker](#run-with-docker)).
- **A Telegram bot token** — message [@BotFather](https://t.me/BotFather), send `/newbot`, and copy the token it gives you.
- **An Anthropic API key** — create one at [console.anthropic.com](https://console.anthropic.com). Note that generating briefings makes real (paid) Claude API calls.
- **A Telegram account** to actually talk to your bot.
- `git` to clone the repo.

No database to set up: SQLite is created automatically on first run. No public URL or webhook either — the bot uses long-polling.

## Quickstart (local)

```bash
git clone <your-fork-url> adhd-briefing && cd adhd-briefing
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env        # then fill in TELEGRAM_BOT_TOKEN and ANTHROPIC_API_KEY
```

Run the bot (long-polling — no public URL needed):

```bash
PYTHONPATH=src .venv/bin/python -m adhd_briefing.bot
```

Then message your bot on Telegram: `/start` to onboard, `/briefing` to get one now.

Prefer to see the pipeline without Telegram? The CLI prints a briefing to stdout:

```bash
PYTHONPATH=src .venv/bin/python -m adhd_briefing.cli \
  --chat-id me --sources "https://evilmartians.com"
```

## Run with Docker

```bash
docker build -t adhd-briefing .
docker run -d --name adhd-briefing \
  --env-file .env \
  -v adhd_data:/data \
  adhd-briefing
```

The SQLite database lives on the `adhd_data` volume (`DB_PATH=/data/adhd.db` is set in the image), so it survives restarts and redeploys. The same image runs unchanged on any container host (Fly.io, an Oracle Cloud free VM, a Raspberry Pi, etc.).

## Bot commands

| Command | What it does |
|---|---|
| `/start` | Conversational onboarding (topics, sources, schedule, tone) |
| `/briefing` | Generate and deliver a briefing right now |
| `/sources` | List your tracked sources |
| `/addsource <url…>` | Add one or more sources (incremental, deduped) |
| `/removesource <n\|url>` | Remove a source by number or URL |
| `/tone [neutral\|warm\|direct]` | Show or set the briefing tone |
| *(paste a link)* | Adds it to a one-shot inbox, delivered in your next briefing |

## Testing & quality

```bash
.venv/bin/python -m pytest -q          # 86 tests, fully mocked — no network/LLM
.venv/bin/ruff check src/ evals/        # lint
```

Summary quality is treated as a first-class, measurable property. The `evals/` harness (which makes **real** LLM calls and is intentionally kept out of the pytest suite) scores the summarizer with an LLM-as-judge against a golden set, and supports A/B testing prompt variants:

```bash
PYTHONPATH=src .venv/bin/python -m evals.run validate      # judge discriminates good vs. bad
PYTHONPATH=src .venv/bin/python -m evals.run summarizer     # baseline quality score
PYTHONPATH=src .venv/bin/python -m evals.prompt_variants    # A/B prompt comparison
```

Rule of thumb in this repo: **changing the summarizer prompt means re-running the eval** before committing.

## Project layout

```
src/adhd_briefing/
├── config.py        # settings from .env (pydantic-settings)
├── sources/         # RSS + scraper providers, feed auto-discovery
├── db/              # SQLite schema + async data layer (WAL, dedup, idempotency)
├── llm/             # Claude summarizer (structured output, ADHD prompt)
├── graphs/          # BriefingGraph + OnboardingGraph (+ shared state)
├── notify/          # NotificationService abstraction → TelegramNotifier
├── cli.py           # run a briefing without Telegram
└── bot.py           # Telegram entry point
evals/               # eval harness (golden set, judge, prompt A/B)
docs/                # architecture, content guidelines, progress, dev guide
```

More detail in [`docs/dev-guide.md`](docs/dev-guide.md) (setup, commands, where the prompts live).

## Roadmap

- [ ] **Scheduler** — automatic daily delivery at a chosen time (APScheduler; idempotency table already in the schema).
- [ ] Tone-preset A/B in the eval harness.
- [ ] *Retrieval* phase — searchable history of past briefings.
- [ ] *Action* phase — per-article action suggestions, weekly retrospective.
- [ ] WhatsApp as a second `NotificationService`.

## A note on the docs

Some in-repo docs (`CLAUDE.md`, `docs/`) are written in Polish — they're the working notes that drove the build, including the agent instructions used while developing with Claude Code. They're kept in the repo on purpose, as a record of how the project was actually built. This README and all user-facing bot content are in English.

## License

[MIT](LICENSE) © 2026 Michał Nawrocki
