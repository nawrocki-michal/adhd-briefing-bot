"""Cennik Claude API i wyliczanie kosztu briefingu (obserwowalność pay-as-you-go).

Ceny w USD za 1M tokenów. Dopasowanie po prefiksie ID modelu (bez sufiksu daty),
więc np. ``claude-haiku-4-5-20251001`` trafia w wpis ``claude-haiku-4-5``.
Źródło: cennik Anthropic (Haiku 4.5: $1 input / $5 output).
"""

# (input_per_mtok, output_per_mtok) w USD
_PRICING: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-8": (5.0, 25.0),
}

# Fallback, gdy model nieznany — używamy najdroższego znanego tieru, żeby raczej
# przeszacować niż niedoszacować koszt (bezpieczniej dla budżetu).
_FALLBACK = (5.0, 25.0)


def _rates(model: str) -> tuple[float, float]:
    for prefix, rates in _PRICING.items():
        if model.startswith(prefix):
            return rates
    return _FALLBACK


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Zwraca szacowany koszt w USD dla podanej liczby tokenów wejścia/wyjścia."""
    in_rate, out_rate = _rates(model)
    return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000
