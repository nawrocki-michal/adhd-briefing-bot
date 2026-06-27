"""Async warstwa dostępu do SQLite (aiosqlite, WAL mode).

Tabele aplikacji żyją w tej samej bazie co checkpointy LangGraph (AsyncSqliteSaver) —
WAL mode jest obowiązkowy dla równoczesnych zapisów scheduler + bot + checkpointer.
"""

import json
from datetime import date
from pathlib import Path

import aiosqlite

from adhd_briefing.llm.pricing import estimate_cost
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
            await self._migrate(db)
            await db.commit()

    async def _migrate(self, db: aiosqlite.Connection) -> None:
        """Lekkie migracje dla istniejących baz (CREATE IF NOT EXISTS nie dołoży kolumny)."""
        async with db.execute("PRAGMA table_info(users)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
        if "tone" not in cols:
            await db.execute("ALTER TABLE users ADD COLUMN tone TEXT DEFAULT 'neutral'")

    # --- users ---

    async def upsert_user(
        self,
        chat_id: str,
        topics: list[str],
        sources: list[str],
        briefing_time: str,
        timezone: str,
        tone: str = "neutral",
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO users (chat_id, topics, sources, briefing_time, timezone, tone)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    topics=excluded.topics,
                    sources=excluded.sources,
                    briefing_time=excluded.briefing_time,
                    timezone=excluded.timezone,
                    tone=excluded.tone
                """,
                (
                    chat_id,
                    json.dumps(topics),
                    json.dumps(sources),
                    briefing_time,
                    timezone,
                    tone,
                ),
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
        user["tone"] = user.get("tone") or "neutral"
        return user

    async def set_tone(self, chat_id: str, tone: str) -> None:
        """Zmienia ton briefingu bez nadpisywania reszty profilu (inaczej niż /start)."""
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE users SET tone = ? WHERE chat_id = ?", (tone, chat_id)
            )
            await db.commit()

    async def list_users(self) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT chat_id FROM users") as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def add_sources(self, chat_id: str, urls: list[str]) -> list[str]:
        """Dokleja źródła do listy użytkownika (bez nadpisywania). Zwraca pełną listę.

        Deduplikuje samą listę (zachowując kolejność: istniejące + nowe).
        No-op jeśli użytkownik nie istnieje albo brak URL-i do dodania.
        """
        user = await self.get_user(chat_id)
        if user is None:
            return []
        current = user["sources"]
        merged = list(current)
        for url in urls:
            if url not in merged:
                merged.append(url)
        if merged != current:
            await self._set_sources(chat_id, merged)
        return merged

    async def remove_source(self, chat_id: str, url: str) -> list[str]:
        """Usuwa pojedyncze źródło. Zwraca pozostałą listę (bez zmian jeśli nie było)."""
        user = await self.get_user(chat_id)
        if user is None:
            return []
        remaining = [s for s in user["sources"] if s != url]
        if remaining != user["sources"]:
            await self._set_sources(chat_id, remaining)
        return remaining

    async def _set_sources(self, chat_id: str, sources: list[str]) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE users SET sources = ? WHERE chat_id = ?",
                (json.dumps(sources), chat_id),
            )
            await db.commit()

    # --- inbox jednorazowy (pending_articles) ---

    async def add_pending(self, chat_id: str, urls: list[str]) -> int:
        """Dodaje URL-e do inboxa jednorazowego. Zwraca liczbę zakolejkowanych łącznie."""
        async with aiosqlite.connect(self.path) as db:
            for url in urls:
                await db.execute(
                    "INSERT OR IGNORE INTO pending_articles (chat_id, url) VALUES (?, ?)",
                    (chat_id, url),
                )
            await db.commit()
        return len(await self.get_pending(chat_id))

    async def get_pending(self, chat_id: str) -> list[str]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT url FROM pending_articles WHERE chat_id = ? ORDER BY added_at",
                (chat_id,),
            ) as cur:
                return [row[0] for row in await cur.fetchall()]

    async def clear_pending(self, chat_id: str, urls: list[str]) -> None:
        """Usuwa z inboxa dostarczone URL-e (po udanej wysyłce briefingu)."""
        if not urls:
            return
        placeholders = ",".join("?" * len(urls))
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                f"DELETE FROM pending_articles WHERE chat_id = ? AND url IN ({placeholders})",
                (chat_id, *urls),
            )
            await db.commit()

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

    # --- obserwowalność kosztów LLM (llm_usage) ---

    async def record_usage(self, chat_id: str, usage: dict) -> float:
        """Zapisuje zużycie tokenów briefingu i zwraca jego szacowany koszt w USD.

        usage: {model, input_tokens, output_tokens, articles} z grafu briefingu.
        Wpis z zerowym zużyciem (np. briefing bez nowych artykułów) jest pomijany.
        """
        model = usage.get("model") or ""
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        if not (input_tokens or output_tokens):
            return 0.0
        cost = estimate_cost(model, input_tokens, output_tokens)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO llm_usage (chat_id, model, input_tokens, output_tokens, cost_usd, articles)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (chat_id, model, input_tokens, output_tokens, cost, usage.get("articles", 0)),
            )
            await db.commit()
        return cost

    async def usage_total(self, chat_id: str, since: date) -> dict:
        """Sumuje koszt i tokeny użytkownika od daty `since` (do budżetu/raportu)."""
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                """
                SELECT COALESCE(SUM(cost_usd), 0), COALESCE(SUM(input_tokens), 0),
                       COALESCE(SUM(output_tokens), 0), COUNT(*)
                FROM llm_usage
                WHERE chat_id = ? AND created_at >= ?
                """,
                (chat_id, since.isoformat()),
            ) as cur:
                cost, in_tok, out_tok, runs = await cur.fetchone()
        return {
            "cost_usd": cost,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "runs": runs,
        }
