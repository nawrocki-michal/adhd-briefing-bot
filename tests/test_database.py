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
    expected = {
        "users", "briefings", "articles", "seen_articles",
        "actions", "briefing_runs", "pending_articles",
    }
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


# --- ton briefingu (tone) ---


async def test_tone_defaults_to_neutral(db):
    await db.upsert_user("123", ["AI"], [], "08:00", "Europe/Warsaw")
    user = await db.get_user("123")
    assert user["tone"] == "neutral"


async def test_upsert_with_tone(db):
    await db.upsert_user("123", ["AI"], [], "08:00", "Europe/Warsaw", tone="warm")
    assert (await db.get_user("123"))["tone"] == "warm"


async def test_set_tone_preserves_rest(db):
    await db.upsert_user("123", ["AI"], ["https://a.com"], "08:00", "Europe/Warsaw")
    await db.set_tone("123", "direct")
    user = await db.get_user("123")
    assert user["tone"] == "direct"
    assert user["sources"] == ["https://a.com"]  # reszta profilu nietknięta


async def test_migrate_adds_tone_to_legacy_users(tmp_path):
    """Stara baza bez kolumny tone → init() dokłada ją z defaultem neutral."""
    path = str(tmp_path / "legacy.db")
    async with aiosqlite.connect(path) as conn:
        await conn.execute(
            "CREATE TABLE users (chat_id TEXT PRIMARY KEY, topics TEXT, sources TEXT, "
            "briefing_time TEXT, timezone TEXT, created_at DATETIME)"
        )
        await conn.execute("INSERT INTO users (chat_id) VALUES ('old')")
        await conn.commit()
    database = Database(path)
    await database.init()  # migracja
    user = await database.get_user("old")
    assert user["tone"] == "neutral"


# --- zarządzanie źródłami (add/remove, inkrementalne) ---


async def test_add_sources_appends_without_overwrite(db):
    await db.upsert_user("123", ["AI"], ["https://a.com"], "08:00", "Europe/Warsaw")
    merged = await db.add_sources("123", ["https://b.com"])
    assert merged == ["https://a.com", "https://b.com"]  # stare zachowane
    user = await db.get_user("123")
    assert user["sources"] == ["https://a.com", "https://b.com"]


async def test_add_sources_dedupes_list(db):
    await db.upsert_user("123", [], ["https://a.com"], "08:00", "Europe/Warsaw")
    merged = await db.add_sources("123", ["https://a.com", "https://b.com"])
    assert merged == ["https://a.com", "https://b.com"]  # bez duplikatu a.com


async def test_add_sources_no_user_is_noop(db):
    assert await db.add_sources("ghost", ["https://a.com"]) == []


async def test_remove_source(db):
    await db.upsert_user("123", [], ["https://a.com", "https://b.com"], "08:00", "Europe/Warsaw")
    remaining = await db.remove_source("123", "https://a.com")
    assert remaining == ["https://b.com"]


async def test_remove_source_absent_is_noop(db):
    await db.upsert_user("123", [], ["https://a.com"], "08:00", "Europe/Warsaw")
    assert await db.remove_source("123", "https://nope.com") == ["https://a.com"]


# --- inbox jednorazowy (pending_articles) ---


async def test_add_and_get_pending(db):
    total = await db.add_pending("123", ["https://x.com", "https://y.com"])
    assert total == 2
    assert await db.get_pending("123") == ["https://x.com", "https://y.com"]


async def test_pending_dedupes(db):
    await db.add_pending("123", ["https://x.com"])
    total = await db.add_pending("123", ["https://x.com"])  # PRIMARY KEY → ignore
    assert total == 1


async def test_pending_is_per_user(db):
    await db.add_pending("123", ["https://x.com"])
    assert await db.get_pending("456") == []


async def test_clear_pending(db):
    await db.add_pending("123", ["https://x.com", "https://y.com"])
    await db.clear_pending("123", ["https://x.com"])
    assert await db.get_pending("123") == ["https://y.com"]


async def test_clear_pending_empty_is_noop(db):
    await db.add_pending("123", ["https://x.com"])
    await db.clear_pending("123", [])
    assert await db.get_pending("123") == ["https://x.com"]


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
