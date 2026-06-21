"""Stany grafów LangGraph."""

import operator
from typing import Annotated, TypedDict


class BriefingState(TypedDict):
    """Stan grafu briefingu.

    raw_articles MUSI mieć reducer operator.add — przy Send() fan-oucie każdy
    równoległy fetch_worker zapisuje do tego samego klucza; bez reducera
    LangGraph rzuci InvalidUpdateError (Bug #1 z architektury).
    """

    chat_id: str
    sources: list[str]
    pending_urls: list[str]  # inbox jednorazowy — pobierany wprost (bez discovery), pinned
    raw_articles: Annotated[list[dict], operator.add]
    filtered_articles: list[dict]
    summarized_articles: list[dict]
    briefing: str


class OnboardingState(TypedDict):
    """Stan grafu onboardingu (konwersacyjny, human-in-the-loop)."""

    chat_id: str
    topics: list[str]
    sources: list[str]
    briefing_time: str  # "07:30"
    timezone: str  # "Europe/Warsaw" — wymagane dla schedulera (M5)
    setup_complete: bool
