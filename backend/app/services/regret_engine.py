from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class RegretResult:
    classification: str
    decision_value: float


class RegretEngine:
    """Pure deterministic decision-value classification."""

    def classify(
        self,
        *,
        decision: str,
        pnl_amount: float,
    ) -> RegretResult:
        normalized = str(decision).strip().upper()
        if normalized not in {"ACCEPT", "REJECT"}:
            raise ValueError("decision must be ACCEPT or REJECT")

        pnl = float(pnl_amount)
        if not isfinite(pnl):
            raise ValueError("pnl_amount must be finite")

        if normalized == "REJECT":
            classification = "MISSED_ALPHA" if pnl > 0 else "AVOIDED_LOSS"
            decision_value = -pnl
        else:
            classification = (
                "CORRECT_EXECUTION" if pnl >= 0 else "BAD_EXECUTION"
            )
            decision_value = pnl

        return RegretResult(
            classification=classification,
            decision_value=decision_value,
        )


regret_engine = RegretEngine()
