from datetime import datetime, timezone
from math import isfinite

from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.candidate_trade import CandidateTrade
from backend.app.models.critic_analysis import CriticAnalysis
from backend.app.models.decision_analysis import DecisionAnalysis
from backend.app.models.executed_trade import ExecutedTrade
from backend.app.models.risk_decision import RiskDecision
from backend.app.models.shadow_trade import ShadowTrade
from backend.app.services.alpaca_service import alpaca_service
from backend.app.services.paper_execution_service import (
    paper_execution_service,
)
from backend.app.services.shadow_trade_service import (
    shadow_trade_service,
)


def _enum_value(value) -> str:
    """
    Normalize Alpaca enum-like values into plain strings.
    """
    if value is None:
        return ""

    return str(
        getattr(
            value,
            "value",
            value,
        )
    )


def _float_or_none(value):
    if value is None:
        return None

    return float(value)


class DecisionRouter:

    def route(
        self,
        *,
        db: Session,
        decision_id: int,
    ) -> dict:
        """
        Route a completed deterministic RiskDecision.

        REJECT
            -> ShadowTrade

        ACCEPT
            -> Alpaca PAPER execution,
               only when kill switch is enabled.

        This router never decides whether a trade
        should be accepted or rejected. That decision
        must already exist in RiskDecision.
        """

        # =====================================================
        # 1. Load deterministic risk decision
        # =====================================================

        risk = db.get(
            RiskDecision,
            decision_id,
        )

        if risk is None:
            raise LookupError(
                f"RiskDecision {decision_id} not found"
            )

        analysis = db.get(
            DecisionAnalysis,
            risk.analysis_id,
        )

        if analysis is None:
            raise RuntimeError(
                "RiskDecision has no valid "
                "DecisionAnalysis"
            )

        candidate = db.get(
            CandidateTrade,
            risk.candidate_id,
        )

        if candidate is None:
            raise RuntimeError(
                "RiskDecision has no valid candidate"
            )

        critic = db.get(CriticAnalysis, risk.critic_id)
        if critic is None:
            raise RuntimeError("RiskDecision has no valid CriticAnalysis")

        if (
            analysis.candidate_id != candidate.id
            or critic.candidate_id != candidate.id
            or critic.analysis_id != analysis.id
        ):
            raise RuntimeError("RiskDecision analysis chain is inconsistent")

        if (
            candidate.side.strip().upper() != "BUY"
            or analysis.direction.strip().upper() != "LONG"
            or analysis.symbol.strip().upper() != candidate.symbol.strip().upper()
        ):
            raise RuntimeError("Only a consistent BUY/LONG analysis may be routed")

        # =====================================================
        # 2. Validate final deterministic decision
        # =====================================================

        decision = (
            str(risk.decision)
            .strip()
            .upper()
        )

        if decision not in {
            "ACCEPT",
            "REJECT",
        }:
            raise ValueError(
                "RiskDecision must be "
                "ACCEPT or REJECT"
            )

        # =====================================================
        # 3. Prevent contradictory routing
        # =====================================================

        existing_execution = (
            db.query(ExecutedTrade)
            .filter(
                ExecutedTrade.risk_decision_id
                == risk.id
            )
            .first()
        )

        existing_shadow = (
            db.query(ShadowTrade)
            .filter(
                ShadowTrade.risk_decision_id
                == risk.id
            )
            .first()
        )

        if (
            existing_execution is not None
            and existing_shadow is not None
        ):
            raise RuntimeError(
                "Invalid state: this decision has both "
                "an ExecutedTrade and ShadowTrade"
            )

        # =====================================================
        # 4. REJECT PATH
        # =====================================================

        if decision == "REJECT":

            if candidate.status != "REJECTED":
                raise RuntimeError(
                    "REJECT decision requires candidate "
                    "status REJECTED"
                )

            #
            # A rejected decision must NEVER have
            # an execution record.
            #
            if existing_execution is not None:
                raise RuntimeError(
                    "Safety violation: REJECT decision "
                    "already has execution record"
                )

            #
            # Idempotency:
            # return existing ShadowTrade if route
            # was already called previously.
            #
            if existing_shadow is not None:
                return {
                    "route": "SHADOW",
                    "decision": "REJECT",

                    "shadow_trade_id":
                        existing_shadow.id,

                    "shadow_status":
                        existing_shadow.status,

                    "idempotent_replay": True,

                    "paper": True,

                    "order_submitted": False,
                }

            #
            # Account call is READ ONLY.
            #
            # Equity is needed only to calculate the
            # hypothetical shadow notional.
            #
            account = alpaca_service.get_account()

            equity = float(account.equity)

            if not isfinite(equity) or equity <= 0:
                raise RuntimeError(
                    "Invalid Alpaca paper equity"
                )

            shadow = shadow_trade_service.create(
                db=db,
                risk=risk,
                analysis=analysis,
                equity=equity,
            )

            return {
                "route": "SHADOW",
                "decision": "REJECT",

                "shadow_trade_id":
                    shadow.id,

                "symbol":
                    shadow.symbol,

                "hypothetical_entry":
                    shadow.hypothetical_entry,

                "hypothetical_notional":
                    shadow.hypothetical_notional,

                "evaluation_due_at":
                    shadow.evaluation_due_at,

                "shadow_status":
                    shadow.status,

                "idempotent_replay": False,

                "paper": True,

                #
                # Very important for API/demo safety.
                #
                "order_submitted": False,
            }

        # =====================================================
        # 5. ACCEPT PATH
        # =====================================================

        if candidate.status != "ACCEPTED":
            raise RuntimeError(
                "ACCEPT decision requires candidate "
                "status ACCEPTED"
            )

        #
        # ACCEPT must never have a ShadowTrade.
        #
        if existing_shadow is not None:
            raise RuntimeError(
                "Safety violation: ACCEPT decision "
                "already has ShadowTrade"
            )

        #
        # Idempotency:
        #
        # If the route has already produced an
        # ExecutedTrade, NEVER submit another order.
        #
        if existing_execution is not None:
            return {
                "route": "PAPER_EXECUTION",
                "decision": "ACCEPT",

                "executed_trade_id":
                    existing_execution.id,

                "alpaca_order_id":
                    existing_execution.alpaca_order_id,

                "execution_status":
                    existing_execution.status,

                "idempotent_replay": True,

                "paper": True,

                "order_submitted": (
                    existing_execution.alpaca_order_id
                    is not None
                ),
            }

        # =====================================================
        # 6. Explicit execution kill switch
        # =====================================================

        if not settings.paper_execution_enabled:
            raise RuntimeError(
                "Paper execution kill switch is disabled"
            )

        # =====================================================
        # 7. Calculate paper position size
        # =====================================================

        account = alpaca_service.get_account()

        equity = float(account.equity)

        if not isfinite(equity) or equity <= 0:
            raise RuntimeError(
                "Invalid Alpaca paper account equity"
            )

        risk_position_pct = float(
            risk.proposed_position_pct
        )

        if not isfinite(risk_position_pct) or not 0 < risk_position_pct <= 0.05:
            raise RuntimeError(
                "RiskDecision contains invalid "
                "position percentage"
            )

        #
        # Fail conservatively:
        # never exceed either the RiskDecision allocation
        # or the configured execution allocation.
        #
        allocation_pct = min(
            risk_position_pct,
            settings.execution_position_pct,
        )

        notional = round(
            equity * allocation_pct,
            2,
        )

        if notional <= 0:
            raise RuntimeError(
                "Calculated order notional is invalid"
            )

        # =====================================================
        # 8. Reserve execution record BEFORE API submission
        # =====================================================
        #
        # This gives us a persistent record before touching
        # Alpaca and prevents normal repeated routing calls
        # from submitting another order.
        #

        execution = ExecutedTrade(
            candidate_id=candidate.id,
            risk_decision_id=risk.id,
            alpaca_order_id=None,
            symbol=analysis.symbol,
            side="BUY",
            requested_notional=notional,
            status="PENDING_SUBMISSION",
        )

        db.add(execution)
        db.commit()
        db.refresh(execution)

        # =====================================================
        # 9. Submit PAPER order
        # =====================================================

        try:
            order = (
                paper_execution_service
                .submit_long_market_order(
                    symbol=analysis.symbol,
                    notional=notional,
                )
            )

        except Exception as exc:

            execution.status = (
                "SUBMISSION_FAILED"
            )

            db.commit()
            db.refresh(execution)

            #
            # Fail closed.
            #
            # We intentionally DO NOT automatically retry.
            #
            raise RuntimeError(
                "Alpaca paper submission failed; automatic retry is disabled"
            ) from exc

        # =====================================================
        # 10. Persist Alpaca response
        # =====================================================

        execution.alpaca_order_id = str(
            order.id
        )

        execution.status = (
            _enum_value(order.status)
            or "SUBMITTED"
        )

        execution.filled_qty = (
            _float_or_none(
                getattr(
                    order,
                    "filled_qty",
                    None,
                )
            )
        )

        execution.filled_avg_price = (
            _float_or_none(
                getattr(
                    order,
                    "filled_avg_price",
                    None,
                )
            )
        )

        execution.submitted_at = (
            datetime.now(timezone.utc)
        )

        db.commit()
        db.refresh(execution)

        # =====================================================
        # 11. Return API-safe result
        # =====================================================

        return {
            "route": "PAPER_EXECUTION",
            "decision": "ACCEPT",

            "executed_trade_id":
                execution.id,

            "symbol":
                execution.symbol,

            "requested_notional":
                execution.requested_notional,

            "alpaca_order_id":
                execution.alpaca_order_id,

            "execution_status":
                execution.status,

            "filled_qty":
                execution.filled_qty,

            "filled_avg_price":
                execution.filled_avg_price,

            "idempotent_replay": False,

            "paper": True,

            "order_submitted": True,
        }


decision_router = DecisionRouter()
