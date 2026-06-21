"""CLI — uruchamia BriefingGraph ręcznie (vertical slice M3, bez Telegrama).

Użycie:
    python -m adhd_briefing.cli --sources url1,url2 [--chat-id cli]
"""

import argparse
import asyncio
from datetime import date, datetime, timezone

from adhd_briefing.config import settings
from adhd_briefing.db import Database
from adhd_briefing.graphs.briefing import build_briefing_graph
from adhd_briefing.llm import Summarizer
from adhd_briefing.models import Article


async def run(sources: list[str], chat_id: str) -> str:
    db = Database(settings.db_path)
    await db.init()

    summarizer = Summarizer()
    graph = build_briefing_graph(db, summarizer)

    state = await graph.ainvoke(
        {
            "chat_id": chat_id,
            "sources": sources,
            "pending_urls": [],
            "raw_articles": [],
            "filtered_articles": [],
            "summarized_articles": [],
            "briefing": "",
        }
    )

    # Persist: zapisz briefing + oznacz artykuły jako widziane (dedup przy kolejnym runie).
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

    return state["briefing"]


def main() -> None:
    parser = argparse.ArgumentParser(description="ADHD Briefing — CLI (vertical slice)")
    parser.add_argument(
        "--sources",
        required=True,
        help="URL-e źródeł rozdzielone przecinkami",
    )
    parser.add_argument("--chat-id", default="cli", help="Identyfikator użytkownika (dedup)")
    args = parser.parse_args()

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    briefing = asyncio.run(run(sources, args.chat_id))
    print("\n" + briefing + "\n")


if __name__ == "__main__":
    main()
