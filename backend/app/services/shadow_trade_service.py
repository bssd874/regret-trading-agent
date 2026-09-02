from datetime import (
    datetime,
    timedelta,
    timezone,
)
from math import isfinite

from sqlalchemy.orm import Session

from backend.app.models.decision_analysis import (
    DecisionAnalysis,
)
from backend.app.models.risk_decision import (
    RiskDecision,
)
from backend.app.models.shadow_trade import (
    ShadowTrade,
)


class ShadowTradeService:

    def create(
        self,
        *,
        db: Session,
        risk: RiskDecision,
        analysis: DecisionAnalysis,
        equity: float,
    ) -> ShadowTrade:

        existing = (
            db.query(ShadowTrade)
            .filter(
                ShadowTrade.risk_decision_id
                == risk.id
            )
            .first()
        )

        if existing:
            return existing

        if risk.decision != "REJECT":
            raise ValueError(
                "ShadowTrade requires REJECT decision"
            )

        if not isfinite(equity) or equity <= 0:
            raise ValueError("equity must be a positive finite number")
        if (
            not isfinite(risk.proposed_position_pct)
            or risk.proposed_position_pct <= 0
        ):
            raise ValueError("risk position percentage must be positive and finite")

        notional = (
            equity
            * risk.proposed_position_pct
        )

        now = datetime.now(timezone.utc)

        shadow = ShadowTrade(
            candidate_id=risk.candidate_id,
            risk_decision_id=risk.id,
            symbol=analysis.symbol,
            side="BUY",
            hypothetical_entry=(
                analysis.entry_price
            ),
            hypothetical_notional=round(
                notional,
                2,
            ),
            stop_loss=analysis.stop_loss,
            target_price=analysis.target_price,
            horizon_minutes=(
                analysis.horizon_minutes
            ),
            status="OPEN",
            opened_at=now,
            evaluation_due_at=(
                now
                + timedelta(
                    minutes=(
                        analysis.horizon_minutes
                    )
                )
            ),
        )

        db.add(shadow)
        db.commit()
        db.refresh(shadow)

        return shadow


shadow_trade_service = ShadowTradeService()
