"""LLM-as-judge — scores a summary against the ADHD-friendly rubric.

Judge model: Claude Sonnet 4.6 (more capable than the Haiku summarizer it grades).
Structured outputs guarantee parseable per-dimension scores.
"""

import json

from anthropic import AsyncAnthropic

from adhd_briefing.config import settings

JUDGE_MODEL = "claude-sonnet-4-6"

# Quality dimensions scored 1-5 (faithfulness is a separate pass/fail gate).
DIMENSIONS = ["bluf", "specificity", "conciseness", "actionability", "clarity", "atomic_bullets"]

# Weights from docs/adhd-content-guidelines.md (BLUF + specificity highest).
WEIGHTS = {
    "bluf": 3,
    "specificity": 3,
    "conciseness": 2,
    "actionability": 2,
    "clarity": 2,
    "atomic_bullets": 1,
}

_SCHEMA = {
    "type": "object",
    "properties": {
        "faithfulness": {"type": "boolean"},
        "bluf": {"type": "integer"},
        "specificity": {"type": "integer"},
        "conciseness": {"type": "integer"},
        "actionability": {"type": "integer"},
        "clarity": {"type": "integer"},
        "atomic_bullets": {"type": "integer"},
        "rationale": {"type": "string"},
    },
    "required": [
        "faithfulness",
        "bluf",
        "specificity",
        "conciseness",
        "actionability",
        "clarity",
        "atomic_bullets",
        "rationale",
    ],
    "additionalProperties": False,
}

_SYSTEM = """You are a strict evaluator of ADHD-friendly article summaries. \
You receive the SOURCE article and a SUMMARY (a one-sentence main_outcome plus 2-4 bullets). \
Judge ONLY against the source — do not use outside knowledge.

Return:
- faithfulness (boolean): true ONLY if every claim in the summary is supported by the source. \
Any invented fact, number, name, or relationship => false. This is a hard gate.
- Six dimensions scored 1-5 (5 = excellent, 1 = poor):
  - bluf: does main_outcome state the single most important point up front and stand alone?
  - specificity: concrete facts (numbers, names, the actual claim) vs vague generalities?
  - conciseness: no filler, hedging, or throat-clearing; every word earns its place?
  - actionability: can the reader tell why it matters / what to do with it?
  - clarity: plain, unambiguous language; no unexplained jargon?
  - atomic_bullets: each bullet one idea, parallel, easy to scan?
- rationale: one or two sentences explaining the scores, citing the biggest issue.

Be discriminating: reserve 5 for genuinely excellent, use 1-2 for clear violations."""


async def judge_summary(
    source: str,
    main_outcome: str,
    tldr: list[str],
    *,
    client: AsyncAnthropic | None = None,
    model: str = JUDGE_MODEL,
) -> dict:
    client = client or AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=4)
    bullets = "\n".join(f"- {b}" for b in tldr)
    user = (
        f"SOURCE ARTICLE:\n{source}\n\n"
        f"SUMMARY TO EVALUATE:\nmain_outcome: {main_outcome}\nbullets:\n{bullets}"
    )
    resp = await client.messages.create(
        model=model,
        max_tokens=1024,
        system=_SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": _SCHEMA}},
    )
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def overall_score(scores: dict) -> int:
    """Gated weighted score 0-100. Faithfulness failure → 0."""
    if not scores.get("faithfulness"):
        return 0
    num = sum(scores[d] * w for d, w in WEIGHTS.items())
    den = sum(WEIGHTS.values()) * 5
    return round(num / den * 100)
