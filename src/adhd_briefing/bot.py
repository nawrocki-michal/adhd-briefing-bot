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
from adhd_briefing.graphs.onboarding import build_onboarding_graph
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
            "✅ All set! Send /briefing to get a preview now."
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
    if not snapshot.next:  # onboarding nie trwa
        await update.message.reply_text(
            "Send /start to set up, or /briefing to get your briefing."
        )
        return
    result = await graph.ainvoke(Command(resume=update.message.text), config)
    await _reply_onboarding(update, result)


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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    logger.info("Start pollingu…")
    app.run_polling()


if __name__ == "__main__":
    main()
