"""Testy wyliczania kosztu LLM (llm/pricing.py)."""

import pytest

from adhd_briefing.llm.pricing import estimate_cost


def test_haiku_cost():
    # $1/M input, $5/M output
    assert estimate_cost("claude-haiku-4-5", 1_000_000, 0) == pytest.approx(1.0)
    assert estimate_cost("claude-haiku-4-5", 0, 1_000_000) == pytest.approx(5.0)


def test_matches_by_prefix_ignoring_date_suffix():
    assert estimate_cost("claude-haiku-4-5-20251001", 1_000_000, 0) == pytest.approx(1.0)


def test_unknown_model_uses_safe_fallback():
    # Fallback = najdroższy tier (opus): $5/M input — raczej przeszacuj niż niedoszacuj.
    assert estimate_cost("some-future-model", 1_000_000, 0) == pytest.approx(5.0)


def test_zero_tokens_zero_cost():
    assert estimate_cost("claude-haiku-4-5", 0, 0) == 0.0
