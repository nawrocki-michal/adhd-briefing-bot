"""Deterministic auto-checks for a summary (no LLM) — length/format bounds."""

import re


def auto_checks(main_outcome: str, tldr: list[str]) -> dict:
    n = len(tldr)
    return {
        "n_bullets": n,
        "bullet_count_ok": 2 <= n <= 4,
        "bullets_short_ok": all(len(b.split()) <= 40 for b in tldr) if tldr else False,
        # liczymy tylko końce zdań (interpunkcja + spacja/koniec), pomijając kropki
        # dziesiętne typu "1.1" czy "$4,000.50" (kropka przed cyfrą/nie-spacją)
        "main_outcome_one_sentence": len(re.findall(r"[.!?]+(?=\s|$)", main_outcome.strip())) <= 1,
        "format_valid": isinstance(tldr, list) and isinstance(main_outcome, str) and bool(main_outcome.strip()),
    }


def auto_ok(checks: dict) -> bool:
    return all(
        checks[k]
        for k in ("bullet_count_ok", "bullets_short_ok", "main_outcome_one_sentence", "format_valid")
    )
