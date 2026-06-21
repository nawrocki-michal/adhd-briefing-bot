"""Telegram bot — entry pointy /start (onboarding) i /briefing (briefing on-demand).

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
from adhd_briefing.graphs.onboarding import build_onboarding_graph, parse_sources
from adhd_briefing.llm import Summarizer
from adhd_briefing.models import Article
from adhd_briefing.notify import TelegramNotifier

logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s", level=logging.INFO
)
logger = logging.getLogger("adhd_briefing.bot")


def _onboarding_config(chat_id: str) -> dict:
    return {"configurable": {"thread_id": chat_id}}  # Bug #2: per-user thread


def _briefing_config(chat_id: str) -> dict:
    return {"configurable": {"thread_id": f"briefing_{chat_id}"}}


def _initial_briefing_state(chat_id: str, sources: list[str]) -> dict:
    return {
        "chat_id": chat_id,
        "sources": sources,
        "pending_urls": [],  # prepare() doczyta inbox z DB
        "raw_articles": [],
        "filtered_articles": [],
        "summarized_articles": [],
        "briefing": "",
    }


async def _reply_onboarding(update: Update, result: dict) -> None:
    interrupts = result.get("__interrupt__")
    if interrupts:
        await update.message.reply_text(interrupts[0].value)
    elif result.get("setup_complete"):
        await update.message.reply_text(
            "✅ All set! Send /briefing for a preview now, or just paste article "
            "links anytime to add them to your next briefing."
        )


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
            "setup_complete": False,
        },
        _onboarding_config(chat_id),
    )
    await _reply_onboarding(update, result)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    graph = context.bot_data["onboarding"]
    config = _onboarding_config(chat_id)
    snapshot = await graph.aget_state(config)
    if snapshot.next:  # onboarding trwa — przekaż odpowiedź do grafu
        result = await graph.ainvoke(Command(resume=update.message.text), config)
        await _reply_onboarding(update, result)
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
    graph = context.bot_data["briefing"]
    state = await graph.ainvoke(
        _initial_briefing_state(chat_id, user["sources"]),
        _briefing_config(chat_id),
    )

    notifier: TelegramNotifier = context.bot_data["notifier"]
    await notifier.send(chat_id, state["briefing"])

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

    # Inbox jednorazowy: czyść wszystko, co próbowaliśmy dostarczyć (one-shot,
    # bez ponawiania martwych linków). Dostarczone URL-e są już oznaczone jako seen.
    await db.clear_pending(chat_id, state.get("pending_urls", []))


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
    msg = f"🗑️ Removed. {len(remaining)} sources left."
    if remaining:
        msg += "\n" + _format_sources(remaining)
    await update.message.reply_text(msg)


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
    app.bot_data["briefing"] = build_briefing_graph(db, summarizer, checkpointer=checkpointer)
    app.bot_data["notifier"] = TelegramNotifier(app.bot)
    logger.info("Bot zainicjalizowany — onboarding + briefing gotowe.")


def main() -> None:
    if not settings.telegram_bot_token:
        raise SystemExit("Brak TELEGRAM_BOT_TOKEN w .env")

    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("briefing", briefing))
    app.add_handler(CommandHandler("sources", sources_cmd))
    app.add_handler(CommandHandler("addsource", addsource_cmd))
    app.add_handler(CommandHandler("removesource", removesource_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    logger.info("Start pollingu…")
    app.run_polling()


if __name__ == "__main__":
    main()
