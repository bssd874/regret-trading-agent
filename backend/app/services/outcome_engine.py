from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class OutcomeResult:
    entry_price: float
    evaluation_price: float
    quantity: float
    notional: float
    pnl_pct: float
    pnl_amount: float


def _positive_finite(name: str, value: float) -> float:
    number = float(value)
    if not isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return number


class OutcomeEngine:
    """Pure deterministic LONG outcome math."""

    def calculate_long(
        self,
        *,
        entry_price: float,
        evaluation_price: float,
        notional: float,
    ) -> OutcomeResult:
        entry = _positive_finite("entry_price", entry_price)
        evaluation = _positive_finite("evaluation_price", evaluation_price)
        safe_notional = _positive_finite("notional", notional)

        quantity = safe_notional / entry
        pnl_amount = (evaluation - entry) * quantity
        pnl_pct = (evaluation - entry) / entry

        if not all(isfinite(value) for value in (quantity, pnl_amount, pnl_pct)):
            raise ValueError("calculated outcome must contain only finite values")

        return OutcomeResult(
            entry_price=entry,
            evaluation_price=evaluation,
            quantity=quantity,
            notional=safe_notional,
            pnl_pct=pnl_pct,
            pnl_amount=pnl_amount,
        )


outcome_engine = OutcomeEngine()
