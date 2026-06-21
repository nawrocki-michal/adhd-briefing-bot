"""BriefingGraph — async, Send() fan-out, fan-in z reducerem.

Przepływ (LangGraph 1.x — Send() zwracany z funkcji routującej conditional edge,
nie wymaga osobnego węzła dispatcher, inaczej niż zakładała architektura dla
starszych wersji):

    START → prepare → [dispatch fan-out] → fetch_worker × N
                                              → filter → (summarize | format) → END
"""

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from adhd_briefing.config import settings
from adhd_briefing.db import Database
from adhd_briefing.graphs.state import BriefingState
from adhd_briefing.llm import Summarizer
from adhd_briefing.sources import fetch_articles  # patchowalne w testach


def format_briefing(articles: list[dict]) -> str:
    """Składa ADHD-friendly briefing z listy streszczonych artykułów."""
    if not articles:
        return "✅ Nic nowego dzisiaj — wszystko na bieżąco!"

    lines = ["📋 *Twój briefing*", ""]
    for i, art in enumerate(articles, 1):
        lines.append(f"{i}. *{art.get('title') or 'Bez tytułu'}*")
        outcome = art.get("main_outcome")
        if outcome:
            lines.append(f"   → {outcome}")
        for bullet in art.get("tldr", []):
            lines.append(f"   • {bullet}")
        if art.get("url"):
            lines.append(f"   🔗 {art['url']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def build_briefing_graph(
    db: Database,
    summarizer: Summarizer,
    *,
    max_articles: int | None = None,
    checkpointer=None,
):
    """Buduje i kompiluje BriefingGraph z wstrzykniętymi zależnościami."""
    limit = max_articles or settings.briefing_max_articles

    async def prepare(state: BriefingState) -> dict:
        # Węzeł wejściowy przed conditional-edge fan-outem (Send wymaga źródła).
        return {}

    def dispatch(state: BriefingState) -> list[Send]:
        return [
            Send("fetch_worker", {"url": url, "chat_id": state["chat_id"]})
            for url in state["sources"]
        ]

    async def fetch_worker(state: dict) -> dict:
        # Otrzymuje cząstkowy stan {"url","chat_id"} z Send().
        articles = await fetch_articles(state["url"])
        return {"raw_articles": [_to_dict(a) for a in articles]}

    async def filter_node(state: BriefingState) -> dict:
        chat_id = state["chat_id"]
        # Deduplikacja w obrębie batcha (po URL).
        seen: set[str] = set()
        unique: list[dict] = []
        for art in state["raw_articles"]:
            if art["url"] in seen:
                continue
            seen.add(art["url"])
            unique.append(art)
        # Deduplikacja względem historii użytkownika (seen_articles w DB).
        unseen_urls = await db.filter_unseen(chat_id, [a["url"] for a in unique])
        filtered = [a for a in unique if a["url"] in unseen_urls]
        return {"filtered_articles": filtered}

    def route_after_filter(state: BriefingState) -> str:
        return "summarize" if state["filtered_articles"] else "format"

    async def summarize_node(state: BriefingState) -> dict:
        import asyncio

        selected = state["filtered_articles"][:limit]
        results = await asyncio.gather(*(summarizer.summarize(a) for a in selected))
        return {"summarized_articles": list(results)}

    async def format_node(state: BriefingState) -> dict:
        articles = state.get("summarized_articles", [])
        return {"briefing": format_briefing(articles)}

    builder = StateGraph(BriefingState)
    builder.add_node("prepare", prepare)
    builder.add_node("fetch_worker", fetch_worker)
    builder.add_node("filter", filter_node)
    builder.add_node("summarize", summarize_node)
    builder.add_node("format", format_node)

    builder.add_edge(START, "prepare")
    builder.add_conditional_edges("prepare", dispatch, ["fetch_worker"])
    builder.add_edge("fetch_worker", "filter")
    builder.add_conditional_edges("filter", route_after_filter, ["summarize", "format"])
    builder.add_edge("summarize", "format")
    builder.add_edge("format", END)

    return builder.compile(checkpointer=checkpointer)


def _to_dict(article) -> dict:
    """Article (dataclass) → dict do stanu grafu."""
    return {
        "url": article.url,
        "title": article.title,
        "content": article.content,
        "source_url": article.source_url,
    }
