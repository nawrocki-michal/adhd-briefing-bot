"""Telegram bot — /start (onboarding), /briefing (on-demand) i scheduler (codziennie).

Uruchomienie:
    PYTHONPATH=src .venv/bin/python -m adhd_briefing.bot
"""

import logging
from datetime import date, datetime, timezone

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from adhd_briefing.config import settings
from adhd_briefing.db import Database
from adhd_briefing.graphs.briefing import build_briefing_graph
from adhd_briefing.graphs.onboarding import (
    build_onboarding_graph,
    normalize_time,
    parse_sources,
    parse_tone,
)
from adhd_briefing.llm import Summarizer
from adhd_briefing.models import Article
from adhd_briefing.notify import TelegramNotifier
from adhd_briefing.scheduler import BriefingScheduler, resolve_timezone

logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s", level=logging.INFO
)
logger = logging.getLogger("adhd_briefing.bot")

# Doklejane, gdy scheduler nadrabia briefing pominięty przy wyłączonym bocie.
_LATE_NOTE = "⏰ _Catching up — this one is late._\n\n"


def _onboarding_config(chat_id: str) -> dict:
    return {"configurable": {"thread_id": chat_id}}  # Bug #2: per-user thread


def _briefing_config(chat_id: str) -> dict:
    return {"configurable": {"thread_id": f"briefing_{chat_id}"}}


def _initial_briefing_state(chat_id: str, sources: list[str], tone: str = "neutral") -> dict:
    return {
        "chat_id": chat_id,
        "sources": sources,
        "tone": tone,
        "pending_urls": [],  # prepare() doczyta inbox z DB
        "raw_articles": [],
        "filtered_articles": [],
        "summarized_articles": [],
        "briefing": "",
    }


async def _reply_onboarding(
    update: Update, context: ContextTypes.DEFAULT_TYPE, result: dict
) -> None:
    interrupts = result.get("__interrupt__")
    if interrupts:
        await update.message.reply_text(interrupts[0].value)
        return
    if not result.get("setup_complete"):
        return
    # Onboarding domknięty — zaplanuj codzienny briefing od razu, bez restartu bota.
    chat_id = str(update.effective_chat.id)
    await _sync_schedule(context, chat_id)
    when = result.get("briefing_time") or "your chosen time"
    await update.message.reply_text(
        f"✅ All set! I'll send your briefing daily at {when}. "
        "Send /briefing for a preview now, or just paste article links "
        "anytime to add them to your next briefing."
    )


async def _sync_schedule(context: ContextTypes.DEFAULT_TYPE, chat_id: str) -> None:
    """Przebudowuje job schedulera z aktualnego wiersza users (no-op bez schedulera)."""
    scheduler: BriefingScheduler | None = context.bot_data.get("scheduler")
    if scheduler:
        await scheduler.sync_user(chat_id)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    graph = context.bot_data["onboarding"]
    result = await graph.ainvoke(
        {
            "chat_id": chat_id,
            "topics": [],
            "sources": [],
            "briefing_time": "",
            "timezone": "",
            "tone": "neutral",
            "setup_complete": False,
        },
        _onboarding_config(chat_id),
    )
    await _reply_onboarding(update, context, result)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    graph = context.bot_data["onboarding"]
    config = _onboarding_config(chat_id)
    snapshot = await graph.aget_state(config)
    if snapshot.next:  # onboarding trwa — przekaż odpowiedź do grafu
        result = await graph.ainvoke(Command(resume=update.message.text), config)
        await _reply_onboarding(update, context, result)
        return

    # Poza onboardingiem: wklejone linki → inbox jednorazowy (capture).
    urls = parse_sources(update.message.text)
    if urls:
        await _queue_for_briefing(update, context, chat_id, urls)
        return

    await update.message.reply_text(
        "Send links to add them to your next briefing, "
        "/briefing for one now, or /sources to manage what you follow."
    )


async def _queue_for_briefing(
    update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: str, urls: list[str]
) -> None:
    db: Database = context.bot_data["db"]
    user = await db.get_user(chat_id)
    if not user:
        await update.message.reply_text("First send /start to set up your briefing.")
        return
    total = await db.add_pending(chat_id, urls)
    when = user.get("briefing_time") or "your next briefing"
    noun = "link" if len(urls) == 1 else "links"
    await update.message.reply_text(
        f"📥 Added {len(urls)} {noun} — you'll get the summary in your briefing at {when} "
        f"({total} queued)."
    )


