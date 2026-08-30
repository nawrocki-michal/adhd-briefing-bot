"""Testy schedulera (M5) — planowanie z bazy, idempotencja, catch-up, strefy czasowe.

Zegar jest wstrzykiwany (`clock=`), więc testy nie zależą od realnej godziny —
bez tego „czy termin już minął" byłoby flaky raz na dobę.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from adhd_briefing.db import Database
from adhd_briefing.scheduler import (
    BriefingScheduler,
    job_id,
    parse_hhmm,
    resolve_timezone,
)


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.init()
    return database


@pytest.fixture
async def user(db):
    await db.upsert_user(
        chat_id="42",
        topics=["ai"],
        sources=["https://example.com/feed"],
        briefing_time="07:30",
        timezone="Europe/Warsaw",
    )
    return "42"


class DeliverySpy:
    """Podstawia się pod `_deliver_briefing` — zapisuje wywołania, opcjonalnie rzuca."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, bool]] = []
        self.error = error

    async def __call__(self, chat_id: str, *, late: bool = False) -> None:
        self.calls.append((chat_id, late))
        if self.error:
            raise self.error


def frozen_clock(moment: datetime):
    """Zegar zwracający `moment` przeliczony do żądanej strefy."""

    def _clock(tz):
        return moment.astimezone(tz)

    return _clock


# --- helpery czystych funkcji ---


@pytest.mark.parametrize(
    "value,expected",
    [
        ("07:30", (7, 30)),
        ("00:00", (0, 0)),
        ("23:59", (23, 59)),
        ("7:05", (7, 5)),
        ("", (8, 0)),  # fallback
        ("garbage", (8, 0)),
        ("25:00", (8, 0)),  # poza zakresem
        ("07:60", (8, 0)),
    ],
)
def test_parse_hhmm(value, expected):
    assert parse_hhmm(value) == expected


def test_resolve_timezone_valid():
    assert resolve_timezone("America/New_York").key == "America/New_York"


def test_resolve_timezone_falls_back_on_garbage():
    # Zła strefa nie może wywrócić schedulera — cichy fallback do domyślnej.
    assert resolve_timezone("Mars/Olympus_Mons").key == "Europe/Warsaw"


def test_resolve_timezone_falls_back_on_none():
    assert resolve_timezone(None).key == "Europe/Warsaw"


# --- sync_user: joby budowane z bazy ---


async def test_sync_user_schedules_job_at_user_time(db, user):
    scheduler = BriefingScheduler(db, DeliverySpy())
    assert await scheduler.sync_user(user) is True

    job = scheduler.scheduler.get_job(job_id(user))
    assert job is not None
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["hour"] == "7"
    assert fields["minute"] == "30"
    assert str(job.trigger.timezone) == "Europe/Warsaw"


async def test_sync_user_skips_user_without_sources(db):
    await db.upsert_user(
        chat_id="99", topics=[], sources=[], briefing_time="07:30", timezone="Europe/Warsaw"
    )
    scheduler = BriefingScheduler(db, DeliverySpy())
    assert await scheduler.sync_user("99") is False
    assert scheduler.scheduler.get_job(job_id("99")) is None


async def test_sync_user_unschedules_when_sources_removed(db, user):
    scheduler = BriefingScheduler(db, DeliverySpy())
    await scheduler.sync_user(user)
    assert scheduler.scheduler.get_job(job_id(user)) is not None

    await db.remove_source(user, "https://example.com/feed")
    assert await scheduler.sync_user(user) is False
    assert scheduler.scheduler.get_job(job_id(user)) is None


async def test_sync_user_replaces_job_after_time_change(db, user):
    scheduler = BriefingScheduler(db, DeliverySpy())
    await scheduler.sync_user(user)

    await db.set_schedule(user, "21:15", "America/New_York")
    await scheduler.sync_user(user)

    jobs = [j for j in scheduler.scheduler.get_jobs() if j.id == job_id(user)]
    assert len(jobs) == 1  # replace_existing, nie duplikat
    fields = {f.name: str(f) for f in jobs[0].trigger.fields}
    assert (fields["hour"], fields["minute"]) == ("21", "15")
    assert str(jobs[0].trigger.timezone) == "America/New_York"


