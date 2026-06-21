"""Deterministic auto-checks for a summary (no LLM) — length/format bounds."""

import re


def auto_checks(main_outcome: str, tldr: list[str]) -> dict:
    n = len(tldr)
    return {
        "n_bullets": n,
        "bullet_count_ok": 2 <= n <= 4,
        "bullets_short_ok": all(len(b.split()) <= 40 for b in tldr) if tldr else False,
        "main_outcome_one_sentence": len(re.findall(r"[.!?]+", main_outcome)) <= 1,
        "format_valid": isinstance(tldr, list) and isinstance(main_outcome, str) and bool(main_outcome.strip()),
    }


def auto_ok(checks: dict) -> bool:
    return all(
        checks[k]
        for k in ("bullet_count_ok", "bullets_short_ok", "main_outcome_one_sentence", "format_valid")
    )