async def briefing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    db: Database = context.bot_data["db"]
    user = await db.get_user(chat_id)
    if not user or not user.get("sources"):
        await update.message.reply_text("First send /start — you don't have any sources set up yet.")
        return

    await update.message.reply_text("⏳ Generating your briefing…")
    # Ręczny /briefing NIE zapisuje briefing_runs — to rejestr schedulera.
    # Podgląd o 6:00 nie ma kasować briefingu zaplanowanego na 7:30;
    # powtórzeniom treści zapobiega seen_articles.
    await _deliver_briefing(context.bot_data, chat_id)


async def _deliver_briefing(bot_data: dict, chat_id: str, *, late: bool = False) -> dict:
    """Generuje i dostarcza briefing. Wspólne dla handlera /briefing i schedulera.

    Nie zależy od `Update` — scheduler woła to bez żadnej wiadomości od użytkownika.
    Zwraca stan grafu (przydatne w testach i do logowania kosztu).
    """
    db: Database = bot_data["db"]
    user = await db.get_user(chat_id)
    if not user or not user.get("sources"):
        return {}

    graph = bot_data["briefing"]
    state = await graph.ainvoke(
        _initial_briefing_state(chat_id, user["sources"], user.get("tone") or "neutral"),
        _briefing_config(chat_id),
    )

    notifier: TelegramNotifier = bot_data["notifier"]
    message = state["briefing"]
    if late:
        message = _LATE_NOTE + message
    await notifier.send(chat_id, message)

    summarized = state.get("summarized_articles", [])
    if summarized:
        articles = [
            Article(
                url=a["url"],
                title=a.get("title", ""),
                content=a.get("content", ""),
                source_url=a.get("source_url", a["url"]),
                published_at=datetime.now(timezone.utc),
            )
            for a in summarized
        ]
        await db.save_briefing(chat_id, date.today(), articles)

    # Obserwowalność kosztów: zapisz zużycie tokenów i zaloguj szacowany koszt briefingu.
    usage = state.get("usage")
    if usage:
        cost = await db.record_usage(chat_id, usage)
        logger.info(
            "Briefing %s: %d art., in=%d out=%d tok, ~$%.4f",
            chat_id,
            usage.get("articles", 0),
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
            cost,
        )

    # Inbox jednorazowy: czyść wszystko, co próbowaliśmy dostarczyć (one-shot,
    # bez ponawiania martwych linków). Dostarczone URL-e są już oznaczone jako seen.
    await db.clear_pending(chat_id, state.get("pending_urls", []))
    return state


def _format_sources(sources: list[str]) -> str:
    lines = [f"{i}. {url}" for i, url in enumerate(sources, 1)]
    return "\n".join(lines)


async def sources_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    db: Database = context.bot_data["db"]
    user = await db.get_user(chat_id)
    if not user:
        await update.message.reply_text("First send /start to set up your briefing.")
        return
    sources = user.get("sources") or []
    if not sources:
        await update.message.reply_text(
            "You're not following any sources yet. Add one with /addsource <url>."
        )
        return
    await update.message.reply_text(
        "📚 *Sources you follow:*\n"
        + _format_sources(sources)
        + "\n\nAdd with /addsource <url>, remove with /removesource <number>.",
        parse_mode="Markdown",
    )


async def addsource_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    db: Database = context.bot_data["db"]
    user = await db.get_user(chat_id)
    if not user:
        await update.message.reply_text("First send /start to set up your briefing.")
        return
    urls = parse_sources(" ".join(context.args))
    if not urls:
        await update.message.reply_text("Usage: /addsource <url> [url2 …]")
        return
    sources = await db.add_sources(chat_id, urls)
    await _sync_schedule(context, chat_id)
    await update.message.reply_text(
        f"✅ Now following {len(sources)} sources:\n" + _format_sources(sources)
    )


async def removesource_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    db: Database = context.bot_data["db"]
    user = await db.get_user(chat_id)
    if not user:
        await update.message.reply_text("First send /start to set up your briefing.")
        return
    sources = user.get("sources") or []
    arg = context.args[0] if context.args else ""
    target = None
    if arg.isdigit() and 1 <= int(arg) <= len(sources):
        target = sources[int(arg) - 1]
    elif arg in sources:
        target = arg
    if target is None:
        await update.message.reply_text(
            "Usage: /removesource <number> (see /sources) or <url>."
        )
        return
    remaining = await db.remove_source(chat_id, target)
    await _sync_schedule(context, chat_id)
    msg = f"🗑️ Removed. {len(remaining)} sources left."
    if remaining:
        msg += "\n" + _format_sources(remaining)
    await update.message.reply_text(msg)


