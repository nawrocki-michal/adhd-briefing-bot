"""Testy BriefingGraph — fan-out reducer, dedup, izolacja awarii, formatowanie.

Bez sieci i bez LLM: fetch_articles zmockowany, Summarizer podmieniony na fake.
"""

import pytest

from adhd_briefing.db import Database
from adhd_briefing.graphs.briefing import (
    build_briefing_graph,
    estimate_read_time,
    format_briefing,
)
from adhd_briefing.models import Article


class FakeSummarizer:
    """Deterministyczny summarizer — bez wywołań Claude API. Zapamiętuje użyty ton."""

    def __init__(self) -> None:
        self.tones: list[str] = []

    async def summarize(self, article: dict, tone: str = "neutral") -> dict:
        self.tones.append(tone)
        return {
            **article,
            "tldr": [f"bullet dla {article['title']}"],
            "main_outcome": f"wniosek: {article['title']}",
            "_usage": {"model": "claude-haiku-4-5", "input_tokens": 100, "output_tokens": 20},
        }


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "graph.db"))
    await database.init()
    return database


def _make_fetch(mapping: dict[str, list[Article]]):
    async def _fetch(url: str) -> list[Article]:
        return mapping.get(url, [])

    return _fetch


def _initial(chat_id: str, sources: list[str], tone: str = "neutral") -> dict:
    return {
        "chat_id": chat_id,
        "sources": sources,
        "tone": tone,
        "raw_articles": [],
        "filtered_articles": [],
        "summarized_articles": [],
        "briefing": "",
    }


# --- format_briefing ---


def test_format_empty():
    assert "Nothing new" in format_briefing([])


def test_format_includes_articles():
    out = format_briefing(
        [{"title": "Tytuł A", "main_outcome": "wniosek", "tldr": ["b1"], "url": "https://a"}]
    )
    assert "Tytuł A" in out
    assert "wniosek" in out
    assert "b1" in out
    assert "https://a" in out


def test_format_includes_read_time():
    content = " ".join(["word"] * 400)  # 400 słów ≈ 2 min @200 wpm
    out = format_briefing([{"title": "T", "tldr": [], "url": "https://a", "content": content}])
    assert "2 min read" in out


@pytest.mark.parametrize(
    "words,expected",
    [(0, 1), (50, 1), (200, 1), (300, 2), (1000, 5)],
)
def test_estimate_read_time(words, expected):
    assert estimate_read_time(" ".join(["w"] * words)) == expected


# --- fan-out + reducer (Bug #1) ---


async def test_fanout_aggregates_without_invalid_update(db, monkeypatch):
    """Dwa źródła → reducer operator.add scala raw_articles bez InvalidUpdateError."""
    mapping = {
        "https://s1": [Article("https://a1", "A1", "treść 1", "https://s1")],
        "https://s2": [Article("https://a2", "A2", "treść 2", "https://s2")],
    }
    monkeypatch.setattr("adhd_briefing.graphs.briefing.fetch_articles", _make_fetch(mapping))

    graph = build_briefing_graph(db, FakeSummarizer())
    state = await graph.ainvoke(_initial("u1", ["https://s1", "https://s2"]))

    titles = {a["title"] for a in state["summarized_articles"]}
    assert titles == {"A1", "A2"}
    assert "A1" in state["briefing"] and "A2" in state["briefing"]


# --- dedup względem historii ---


async def test_dedup_skips_seen(db, monkeypatch):
    await db.mark_seen("u1", "https://a1")  # a1 już widziane
    mapping = {
        "https://s1": [
            Article("https://a1", "A1", "t", "https://s1"),
            Article("https://a2", "A2", "t", "https://s1"),
        ],
    }
    monkeypatch.setattr("adhd_briefing.graphs.briefing.fetch_articles", _make_fetch(mapping))

    graph = build_briefing_graph(db, FakeSummarizer())
    state = await graph.ainvoke(_initial("u1", ["https://s1"]))

    titles = {a["title"] for a in state["summarized_articles"]}
    assert titles == {"A2"}  # A1 odfiltrowane


# --- dedup w obrębie batcha (ten sam URL z dwóch źródeł) ---


async def test_dedup_within_batch(db, monkeypatch):
    dup = Article("https://same", "Same", "t", "https://s")
    mapping = {"https://s1": [dup], "https://s2": [dup]}
    monkeypatch.setattr("adhd_briefing.graphs.briefing.fetch_articles", _make_fetch(mapping))

    graph = build_briefing_graph(db, FakeSummarizer())
    state = await graph.ainvoke(_initial("u1", ["https://s1", "https://s2"]))

    assert len(state["summarized_articles"]) == 1


# --- brak nowych → "nic nowego" (conditional edge omija summarize) ---


async def test_nothing_new(db, monkeypatch):
    monkeypatch.setattr("adhd_briefing.graphs.briefing.fetch_articles", _make_fetch({}))
    graph = build_briefing_graph(db, FakeSummarizer())
    state = await graph.ainvoke(_initial("u1", ["https://empty"]))
    assert "Nothing new" in state["briefing"]
    assert state["summarized_articles"] == []


