from dataclasses import dataclass
from math import isfinite


MIN_CONFIDENCE = 0.70
MIN_REWARD_RISK = 1.50
MAX_POSITION_PCT = 0.05
MAX_DAILY_LOSS_PCT = 0.02
MAX_STOP_DISTANCE_PCT = 0.05


@dataclass(frozen=True)
class RiskResult:
    decision: str
    risk_score: float
    reward_risk_ratio: float
    proposed_position_pct: float
    reasons: list[str]


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(float(value))
    )


class RiskEngine:
    """Deterministic, fail-closed final authority for a candidate."""

    def evaluate(
        self,
        *,
        adjusted_confidence: float,
        entry_price: float,
        stop_loss: float,
        target_price: float,
        equity: float,
        last_equity: float,
        proposed_position_pct: float = 0.02,
    ) -> RiskResult:
        reasons: list[str] = []

        confidence_valid = _is_finite_number(adjusted_confidence)
        entry_valid = _is_finite_number(entry_price) and entry_price > 0
        stop_valid = _is_finite_number(stop_loss) and stop_loss > 0
        target_valid = _is_finite_number(target_price) and target_price > 0
        equity_valid = _is_finite_number(equity) and equity > 0
        last_equity_valid = (
            _is_finite_number(last_equity) and last_equity > 0
        )
        position_valid = (
            _is_finite_number(proposed_position_pct)
            and proposed_position_pct > 0
        )

        if not confidence_valid or not 0.0 <= adjusted_confidence <= 1.0:
            reasons.append("invalid confidence")
            confidence_valid = False

        if not entry_valid:
            reasons.append("invalid entry price")

        if not stop_valid:
            reasons.append("invalid stop loss")

        if not target_valid:
            reasons.append("invalid target price")

        if not equity_valid:
            reasons.append("invalid account equity")

        if not last_equity_valid:
            reasons.append("invalid last equity")

        if not position_valid:
            reasons.append("invalid position size")

        levels_valid = entry_valid and stop_valid and target_valid

        if levels_valid and stop_loss >= entry_price:
            reasons.append("stop loss must be below entry")
            levels_valid = False

        if entry_valid and target_valid and target_price <= entry_price:
            reasons.append("target must be above entry")
            levels_valid = False

        reward_risk_ratio = 0.0
        stop_distance_pct = 1.0

        if levels_valid:
            risk_per_share = entry_price - stop_loss
            reward_per_share = target_price - entry_price
            reward_risk_ratio = reward_per_share / risk_per_share
            stop_distance_pct = risk_per_share / entry_price

        if confidence_valid and adjusted_confidence < MIN_CONFIDENCE:
            reasons.append("confidence below minimum threshold")

        if levels_valid and reward_risk_ratio < MIN_REWARD_RISK:
            reasons.append("reward/risk ratio below minimum")

        if levels_valid and stop_distance_pct > MAX_STOP_DISTANCE_PCT:
            reasons.append("stop distance exceeds maximum")

        if position_valid and proposed_position_pct > MAX_POSITION_PCT:
            reasons.append("position size exceeds maximum")

        if equity_valid and last_equity_valid:
            daily_return = (equity - last_equity) / last_equity

            if daily_return <= -MAX_DAILY_LOSS_PCT:
                reasons.append("daily loss limit reached")

        decision = "ACCEPT" if not reasons else "REJECT"
        risk_score = min(
            100.0,
            len(reasons) * 20 + stop_distance_pct * 500,
        )

        safe_position_pct = (
            float(proposed_position_pct) if position_valid else 0.0
        )

        return RiskResult(
            decision=decision,
            risk_score=round(risk_score, 2),
            reward_risk_ratio=round(reward_risk_ratio, 4),
            proposed_position_pct=round(safe_position_pct, 4),
            reasons=reasons,
        )


risk_engine = RiskEngine()