async def test_sync_all_counts_schedulable_users(db, user):
    await db.upsert_user(
        chat_id="no-sources", topics=[], sources=[], briefing_time="07:30", timezone="UTC"
    )
    scheduler = BriefingScheduler(db, DeliverySpy())
    assert await scheduler.sync_all() == 1


# --- _fire: idempotencja przez briefing_runs ---


async def test_fire_delivers_and_records_run(db, user):
    spy = DeliverySpy()
    now = datetime(2026, 7, 1, 7, 30, tzinfo=ZoneInfo("Europe/Warsaw"))
    scheduler = BriefingScheduler(db, spy, clock=frozen_clock(now))

    assert await scheduler._fire(user) is True
    assert spy.calls == [(user, False)]
    assert await db.is_run_done(user, date(2026, 7, 1)) is True


async def test_fire_is_idempotent_within_a_day(db, user):
    spy = DeliverySpy()
    now = datetime(2026, 7, 1, 7, 30, tzinfo=ZoneInfo("Europe/Warsaw"))
    scheduler = BriefingScheduler(db, spy, clock=frozen_clock(now))

    assert await scheduler._fire(user) is True
    assert await scheduler._fire(user) is False  # drugi strzał tego samego dnia
    assert len(spy.calls) == 1


async def test_fire_runs_again_next_day(db, user):
    spy = DeliverySpy()
    day1 = datetime(2026, 7, 1, 7, 30, tzinfo=ZoneInfo("Europe/Warsaw"))
    scheduler = BriefingScheduler(db, spy, clock=frozen_clock(day1))
    await scheduler._fire(user)

    scheduler._clock = frozen_clock(day1 + timedelta(days=1))
    assert await scheduler._fire(user) is True
    assert len(spy.calls) == 2


async def test_fire_records_failure_and_allows_retry(db, user):
    spy = DeliverySpy(error=RuntimeError("feed down"))
    now = datetime(2026, 7, 1, 7, 30, tzinfo=ZoneInfo("Europe/Warsaw"))
    scheduler = BriefingScheduler(db, spy, clock=frozen_clock(now))

    # Wyjątek dostawy nie może wypłynąć do schedulera (ubiłby joba).
    assert await scheduler._fire(user) is False
    # 'failed' != 'completed' → dzień pozostaje do nadrobienia.
    assert await db.is_run_done(user, date(2026, 7, 1)) is False

    spy.error = None
    assert await scheduler._fire(user) is True


async def test_fire_uses_user_timezone_for_run_date(db):
    """23:30 w Warszawie to wciąż 21:30 UTC — data runu musi iść za użytkownikiem."""
    await db.upsert_user(
        chat_id="tz",
        topics=[],
        sources=["https://example.com/feed"],
        briefing_time="23:30",
        timezone="Europe/Warsaw",
    )
    # 2026-07-01 23:30 Warsaw == 2026-07-01 21:30 UTC (ta sama data)
    # ale 2026-07-02 00:30 Warsaw == 2026-07-01 22:30 UTC (różne daty)
    moment = datetime(2026, 7, 1, 22, 30, tzinfo=ZoneInfo("UTC"))
    scheduler = BriefingScheduler(db, DeliverySpy(), clock=frozen_clock(moment))

    await scheduler._fire("tz")
    assert await db.is_run_done("tz", date(2026, 7, 2)) is True  # data lokalna użytkownika
    assert await db.is_run_done("tz", date(2026, 7, 1)) is False


# --- catch-up po restarcie ---