# --- izolacja awarii: jedno źródło puste, drugie działa ---


async def test_one_source_fails_others_survive(db, monkeypatch):
    mapping = {
        "https://ok": [Article("https://a", "OK", "t", "https://ok")],
        "https://bad": [],  # symuluje awarię/timeout (provider zwrócił [])
    }
    monkeypatch.setattr("adhd_briefing.graphs.briefing.fetch_articles", _make_fetch(mapping))

    graph = build_briefing_graph(db, FakeSummarizer())
    state = await graph.ainvoke(_initial("u1", ["https://ok", "https://bad"]))

    titles = {a["title"] for a in state["summarized_articles"]}
    assert titles == {"OK"}


# --- limit max_articles ---


# --- inbox jednorazowy (pending_articles) ---


async def test_pending_article_delivered_via_fetch_single(db, monkeypatch):
    """Zakolejkowany URL → pobrany przez fetch_single (nie fetch_articles) i dostarczony."""
    await db.upsert_user("u1", [], [], "08:00", "Europe/Warsaw")
    await db.add_pending("u1", ["https://paste"])
    # fetch_articles puste (brak stałych źródeł); fetch_single zwraca wklejony artykuł.
    monkeypatch.setattr("adhd_briefing.graphs.briefing.fetch_articles", _make_fetch({}))
    monkeypatch.setattr(
        "adhd_briefing.graphs.briefing.fetch_single",
        _make_fetch({"https://paste": [Article("https://paste", "Pasted", "t", "https://paste")]}),
    )

    graph = build_briefing_graph(db, FakeSummarizer())
    state = await graph.ainvoke(_initial("u1", []))

    titles = {a["title"] for a in state["summarized_articles"]}
    assert titles == {"Pasted"}


async def test_pending_bypasses_seen_filter(db, monkeypatch):
    """Wklejony artykuł przechodzi nawet jeśli był już 'seen' (pinned bypass)."""
    await db.upsert_user("u1", [], [], "08:00", "Europe/Warsaw")
    await db.mark_seen("u1", "https://paste")  # niby już widziany
    await db.add_pending("u1", ["https://paste"])
    monkeypatch.setattr("adhd_briefing.graphs.briefing.fetch_articles", _make_fetch({}))
    monkeypatch.setattr(
        "adhd_briefing.graphs.briefing.fetch_single",
        _make_fetch({"https://paste": [Article("https://paste", "Pasted", "t", "https://paste")]}),
    )

    graph = build_briefing_graph(db, FakeSummarizer())
    state = await graph.ainvoke(_initial("u1", []))

    titles = {a["title"] for a in state["summarized_articles"]}
    assert titles == {"Pasted"}  # mimo seen — bo pinned


async def test_tone_forwarded_to_summarizer(db, monkeypatch):
    """Ton ze stanu briefingu trafia do summarizer.summarize()."""
    mapping = {"https://s": [Article("https://a", "A", "t", "https://s")]}
    monkeypatch.setattr("adhd_briefing.graphs.briefing.fetch_articles", _make_fetch(mapping))
    fake = FakeSummarizer()
    graph = build_briefing_graph(db, fake)
    await graph.ainvoke(_initial("u1", ["https://s"], tone="warm"))
    assert fake.tones == ["warm"]


# --- obserwowalność kosztów: agregacja usage ---


async def test_usage_aggregated_across_articles(db, monkeypatch):
    mapping = {
        "https://s1": [Article("https://a1", "A1", "t", "https://s1")],
        "https://s2": [Article("https://a2", "A2", "t", "https://s2")],
    }
    monkeypatch.setattr("adhd_briefing.graphs.briefing.fetch_articles", _make_fetch(mapping))

    graph = build_briefing_graph(db, FakeSummarizer())
    state = await graph.ainvoke(_initial("u1", ["https://s1", "https://s2"]))

    usage = state["usage"]
    assert usage["articles"] == 2
    assert usage["input_tokens"] == 200  # 2 × 100
    assert usage["output_tokens"] == 40  # 2 × 20
    assert usage["model"] == "claude-haiku-4-5"


async def test_nothing_new_has_no_usage(db, monkeypatch):
    monkeypatch.setattr("adhd_briefing.graphs.briefing.fetch_articles", _make_fetch({}))
    graph = build_briefing_graph(db, FakeSummarizer())
    state = await graph.ainvoke(_initial("u1", ["https://empty"]))
    # summarize pominięty (conditional edge) → usage nieustawione lub puste
    assert not state.get("usage")


async def test_respects_max_articles(db, monkeypatch):
    arts = [Article(f"https://a{i}", f"A{i}", "t", "https://s") for i in range(10)]
    monkeypatch.setattr(
        "adhd_briefing.graphs.briefing.fetch_articles", _make_fetch({"https://s": arts})
    )

    graph = build_briefing_graph(db, FakeSummarizer(), max_articles=3)
    state = await graph.ainvoke(_initial("u1", ["https://s"]))

    assert len(state["summarized_articles"]) == 3