async def tone_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    db: Database = context.bot_data["db"]
    user = await db.get_user(chat_id)
    if not user:
        await update.message.reply_text("First send /start to set up your briefing.")
        return
    if not context.args:
        current = user.get("tone") or "neutral"
        await update.message.reply_text(
            f"Current tone: *{current}*.\n"
            "Change it with /tone neutral | warm | direct.",
            parse_mode="Markdown",
        )
        return
    tone = parse_tone(" ".join(context.args))
    await db.set_tone(chat_id, tone)
    await update.message.reply_text(f"✅ Briefing tone set to *{tone}*.", parse_mode="Markdown")


async def time_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/time [HH:MM] [IANA timezone] — pora briefingu bez przechodzenia /start od nowa."""
    chat_id = str(update.effective_chat.id)
    db: Database = context.bot_data["db"]
    user = await db.get_user(chat_id)
    if not user:
        await update.message.reply_text("First send /start to set up your briefing.")
        return

    if not context.args:
        tz = user.get("timezone") or settings.default_timezone
        current = user.get("briefing_time") or "not set"
        lines = [f"Briefing time: *{current}* ({tz})."]
        scheduler: BriefingScheduler | None = context.bot_data.get("scheduler")
        upcoming = scheduler.next_run(chat_id) if scheduler else None
        if upcoming:
            lines.append(f"Next one: {upcoming:%a %d %b, %H:%M %Z}.")
        lines.append("Change it with /time 07:30 (optionally /time 07:30 Europe/London).")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    briefing_time = normalize_time(context.args[0])
    tz_name = None
    if len(context.args) > 1:
        candidate = context.args[1]
        # Waliduj strefę zanim ją zapiszesz — zła nazwa uciszyłaby scheduler na cicho.
        if resolve_timezone(candidate).key != candidate:
            await update.message.reply_text(
                f"Unknown timezone {candidate!r}. Use an IANA name like Europe/Warsaw."
            )
            return
        tz_name = candidate

    await db.set_schedule(chat_id, briefing_time, tz_name)
    await _sync_schedule(context, chat_id)

    tz = tz_name or user.get("timezone") or settings.default_timezone
    await update.message.reply_text(
        f"✅ Briefing time set to *{briefing_time}* ({tz}).", parse_mode="Markdown"
    )


async def _post_init(app: Application) -> None:
    db = Database(settings.db_path)
    await db.init()

    # AsyncSqliteSaver z trwałym połączeniem aiosqlite — żyje przez cały czas pracy bota.
    conn = await aiosqlite.connect(settings.db_path)
    checkpointer = AsyncSqliteSaver(conn)
    await checkpointer.setup()

    summarizer = Summarizer()
    app.bot_data["db"] = db
    app.bot_data["onboarding"] = build_onboarding_graph(db, checkpointer=checkpointer)
    # BriefingGraph jest wsadowy i bezstanowy (brak interrupt()) — NIE checkpointujemy go.
    # Z trwałym checkpointerem reducer operator.add na raw_articles akumulowałby fetch
    # każdego /briefing między uruchomieniami (stare/usunięte źródła wracały w kółko).
    # Dedup między dniami zapewnia tabela seen_articles, nie checkpoint.
    app.bot_data["briefing"] = build_briefing_graph(db, summarizer)
    app.bot_data["notifier"] = TelegramNotifier(app.bot)

    # Scheduler startuje NA KOŃCU: catch-up potrafi dostarczyć briefing od razu,
    # więc graf i notifier muszą już być w bot_data. AsyncIOScheduler wiąże się
    # z bieżącą pętlą asyncio — post_init działa wewnątrz pętli PTB, więc to tutaj.
    async def deliver(chat_id: str, *, late: bool = False) -> None:
        await _deliver_briefing(app.bot_data, chat_id, late=late)

    scheduler = BriefingScheduler(
        db,
        deliver,
        misfire_grace_time=settings.scheduler_misfire_grace_time,
        catch_up=settings.briefing_catch_up,
    )
    app.bot_data["scheduler"] = scheduler
    await scheduler.start()

    logger.info("Bot zainicjalizowany — onboarding + briefing + scheduler gotowe.")


async def _post_shutdown(app: Application) -> None:
    scheduler: BriefingScheduler | None = app.bot_data.get("scheduler")
    if scheduler:
        await scheduler.shutdown()


def main() -> None:
    if not settings.telegram_bot_token:
        raise SystemExit("Brak TELEGRAM_BOT_TOKEN w .env")

    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("briefing", briefing))
    app.add_handler(CommandHandler("sources", sources_cmd))
    app.add_handler(CommandHandler("addsource", addsource_cmd))
    app.add_handler(CommandHandler("removesource", removesource_cmd))
    app.add_handler(CommandHandler("tone", tone_cmd))
    app.add_handler(CommandHandler("time", time_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    logger.info("Start pollingu…")
    app.run_polling()


if __name__ == "__main__":
    main()