async def test_catch_up_delivers_missed_briefing(db, user):
    spy = DeliverySpy()
    # Bot wstał o 09:00, briefing miał być o 07:30 — nadrób.
    now = datetime(2026, 7, 1, 9, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
    scheduler = BriefingScheduler(db, spy, clock=frozen_clock(now))

    assert await scheduler.catch_up() == [user]
    assert spy.calls == [(user, True)]  # oznaczony jako spóźniony


async def test_catch_up_skips_before_scheduled_time(db, user):
    spy = DeliverySpy()
    # 06:00 — termin 07:30 jeszcze przed nami, cron się tym zajmie.
    now = datetime(2026, 7, 1, 6, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
    scheduler = BriefingScheduler(db, spy, clock=frozen_clock(now))

    assert await scheduler.catch_up() == []
    assert spy.calls == []


async def test_catch_up_skips_already_delivered_day(db, user):
    spy = DeliverySpy()
    now = datetime(2026, 7, 1, 9, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
    scheduler = BriefingScheduler(db, spy, clock=frozen_clock(now))
    await db.record_run(user, date(2026, 7, 1), "completed")

    assert await scheduler.catch_up() == []
    assert spy.calls == []


async def test_catch_up_retries_failed_run(db, user):
    spy = DeliverySpy()
    now = datetime(2026, 7, 1, 9, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
    scheduler = BriefingScheduler(db, spy, clock=frozen_clock(now))
    await db.record_run(user, date(2026, 7, 1), "failed")

    assert await scheduler.catch_up() == [user]


async def test_catch_up_skips_user_without_sources(db):
    await db.upsert_user(
        chat_id="empty", topics=[], sources=[], briefing_time="07:30", timezone="Europe/Warsaw"
    )
    spy = DeliverySpy()
    now = datetime(2026, 7, 1, 9, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
    scheduler = BriefingScheduler(db, spy, clock=frozen_clock(now))

    assert await scheduler.catch_up() == []


async def test_catch_up_disabled_by_flag(db, user):
    spy = DeliverySpy()
    now = datetime(2026, 7, 1, 9, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
    scheduler = BriefingScheduler(db, spy, clock=frozen_clock(now), catch_up=False)

    await scheduler.start()
    try:
        assert spy.calls == []
        assert scheduler.scheduler.get_job(job_id(user)) is not None  # job i tak zaplanowany
    finally:
        await scheduler.shutdown()


async def test_start_schedules_and_catches_up(db, user):
    spy = DeliverySpy()
    now = datetime(2026, 7, 1, 9, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
    scheduler = BriefingScheduler(db, spy, clock=frozen_clock(now))

    await scheduler.start()
    try:
        assert scheduler.scheduler.running
        assert scheduler.next_run(user) is not None
        assert spy.calls == [(user, True)]
    finally:
        await scheduler.shutdown()
    assert not scheduler.scheduler.running


# --- integracja: scheduler → realny _deliver_briefing z bot.py ---


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, chat_id: str, message: str) -> None:
        self.sent.append((chat_id, message))


async def test_scheduler_delivers_through_real_bot_path(db, user, monkeypatch):
    """Spina scheduler z prawdziwym `_deliver_briefing` — łapie rozjazd sygnatur/bot_data."""
    from adhd_briefing import bot as bot_module
    from adhd_briefing.graphs.briefing import build_briefing_graph
    from adhd_briefing.models import Article

    article = Article(
        url="https://example.com/a",
        title="Tytuł",
        content="słowo " * 200,
        source_url="https://example.com/feed",
        published_at=None,
    )

    async def fake_fetch(url: str) -> list[Article]:
        return [article]

    class FakeSummarizer:
        async def summarize(self, art: dict, tone: str = "neutral") -> dict:
            return {**art, "tldr": ["bullet"], "main_outcome": "wniosek", "_usage": {}}

    monkeypatch.setattr("adhd_briefing.graphs.briefing.fetch_articles", fake_fetch)

    notifier = FakeNotifier()
    bot_data = {
        "db": db,
        "briefing": build_briefing_graph(db, FakeSummarizer()),
        "notifier": notifier,
    }

    async def deliver(chat_id: str, *, late: bool = False) -> None:
        await bot_module._deliver_briefing(bot_data, chat_id, late=late)

    now = datetime(2026, 7, 1, 9, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
    scheduler = BriefingScheduler(db, deliver, clock=frozen_clock(now))

    assert await scheduler.catch_up() == [user]
    assert len(notifier.sent) == 1
    chat_id, message = notifier.sent[0]
    assert chat_id == user
    assert message.startswith(bot_module._LATE_NOTE)  # adnotacja o spóźnieniu
    assert "Tytuł" in message
    assert await db.is_run_done(user, date(2026, 7, 1)) is True
