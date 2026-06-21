"""Summarizer — TL;DR + główny wniosek per artykuł przez Claude API.

Model: Haiku 4.5 (tani, szybki — odpowiedni do streszczeń wsadowych).
Rate limiting: asyncio.Semaphore; SDK Anthropic dodatkowo auto-retry na 429.
Structured outputs: output_config.format gwarantuje poprawny JSON (wsparcie Haiku 4.5).
"""

import asyncio
import json

from anthropic import AsyncAnthropic

from adhd_briefing.config import settings

_SCHEMA = {
    "type": "object",
    "properties": {
        "tldr": {"type": "array", "items": {"type": "string"}},
        "main_outcome": {"type": "string"},
    },
    "required": ["tldr", "main_outcome"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You write ADHD-friendly summaries of articles. Respond in English.\n\n"
    "Rules:\n"
    "- main_outcome: ONE short sentence (aim ≤25 words) that LEADS with the single most "
    "important concrete fact (a number, name, or the specific claim). State the point itself, "
    "not that a point exists. Never open with vague hedges like 'significant', 'proven', "
    "'various', 'promising', 'interesting' — lead with the actual fact.\n"
    "- tldr: 2-4 bullets. Each bullet must add NEW information that is NOT already in the "
    "main_outcome — never restate it. Each bullet is exactly ONE idea (never combine two facts). "
    "Lead with concrete specifics (numbers, names, the actual claim). No filler or throat-clearing.\n"
    "- Faithfulness: only include facts present in the source. Never invent numbers, names, or claims."
)

_MAX_CONTENT_CHARS = 6000


class Summarizer:
    """Streszcza artykuły (dict z polami url/title/content) przez Claude API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        concurrency: int | None = None,
    ) -> None:
        self.client = AsyncAnthropic(
            api_key=api_key or settings.anthropic_api_key,
            max_retries=4,
        )
        self.model = model or settings.summarizer_model
        self._sem = asyncio.Semaphore(concurrency or settings.llm_concurrency)

    async def summarize(self, article: dict) -> dict:
        """Zwraca artykuł wzbogacony o tldr (list[str]) i main_outcome (str)."""
        async with self._sem:
            data = await self._call(article)
        return {**article, "tldr": data["tldr"], "main_outcome": data["main_outcome"]}

    async def _call(self, article: dict) -> dict:
        content = (article.get("content") or "")[:_MAX_CONTENT_CHARS]
        title = article.get("title") or ""
        user = f"Title: {title}\n\nContent:\n{content}"
        try:
            resp = await self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=_SYSTEM,
                messages=[{"role": "user", "content": user}],
                output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
            )
            text = next(b.text for b in resp.content if b.type == "text")
            parsed = json.loads(text)
            return {
                "tldr": parsed.get("tldr", []),
                "main_outcome": parsed.get("main_outcome", ""),
            }
        except Exception:
            # Izolacja awarii per wywołanie LLM — jedno źródło nie wywraca briefingu.
            snippet = (content[:200] + "…") if content else ""
            return {"tldr": [snippet] if snippet else [], "main_outcome": title}
