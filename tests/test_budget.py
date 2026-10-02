"""Hard API budget by reservation (wave 3 rev 2.1 R2-3) and wave 3 pricing.

Budget and pricing are coordinator-authored contract code; these tests pin them.
The two input counts 80,596 and 84,099 are the real 1A and 3A chain lengths from
the Astra wave-3 review (characters / 3), used here as count_tokens results.
"""

import itertools

import pytest

from og.budget import Budget, BudgetExhausted
from og.extract.types import Attempt
from og.pricing import PRICE_BASIS, PRICES_2026_10, max_input_rate, price

SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-4-5-20251001"
REAL_COUNTS = {80_596: 0.242450, 84_099: 0.2512075}


def attempt(model=SONNET, inp=0, out=0, cr=0, cw=0):
    return Attempt(model, inp, out, cr, cw, False)


def test_price_table_and_basis():
    assert PRICE_BASIS == "PRICES_2026_10"
    assert PRICES_2026_10[SONNET] == {
        "input": 2.00,
        "output": 10.00,
        "cache_read": 0.20,
        "cache_write": 2.50,
    }
    assert PRICES_2026_10[HAIKU] == {
        "input": 1.00,
        "output": 5.00,
        "cache_read": 0.10,
        "cache_write": 1.25,
    }


def test_price_sums_attempts():
    cost, basis = price(
        [attempt(inp=1000, out=100, cr=2000, cw=3000), attempt(HAIKU, inp=500, out=10)]
    )
    expected = (1000 * 2 + 100 * 10 + 2000 * 0.2 + 3000 * 2.5 + 500 * 1 + 10 * 5) / 1e6
    assert cost == pytest.approx(expected)
    assert basis == PRICE_BASIS


def test_price_unknown_model():
    assert price([attempt(), attempt("claude-unknown-9", inp=1)]) == (None, "unknown_model")


def test_max_input_rate():
    assert max_input_rate(SONNET) == 2.50
    assert max_input_rate(HAIKU) == 1.25
    assert max_input_rate("claude-unknown-9") is None


@pytest.mark.parametrize(("tokens", "expected"), sorted(REAL_COUNTS.items()))
def test_reservation_uses_cache_write_price_on_real_chain_lengths(tokens, expected):
    budget = Budget(limit_usd=None)
    r = budget.reserve(SONNET, tokens, 4096)
    assert r.amount_usd == pytest.approx(expected, abs=1e-12)
    assert budget.reserved_usd == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize(("tokens", "expected"), sorted(REAL_COUNTS.items()))
def test_admission_at_exactly_the_remaining_amount(tokens, expected):
    budget = Budget(limit_usd=expected)
    budget.reserve(SONNET, tokens, 4096)
    assert budget.exhausted is None


@pytest.mark.parametrize(("tokens", "expected"), sorted(REAL_COUNTS.items()))
def test_refusal_one_microdollar_short_is_sticky(tokens, expected):
    budget = Budget(limit_usd=expected - 0.000001)
    with pytest.raises(BudgetExhausted) as exc:
        budget.reserve(SONNET, tokens, 4096)
    assert exc.value.args[0] == "budget_exhausted"
    assert budget.exhausted == "budget_exhausted"
    assert budget.reserved_usd == 0
    with pytest.raises(BudgetExhausted):
        budget.reserve(HAIKU, 1, 1)


def test_unknown_model_is_sticky():
    budget = Budget(limit_usd=10.0)
    with pytest.raises(BudgetExhausted) as exc:
        budget.reserve("claude-unknown-9", 10, 10)
    assert exc.value.args[0] == "unknown_model"
    with pytest.raises(BudgetExhausted):
        budget.reserve(SONNET, 1, 1)


def test_settle_charges_actuals_and_releases_reservation():
    budget = Budget(limit_usd=1.0)
    r = budget.reserve(SONNET, 80_596, 4096)
    cost = budget.settle(r, [attempt(inp=1000, out=100)])
    assert cost == pytest.approx(0.003)
    assert budget.spent_usd == pytest.approx(0.003)
    assert budget.reserved_usd == pytest.approx(0.0, abs=1e-12)
    assert budget.remaining() == pytest.approx(0.997)
    with pytest.raises(ValueError):
        budget.settle(r, [])


def test_settle_with_unpriced_usage_charges_reservation_and_stops():
    budget = Budget(limit_usd=1.0)
    r = budget.reserve(SONNET, 1000, 100)
    assert budget.settle(r, [attempt("claude-unknown-9", inp=5)]) is None
    assert budget.spent_usd == pytest.approx(r.amount_usd)
    assert budget.exhausted == "unknown_model"
    with pytest.raises(BudgetExhausted):
        budget.reserve(SONNET, 1, 1)


def test_settle_unknown_charges_full_reservation():
    budget = Budget(limit_usd=1.0)
    r = budget.reserve(HAIKU, 1000, 64)
    budget.settle_unknown(r)
    assert budget.spent_usd == pytest.approx((1000 * 1.25 + 64 * 5) / 1e6)
    assert budget.reserved_usd == pytest.approx(0.0, abs=1e-12)
    with pytest.raises(ValueError):
        budget.settle_unknown(r)


def test_fail_is_sticky_and_keeps_first_code():
    budget = Budget(limit_usd=1.0)
    budget.fail("count_failed")
    budget.fail("other")
    assert budget.exhausted == "count_failed"
    with pytest.raises(BudgetExhausted) as exc:
        budget.reserve(SONNET, 1, 1)
    assert exc.value.args[0] == "count_failed"


def test_sequential_reservations_release_unused_funds():
    budget = Budget(limit_usd=0.45)
    for _ in range(5):
        r = budget.reserve(SONNET, 80_596, 4096)
        budget.settle(r, [attempt(cr=80_000, cw=596, out=2000)])
    assert budget.exhausted is None
    assert budget.spent_usd < 0.45


def _distributions(n):
    half = n // 2
    return {
        "input": dict(inp=n),
        "cache_write": dict(cw=n),
        "cache_read": dict(cr=n),
        "mixed": dict(inp=n - half - 10, cw=half, cr=10),
    }


CASES = [
    (tokens, dist, out)
    for tokens, dist, out in itertools.product(
        sorted(REAL_COUNTS), ["input", "cache_write", "cache_read", "mixed"], [0, 2000, 4096]
    )
]


@pytest.mark.parametrize(("tokens", "dist", "out"), CASES)
def test_actual_cost_never_exceeds_reservation(tokens, dist, out):
    assert len(CASES) == 24
    budget = Budget(limit_usd=None)
    r = budget.reserve(SONNET, tokens, 4096)
    cost, _ = price([attempt(out=out, **_distributions(tokens)[dist])])
    assert cost <= r.amount_usd + 1e-12
