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

# Contrastive prompt — winner of the A/B test (evals/prompt_variants.py): 96.5 vs
# baseline 94.8. Teaches by ✗/✓ contrast, targeting the failure modes the eval flagged
# (vague main_outcome, redundant bullets). Re-run that A/B before changing this.
_SYSTEM = (
    "You are an expert editor writing ADHD-friendly summaries of articles. Respond in English.\n"
    "Output a one-sentence `main_outcome` and 2-4 `tldr` bullets. Each rule shows the wrong vs "
    "right way:\n\n"
    "1. Lead with the fact (BLUF).\n"
    "   ✗ 'The company shared significant news about its product.'\n"
    "   ✓ 'Orbita's battery ships in Q3 at $90/kWh — 20% below the market.'\n"
    "2. Bullets add NEW info, never repeat main_outcome.\n"
    "   ✗ a bullet restating the price already in main_outcome.\n"
    "   ✓ a bullet with a different fact (a test result, the cost driver).\n"
    "3. Be specific, not vague.\n"
    "   ✗ 'showed promising results'\n"
    "   ✓ 'cut charging time 40% in a 12-week trial'\n"
    "4. Faithful only — never invent numbers, names, or claims not in the source.\n\n"
    "main_outcome ≤25 words, one sentence. Each bullet = one idea."
)

_MAX_CONTENT_CHARS = 6000


class Summarizer:
    """Streszcza artykuły (dict z polami url/title/content) przez Claude API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        concurrency: int | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self.client = AsyncAnthropic(
            api_key=api_key or settings.anthropic_api_key,
            max_retries=4,
        )
        self.model = model or settings.summarizer_model
        self.system_prompt = system_prompt or _SYSTEM
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
                system=self.system_prompt,
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
