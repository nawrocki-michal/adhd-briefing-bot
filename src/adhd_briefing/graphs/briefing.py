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
from adhd_briefing.sources import fetch_articles, fetch_single  # patchowalne w testach


def estimate_read_time(content: str, wpm: int = 200) -> int:
    """Szacuje czas czytania w minutach (≈200 wpm). Min. 1 min; przybliżone dla feedów."""
    words = len((content or "").split())
    return max(1, round(words / wpm)) if words else 1


def format_briefing(articles: list[dict]) -> str:
    """Składa ADHD-friendly briefing z listy streszczonych artykułów."""
    if not articles:
        return "✅ Nothing new today — you're all caught up!"

    lines = ["📋 *Your briefing*", ""]
    for i, art in enumerate(articles, 1):
        read_min = estimate_read_time(art.get("content") or "")
        lines.append(f"{i}. *{art.get('title') or 'Untitled'}*  ·  ⏱ {read_min} min read")
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
        # Ładuje inbox jednorazowy z DB — jeśli wywołujący nie podał go jawnie.
        if state.get("pending_urls"):
            return {}
        return {"pending_urls": await db.get_pending(state["chat_id"])}

    def dispatch(state: BriefingState) -> list[Send]:
        chat_id = state["chat_id"]
        # Stałe źródła: model „śledzę" → fetch_articles (z discovery feedu).
        sends = [
            Send("fetch_worker", {"url": url, "chat_id": chat_id, "mode": "feed"})
            for url in state["sources"]
        ]
        # Inbox jednorazowy: model „streść mi to" → fetch_single (wprost, bez discovery).
        sends += [
            Send("fetch_worker", {"url": url, "chat_id": chat_id, "mode": "article"})
            for url in state.get("pending_urls", [])
        ]
        return sends

    async def fetch_worker(state: dict) -> dict:
        # Otrzymuje cząstkowy stan {"url","chat_id","mode"} z Send().
        if state.get("mode") == "article":
            articles = await fetch_single(state["url"])
            pinned = True  # wklejone świadomie — omija filtr unseen
        else:
            articles = await fetch_articles(state["url"])
            pinned = False
        return {"raw_articles": [_to_dict(a, pinned=pinned) for a in articles]}

    async def filter_node(state: BriefingState) -> dict:
        chat_id = state["chat_id"]
        # Deduplikacja w obrębie batcha (po URL); pinned ma pierwszeństwo przy kolizji.
        by_url: dict[str, dict] = {}
        for art in state["raw_articles"]:
            url = art["url"]
            if url not in by_url:
                by_url[url] = art
            elif art.get("pinned"):
                by_url[url] = {**by_url[url], "pinned": True}
        unique = list(by_url.values())
        # Dedup względem historii (seen_articles) — ale pinned (inbox) zawsze przechodzi.
        candidates = [a["url"] for a in unique if not a.get("pinned")]
        unseen_urls = await db.filter_unseen(chat_id, candidates)
        filtered = [a for a in unique if a.get("pinned") or a["url"] in unseen_urls]
        return {"filtered_articles": filtered}

    def route_after_filter(state: BriefingState) -> str:
        return "summarize" if state["filtered_articles"] else "format"

    async def summarize_node(state: BriefingState) -> dict:
        import asyncio

        selected = state["filtered_articles"][:limit]
        tone = state.get("tone") or "neutral"
        results = await asyncio.gather(*(summarizer.summarize(a, tone) for a in selected))
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


def _to_dict(article, *, pinned: bool = False) -> dict:
    """Article (dataclass) → dict do stanu grafu. pinned=True dla inboxa jednorazowego."""
    return {
        "url": article.url,
        "title": article.title,
        "content": article.content,
        "source_url": article.source_url,
        "pinned": pinned,
    }
