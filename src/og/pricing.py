"""Model prices for cost accounting (coordinator-authored, frozen).

USD per million tokens. Extraction keeps its own copy in og.extract.__main__;
wave 3 (change checks and gates) prices through this module.
"""

from __future__ import annotations

from collections.abc import Iterable

from og.extract.types import Attempt

PRICE_BASIS = "PRICES_2026_10"
PRICES_2026_10: dict[str, dict[str, float]] = {
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    "claude-haiku-4-5-20251001": {
        "input": 1.00,
        "output": 5.00,
        "cache_read": 0.10,
        "cache_write": 1.25,
    },
}


def price(attempts: Iterable[Attempt]) -> tuple[float | None, str]:
    """Priced usage of the attempts; (None, "unknown_model") if any model is unpriced."""
    total = 0.0
    for a in attempts:
        p = PRICES_2026_10.get(a.model)
        if p is None:
            return None, "unknown_model"
        total += (a.input_tokens or 0) * p["input"]
        total += (a.output_tokens or 0) * p["output"]
        total += (a.cache_read_tokens or 0) * p["cache_read"]
        total += (a.cache_write_tokens or 0) * p["cache_write"]
    return total / 1_000_000, PRICE_BASIS


def max_input_rate(model: str) -> float | None:
    """The highest per-token input tariff (USD/Mtok) for the model, or None if unpriced."""
    p = PRICES_2026_10.get(model)
    if p is None:
        return None
    return max(p["input"], p["cache_read"], p["cache_write"])
