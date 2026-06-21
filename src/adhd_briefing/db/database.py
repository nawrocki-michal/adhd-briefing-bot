"""Async warstwa dostępu do SQLite (aiosqlite, WAL mode).

Tabele aplikacji żyją w tej samej bazie co checkpointy LangGraph (AsyncSqliteSaver) —
WAL mode jest obowiązkowy dla równoczesnych zapisów scheduler + bot + checkpointer.
"""

import json
from datetime import date
from pathlib import Path

import aiosqlite

from adhd_briefing.models import Article

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class Database:
    """Cienki async wrapper na SQLite z helperami domenowymi."""

    def __init__(self, path: str) -> None:
        self.path = path

    async def init(self) -> None:
        """Tworzy schemat i włącza WAL (persystentny na poziomie pliku bazy)."""
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA foreign_keys=ON")
            await db.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
            await db.commit()

    # --- users ---

    async def upsert_user(
        self,
        chat_id: str,
        topics: list[str],
        sources: list[str],
        briefing_time: str,
        timezone: str,
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO users (chat_id, topics, sources, briefing_time, timezone)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    topics=excluded.topics,
                    sources=excluded.sources,
                    briefing_time=excluded.briefing_time,
                    timezone=excluded.timezone
                """,
                (chat_id, json.dumps(topics), json.dumps(sources), briefing_time, timezone),
            )
            await db.commit()

    async def get_user(self, chat_id: str) -> dict | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM users WHERE chat_id = ?", (chat_id,)
            ) as cur:
                row = await cur.fetchone()
        if row is None:
            return None
        user = dict(row)
        user["topics"] = json.loads(user["topics"]) if user["topics"] else []
        user["sources"] = json.loads(user["sources"]) if user["sources"] else []
        return user

    async def list_users(self) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT chat_id FROM users") as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # --- deduplication (seen_articles) ---

    async def mark_seen(self, chat_id: str, url: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO seen_articles (chat_id, url) VALUES (?, ?)",
                (chat_id, url),
            )
            await db.commit()

    async def is_seen(self, chat_id: str, url: str) -> bool:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT 1 FROM seen_articles WHERE chat_id = ? AND url = ?",
                (chat_id, url),
            ) as cur:
                return await cur.fetchone() is not None

    async def filter_unseen(self, chat_id: str, urls: list[str]) -> set[str]:
        """Zwraca podzbiór URL-i, których użytkownik jeszcze nie widział."""
        if not urls:
            return set()
        placeholders = ",".join("?" * len(urls))
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                f"SELECT url FROM seen_articles WHERE chat_id = ? AND url IN ({placeholders})",
                (chat_id, *urls),
            ) as cur:
                seen = {row[0] for row in await cur.fetchall()}
        return set(urls) - seen

    # --- briefings + articles ---

    async def save_briefing(
        self, chat_id: str, run_date: date, articles: list[Article]
    ) -> int:
        """Zapisuje briefing + jego artykuły, oznacza URL-e jako widziane. Zwraca briefing_id."""
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "INSERT INTO briefings (chat_id, date) VALUES (?, ?)",
                (chat_id, run_date.isoformat()),
            )
            briefing_id = cur.lastrowid
            for art in articles:
                await db.execute(
                    "INSERT INTO articles (briefing_id, url, title) VALUES (?, ?, ?)",
                    (briefing_id, art.url, art.title),
                )
                await db.execute(
                    "INSERT OR IGNORE INTO seen_articles (chat_id, url) VALUES (?, ?)",
                    (chat_id, art.url),
                )
            await db.commit()
        return briefing_id

    # --- idempotencja schedulera (briefing_runs) ---

    async def record_run(self, chat_id: str, run_date: date, status: str = "completed") -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO briefing_runs (chat_id, run_date, status)
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id, run_date) DO UPDATE SET status=excluded.status
                """,
                (chat_id, run_date.isoformat(), status),
            )
            await db.commit()

    async def is_run_done(self, chat_id: str, run_date: date) -> bool:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT 1 FROM briefing_runs WHERE chat_id = ? AND run_date = ? AND status = 'completed'",
                (chat_id, run_date.isoformat()),
            ) as cur:
                return await cur.fetchone() is not None
