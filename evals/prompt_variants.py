"""A/B test of summarizer system-prompt variants against the eval.

Applies the `finalize-agent-prompt` methodology: refine structure, wording, and
organization toward proven patterns. Three distinct approaches are compared with the
current baseline, scored by the LLM judge over the golden set (averaged over repeats
to dampen sampling noise).

    PYTHONPATH=src python -m evals.prompt_variants
"""

import asyncio

from anthropic import AsyncAnthropic

from adhd_briefing.config import settings
from adhd_briefing.llm import Summarizer
from adhd_briefing.llm.summarizer import _SYSTEM as BASELINE
from evals.golden_set import GOLDEN_SET
from evals.judge import judge_summary, overall_score

REPEATS = 2  # uśrednienie per (wariant, case) — Haiku nie jest w pełni deterministyczny
_SEM = asyncio.Semaphore(5)


# --- Wariant A: jasna rola + ponumerowane reguły + self-check (struktura/organizacja) ---
VARIANT_A = (
    "You are an expert editor writing ADHD-friendly news briefings. Respond in English.\n\n"
    "Produce a one-sentence `main_outcome` and 2-4 `tldr` bullets.\n\n"
    "Rules:\n"
    "1. main_outcome: open with the single most important concrete fact (a number, name, or "
    "specific claim) in ≤25 words. State the fact itself — never open with a hedge "
    "('significant', 'proven', 'various', 'promising', 'interesting').\n"
    "2. tldr: each bullet adds NEW information not in main_outcome — never restate it. One idea "
    "per bullet. Lead with concrete specifics (numbers, names, the actual claim).\n"
    "3. No filler, hedging, or throat-clearing. Every word earns its place.\n"
    "4. Faithfulness: include only facts present in the source. Never invent numbers, names, "
    "or claims.\n\n"
    "Before finishing, self-check: does main_outcome lead with a concrete fact? Does each bullet "
    "add something new? Drop any bullet that merely repeats the main_outcome."
)


# --- Wariant B: few-shot (jeden wzorcowy przykład — silna dźwignia dla małych modeli) ---
VARIANT_B = (
    "You are an expert editor writing ADHD-friendly summaries. Respond in English.\n\n"
    "Produce a one-sentence `main_outcome` and 2-4 `tldr` bullets.\n"
    "- main_outcome: lead with the single most important concrete fact (number/name/specific "
    "claim), ≤25 words, no hedges.\n"
    "- tldr: each bullet adds NEW info beyond main_outcome (never restate it), one idea each, "
    "concrete specifics first.\n"
    "- Only facts from the source; never invent.\n\n"
    "Example of the desired style:\n"
    'SOURCE (excerpt): "Acme\'s solar tile launches in June at $40/sq ft, 30% cheaper than '
    'rivals; a pilot cut install time 25% thanks to a single-layer design that skips mounting '
    'rails."\n'
    'main_outcome: "Acme\'s solar tile launches in June at $40/sq ft — 30% below rivals."\n'
    "tldr:\n"
    '- "Pilot install cut roof time 25% versus standard panels."\n'
    '- "The saving comes from a single-layer design that skips mounting rails."\n'
    "Note how main_outcome leads with the price fact and each bullet adds a different, "
    "non-overlapping detail."
)


# --- Wariant C: kontrastywny (✗ źle → ✓ dobrze), celuje w wykryte tryby porażki ---
VARIANT_C = (
    "You are an expert editor writing ADHD-friendly summaries. Respond in English.\n"
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


VARIANTS = {
    "baseline": BASELINE,
    "A_structured": VARIANT_A,
    "B_fewshot": VARIANT_B,
    "C_contrastive": VARIANT_C,
}


async def _score_once(summ: Summarizer, case, client) -> int:
    async with _SEM:
        article = {"title": case.name, "content": case.source, "url": f"https://eval/{case.name}"}
        out = await summ.summarize(article)
        scores = await judge_summary(case.source, out["main_outcome"], out["tldr"], client=client)
    return overall_score(scores)


async def score_variant(name: str, prompt: str, client) -> tuple[float, dict]:
    summ = Summarizer(system_prompt=prompt)
    per_case: dict[str, float] = {}
    for case in GOLDEN_SET:
        runs = await asyncio.gather(*(_score_once(summ, case, client) for _ in range(REPEATS)))
        per_case[case.name] = sum(runs) / len(runs)
    avg = sum(per_case.values()) / len(per_case)
    return avg, per_case


async def main() -> None:
    client = AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=4)
    print("=" * 90)
    print(f"PROMPT A/B — {len(VARIANTS)} wariantów × {len(GOLDEN_SET)} cases × {REPEATS} runs")
    print("=" * 90)

    results: dict[str, float] = {}
    for name, prompt in VARIANTS.items():
        avg, per_case = await score_variant(name, prompt, client)
        results[name] = avg
        cases = "  ".join(f"{c}:{v:.0f}" for c, v in per_case.items())
        print(f"  {name:<15} avg {avg:5.1f}   ({cases})")

    print("\n" + "=" * 90)
    ranked = sorted(results.items(), key=lambda kv: kv[1], reverse=True)
    for i, (name, avg) in enumerate(ranked, 1):
        mark = "👑" if i == 1 else "  "
        print(f"  {mark} {i}. {name:<15} {avg:.1f}")
    print(f"\nWINNER: {ranked[0][0]} ({ranked[0][1]:.1f})")
    print("=" * 90)


if __name__ == "__main__":
    asyncio.run(main())
