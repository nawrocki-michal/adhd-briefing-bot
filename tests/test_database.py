"""Testy warstwy SQLite — dedup, idempotencja, WAL, użytkownicy."""

from datetime import date

import aiosqlite
import pytest

from adhd_briefing.db import Database
from adhd_briefing.models import Article


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.init()
    return database


async def test_init_enables_wal(db):
    async with aiosqlite.connect(db.path) as conn:
        async with conn.execute("PRAGMA journal_mode") as cur:
            mode = (await cur.fetchone())[0]
    assert mode.lower() == "wal"


async def test_init_creates_all_tables(db):
    expected = {"users", "briefings", "articles", "seen_articles", "actions", "briefing_runs"}
    async with aiosqlite.connect(db.path) as conn:
        async with conn.execute("SELECT name FROM sqlite_master WHERE type='table'") as cur:
            tables = {row[0] async for row in cur}
    assert expected <= tables


async def test_init_is_idempotent(db):
    await db.init()  # drugie uruchomienie nie może rzucić
    await db.init()


# --- users ---


async def test_upsert_and_get_user(db):
    await db.upsert_user("123", ["AI", "PM"], ["https://x.com"], "07:30", "Europe/Warsaw")
    user = await db.get_user("123")
    assert user["topics"] == ["AI", "PM"]
    assert user["sources"] == ["https://x.com"]
    assert user["briefing_time"] == "07:30"
    assert user["timezone"] == "Europe/Warsaw"


async def test_upsert_overwrites(db):
    await db.upsert_user("123", ["AI"], [], "07:30", "Europe/Warsaw")
    await db.upsert_user("123", ["growth"], ["https://y.com"], "09:00", "Europe/London")
    user = await db.get_user("123")
    assert user["topics"] == ["growth"]
    assert user["briefing_time"] == "09:00"


async def test_get_missing_user_returns_none(db):
    assert await db.get_user("nope") is None


# --- dedup ---


async def test_mark_and_is_seen(db):
    assert await db.is_seen("123", "https://a.com") is False
    await db.mark_seen("123", "https://a.com")
    assert await db.is_seen("123", "https://a.com") is True


async def test_seen_is_per_user(db):
    await db.mark_seen("123", "https://a.com")
    assert await db.is_seen("456", "https://a.com") is False


async def test_mark_seen_idempotent(db):
    await db.mark_seen("123", "https://a.com")
    await db.mark_seen("123", "https://a.com")  # PRIMARY KEY — nie może rzucić
    assert await db.is_seen("123", "https://a.com") is True


async def test_filter_unseen(db):
    await db.mark_seen("123", "https://seen.com")
    unseen = await db.filter_unseen("123", ["https://seen.com", "https://new.com"])
    assert unseen == {"https://new.com"}


async def test_filter_unseen_empty(db):
    assert await db.filter_unseen("123", []) == set()


# --- save_briefing ---


async def test_save_briefing_persists_and_marks_seen(db):
    articles = [
        Article(url="https://a.com", title="A", content="...", source_url="https://src"),
        Article(url="https://b.com", title="B", content="...", source_url="https://src"),
    ]
    bid = await db.save_briefing("123", date(2026, 6, 21), articles)
    assert isinstance(bid, int)
    # artykuły oznaczone jako widziane
    assert await db.is_seen("123", "https://a.com") is True
    assert await db.is_seen("123", "https://b.com") is True


# --- idempotencja schedulera ---


async def test_run_idempotency(db):
    d = date(2026, 6, 21)
    assert await db.is_run_done("123", d) is False
    await db.record_run("123", d, "completed")
    assert await db.is_run_done("123", d) is True


async def test_run_per_user_per_day(db):
    d = date(2026, 6, 21)
    await db.record_run("123", d, "completed")
    assert await db.is_run_done("456", d) is False  # inny user
    assert await db.is_run_done("123", date(2026, 6, 22)) is False  # inny dzień


async def test_run_status_running_not_done(db):
    d = date(2026, 6, 21)
    await db.record_run("123", d, "running")
    assert await db.is_run_done("123", d) is False  # tylko 'completed' liczy się jako done
    await db.record_run("123", d, "completed")
    assert await db.is_run_done("123", d) is True
