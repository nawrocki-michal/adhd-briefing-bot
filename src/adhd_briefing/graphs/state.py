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
    raw_articles: Annotated[list[dict], operator.add]
    filtered_articles: list[dict]
    summarized_articles: list[dict]
    briefing: str
