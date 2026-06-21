"""OnboardingGraph — konwersacyjny setup z interrupt() (human-in-the-loop).

Przepływ: TopicsNode → SourcesNode → ScheduleNode → ConfirmNode
Każdy węzeł pauzuje przez interrupt() i czeka na input użytkownika (Command(resume=...)).
Stan przeżywa restart bota dzięki AsyncSqliteSaver (Bug #3); thread_id per chat_id (Bug #2).
"""

import re

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from adhd_briefing.config import settings
from adhd_briefing.db import Database
from adhd_briefing.graphs.state import OnboardingState

_TOPICS_Q = "Hi! 👋 What topics are you interested in? (e.g. AI, product management, startups)"
_SOURCES_Q = (
    "Great. Now paste the sources you follow — links to sites or RSS feeds,\n"
    "separated by commas or new lines."
)
_SCHEDULE_Q = "What time should I send your briefing? (e.g. 07:30, default 08:00)"


def parse_topics(text: str) -> list[str]:
    return [t.strip() for t in re.split(r"[,\n]", text) if t.strip()]


def parse_sources(text: str) -> list[str]:
    """Wyciąga URL-e z tekstu (linie/przecinki/spacje); zostawia tylko http(s)."""
    tokens = re.split(r"[\s,]+", text.strip())
    return [t for t in tokens if t.startswith("http://") or t.startswith("https://")]


def normalize_time(text: str, default: str = "08:00") -> str:
    """Normalizuje '7', '7:30', '07:30' → 'HH:MM'. Fallback do default."""
    match = re.search(r"(\d{1,2})(?:[:.](\d{2}))?", text)
    if not match:
        return default
    hour = int(match.group(1))
    minute = int(match.group(2)) if match.group(2) else 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return default
    return f"{hour:02d}:{minute:02d}"


def build_onboarding_graph(db: Database, *, checkpointer=None):
    """Buduje OnboardingGraph z wstrzykniętą bazą i checkpointerem."""

    def topics_node(state: OnboardingState) -> dict:
        answer = interrupt(_TOPICS_Q)
        return {"topics": parse_topics(answer)}

    def sources_node(state: OnboardingState) -> dict:
        while True:
            answer = interrupt(_SOURCES_Q)
            sources = parse_sources(answer)
            if sources:
                return {"sources": sources}
            # Brak poprawnych URL-i — pytaj ponownie.

    def schedule_node(state: OnboardingState) -> dict:
        answer = interrupt(_SCHEDULE_Q)
        return {
            "briefing_time": normalize_time(answer),
            "timezone": settings.default_timezone,
        }

    async def confirm_node(state: OnboardingState) -> dict:
        await db.upsert_user(
            chat_id=state["chat_id"],
            topics=state["topics"],
            sources=state["sources"],
            briefing_time=state["briefing_time"],
            timezone=state["timezone"],
        )
        return {"setup_complete": True}

    builder = StateGraph(OnboardingState)
    builder.add_node("topics", topics_node)
    builder.add_node("sources", sources_node)
    builder.add_node("schedule", schedule_node)
    builder.add_node("confirm", confirm_node)

    builder.add_edge(START, "topics")
    builder.add_edge("topics", "sources")
    builder.add_edge("sources", "schedule")
    builder.add_edge("schedule", "confirm")
    builder.add_edge("confirm", END)

    return builder.compile(checkpointer=checkpointer)
