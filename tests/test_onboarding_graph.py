"""Testy OnboardingGraph — parsery + pełny przepływ interrupt/resume + zapis usera."""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from adhd_briefing.db import Database
from adhd_briefing.graphs.onboarding import (
    build_onboarding_graph,
    normalize_time,
    parse_sources,
    parse_tone,
    parse_topics,
)


# --- parsery ---


def test_parse_topics():
    assert parse_topics("AI, product, startupy") == ["AI", "product", "startupy"]
    assert parse_topics("AI\nproduct\n") == ["AI", "product"]


def test_parse_sources_keeps_only_urls():
    text = "https://a.com, http://b.com\nto nie url\nhttps://c.com"
    assert parse_sources(text) == ["https://a.com", "http://b.com", "https://c.com"]


def test_parse_sources_empty():
    assert parse_sources("brak linków tutaj") == []


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1", "neutral"),
        ("2", "warm"),
        ("3", "direct"),
        ("warm", "warm"),
        ("Direct please", "direct"),
        ("bez sensu", "neutral"),  # fallback
    ],
)
def test_parse_tone(raw, expected):
    assert parse_tone(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("7:30", "07:30"),
        ("07:30", "07:30"),
        ("7", "07:00"),
        ("o 9 rano", "09:00"),
        ("25:99", "08:00"),  # nieprawidłowe → default
        ("bez liczb", "08:00"),
    ],
)
def test_normalize_time(raw, expected):
    assert normalize_time(raw) == expected


# --- pełny przepływ z interrupt/resume ---


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "onb.db"))
    await database.init()
    return database


async def test_full_onboarding_flow_saves_user(db):
    graph = build_onboarding_graph(db, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "123"}}

    init = {
        "chat_id": "123",
        "topics": [],
        "sources": [],
        "briefing_time": "",
        "timezone": "",
        "tone": "neutral",
        "setup_complete": False,
    }

    # start → interrupt na pytanie o tematy
    r = await graph.ainvoke(init, config)
    assert "topics" in r["__interrupt__"][0].value.lower()

    # tematy → interrupt na źródła
    r = await graph.ainvoke(Command(resume="AI, growth"), config)
    assert "sources" in r["__interrupt__"][0].value.lower()

    # źródła → interrupt na godzinę
    r = await graph.ainvoke(Command(resume="https://x.com\nhttps://y.com"), config)
    assert "time" in r["__interrupt__"][0].value.lower()

    # godzina → interrupt na ton
    r = await graph.ainvoke(Command(resume="7:30"), config)
    assert "sound" in r["__interrupt__"][0].value.lower()

    # ton → confirm → koniec
    r = await graph.ainvoke(Command(resume="2"), config)
    assert r.get("setup_complete") is True
    assert "__interrupt__" not in r

    # user zapisany w DB
    user = await db.get_user("123")
    assert user["topics"] == ["AI", "growth"]
    assert user["sources"] == ["https://x.com", "https://y.com"]
    assert user["briefing_time"] == "07:30"
    assert user["timezone"]  # ustawione z default_timezone
    assert user["tone"] == "warm"  # "2" → warm


async def test_sources_node_reprompts_on_no_urls(db):
    graph = build_onboarding_graph(db, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "456"}}
    init = {
        "chat_id": "456",
        "topics": [],
        "sources": [],
        "briefing_time": "",
        "timezone": "",
        "tone": "neutral",
        "setup_complete": False,
    }

    await graph.ainvoke(init, config)
    await graph.ainvoke(Command(resume="AI"), config)  # → pyta o źródła
    # odpowiedź bez URL-i → ponowne pytanie o źródła
    r = await graph.ainvoke(Command(resume="nie mam linków"), config)
    assert "sources" in r["__interrupt__"][0].value.lower()
    # teraz poprawny URL → przechodzi dalej (pyta o godzinę)
    r = await graph.ainvoke(Command(resume="https://z.com"), config)
    assert "time" in r["__interrupt__"][0].value.lower()


async def test_threads_isolated_per_user(db):
    graph = build_onboarding_graph(db, checkpointer=InMemorySaver())
    init = lambda cid: {  # noqa: E731
        "chat_id": cid,
        "topics": [],
        "sources": [],
        "briefing_time": "",
        "timezone": "",
        "tone": "neutral",
        "setup_complete": False,
    }
    # user A i B onboardują się równolegle na osobnych thread_id
    await graph.ainvoke(init("A"), {"configurable": {"thread_id": "A"}})
    await graph.ainvoke(init("B"), {"configurable": {"thread_id": "B"}})
    await graph.ainvoke(Command(resume="tematy A"), {"configurable": {"thread_id": "A"}})

    state_b = await graph.aget_state({"configurable": {"thread_id": "B"}})
    # B wciąż czeka na pierwsze pytanie (tematy), nie zmieszał się z A
    assert state_b.values["topics"] == []
