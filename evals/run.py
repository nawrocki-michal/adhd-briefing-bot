"""Eval runner.

    PYTHONPATH=src python -m evals.run validate     # czy eval odróżnia dobre od złych
    PYTHONPATH=src python -m evals.run summarizer    # ocena realnego outputu summarizera

`validate` sprawdza sam eval: dla każdego złego wariantu dobry wariant musi wygrać na
wymiarze, który zły łamie. `summarizer` puszcza prawdziwy Summarizer na źródłach golden
setu i ocenia output (metryka regresji do iteracji promptu).
"""

import argparse
import asyncio
import sys

from anthropic import AsyncAnthropic

from adhd_briefing.config import settings
from adhd_briefing.llm import Summarizer
from evals.checks import auto_checks, auto_ok
from evals.golden_set import GOLDEN_SET
from evals.judge import DIMENSIONS, judge_summary, overall_score

_SEM = asyncio.Semaphore(4)


async def _judge(client, source, main_outcome, tldr):
    async with _SEM:
        return await judge_summary(source, main_outcome, tldr, client=client)


def _fmt_row(label, scores, checks) -> str:
    faith = "✓" if scores["faithfulness"] else "✗FAIL"
    dims = " ".join(f"{d[:4]}:{scores[d]}" for d in DIMENSIONS)
    auto = "auto✓" if auto_ok(checks) else "auto✗"
    return f"  {label:<14} faith:{faith:<6} {dims}  {auto}  = {overall_score(scores):>3}"


async def validate(client) -> int:
    print("=" * 100)
    print("VALIDATE — czy eval odróżnia dobre warianty od złych?")
    print("=" * 100)

    failures = 0
    checks_total = 0
    for case in GOLDEN_SET:
        print(f"\n## case: {case.name}")
        scored: dict[str, dict] = {}
        for vname, summ in case.variants.items():
            s = await _judge(client, case.source, summ.main_outcome, summ.tldr)
            scored[vname] = s
            print(_fmt_row(vname, s, auto_checks(summ.main_outcome, summ.tldr)))

        good = scored["good"]
        for vname, target in case.targets.items():
            bad = scored[vname]
            checks_total += 1
            if target == "faithfulness":
                ok = good["faithfulness"] and not bad["faithfulness"]
            else:
                ok = good[target] > bad[target]
            if not ok:
                failures += 1
                detail = (
                    f"faith good={good['faithfulness']} bad={bad['faithfulness']}"
                    if target == "faithfulness"
                    else f"{target}: good={good[target]} bad={bad[target]}"
                )
                print(f"  ❌ DISCRIMINATION FAIL [{vname} → {target}] {detail}")

    print("\n" + "=" * 100)
    passed = checks_total - failures
    print(f"DISCRIMINATION: {passed}/{checks_total} OK")
    print("WERDYKT:", "EVAL VALID ✅" if failures == 0 else f"EVAL SŁABY ❌ ({failures} fail)")
    print("=" * 100)
    return 0 if failures == 0 else 1


async def summarizer(client) -> int:
    print("=" * 100)
    print("SUMMARIZER — ocena realnego outputu Haiku na źródłach golden setu")
    print("=" * 100)

    summ = Summarizer()
    total = 0
    for case in GOLDEN_SET:
        article = {"title": case.name, "content": case.source, "url": f"https://eval/{case.name}"}
        out = await summ.summarize(article)
        mo, tldr = out["main_outcome"], out["tldr"]
        scores = await _judge(client, case.source, mo, tldr)
        checks = auto_checks(mo, tldr)
        print(f"\n## case: {case.name}")
        print(f"  main_outcome: {mo}")
        for b in tldr:
            print(f"    • {b}")
        print(_fmt_row("haiku", scores, checks))
        print(f"  rationale: {scores['rationale']}")
        total += overall_score(scores)

    avg = round(total / len(GOLDEN_SET))
    print("\n" + "=" * 100)
    print(f"ŚREDNI WYNIK SUMMARIZERA: {avg}/100  (metryka do iteracji promptu)")
    print("=" * 100)
    return 0


async def _main(mode: str) -> int:
    client = AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=4)
    if mode == "validate":
        return await validate(client)
    if mode == "summarizer":
        return await summarizer(client)
    print(f"Nieznany tryb: {mode}")
    return 2


def main() -> None:
    parser = argparse.ArgumentParser(description="ADHD summary eval runner")
    parser.add_argument("mode", choices=["validate", "summarizer"])
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.mode)))


if __name__ == "__main__":
    main()
