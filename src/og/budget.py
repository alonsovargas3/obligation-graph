"""Hard API budget by reservation (wave 3 rev 2.1 R2-3; coordinator-authored, frozen).

Before every model call the caller counts the complete effective request with
the free count_tokens endpoint (output_config included; C0 verified the count
then equals billed input) and reserves the worst case: every input token at the
model's highest input tariff plus max_tokens at the output tariff. Change checks
and gates send no server-side fallback, so one call bills at most one attempt.
After the call, settle() replaces the reservation with the priced actual usage.
Any refusal to admit, or any unknown price, makes the budget sticky-exhausted.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from og.extract.types import Attempt
from og.pricing import PRICES_2026_10, max_input_rate, price


class BudgetExhausted(Exception):
    """No further model calls in this invocation; args[0] is a short code."""


@dataclass
class Reservation:
    model: str
    amount_usd: float
    settled: bool = False


@dataclass
class Budget:
    limit_usd: float | None  # None: unlimited (still records spend)
    spent_usd: float = 0.0
    reserved_usd: float = 0.0
    exhausted: str | None = None  # sticky short code once set
    calls: int = 0
    _open: list[Reservation] = field(default_factory=list)

    def remaining(self) -> float | None:
        if self.limit_usd is None:
            return None
        return self.limit_usd - self.spent_usd - self.reserved_usd

    def reserve(self, model: str, input_tokens: int, max_tokens: int) -> Reservation:
        if self.exhausted is not None:
            raise BudgetExhausted(self.exhausted)
        rate_in = max_input_rate(model)
        if rate_in is None:
            self.exhausted = "unknown_model"
            raise BudgetExhausted(self.exhausted)
        amount = (input_tokens * rate_in + max_tokens * PRICES_2026_10[model]["output"]) / 1e6
        rem = self.remaining()
        if rem is not None and amount > rem + 1e-12:
            self.exhausted = "budget_exhausted"
            raise BudgetExhausted(self.exhausted)
        r = Reservation(model, amount)
        self.reserved_usd += amount
        self._open.append(r)
        self.calls += 1
        return r

    def settle(self, reservation: Reservation, attempts: Iterable[Attempt]) -> float | None:
        """Release the reservation and charge the actual priced usage (returned)."""
        if reservation.settled:
            raise ValueError("reservation already settled")
        reservation.settled = True
        self.reserved_usd -= reservation.amount_usd
        self._open.remove(reservation)
        cost, _basis = price(list(attempts))
        if cost is None:
            # Unpriced usage: charge the full reservation and stop further calls.
            self.spent_usd += reservation.amount_usd
            self.exhausted = "unknown_model"
            return None
        self.spent_usd += cost
        return cost

    def settle_unknown(self, reservation: Reservation) -> None:
        """The call raised with no usage available: charge the whole reservation."""
        if reservation.settled:
            raise ValueError("reservation already settled")
        reservation.settled = True
        self.reserved_usd -= reservation.amount_usd
        self._open.remove(reservation)
        self.spent_usd += reservation.amount_usd

    def fail(self, code: str) -> None:
        """Make the budget sticky-exhausted (e.g. count_tokens failed)."""
        if self.exhausted is None:
            self.exhausted = code
