from datetime import datetime, timezone
from math import isfinite
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.decision_analysis import DecisionAnalysis
from backend.app.models.executed_trade import ExecutedTrade
from backend.app.models.outcome_snapshot import OutcomeSnapshot
from backend.app.models.regret_event import RegretEvent
from backend.app.models.risk_decision import RiskDecision
from backend.app.models.shadow_trade import ShadowTrade
from backend.app.models.trade_exit import TradeExit
from backend.app.services.alpaca_service import EvaluationPrice, alpaca_service
from backend.app.services.outcome_engine import OutcomeEngine, outcome_engine
from backend.app.services.regret_engine import RegretEngine, regret_engine


class MarketPriceProvider(Protocol):
    def get_evaluation_price(self, symbol: str) -> EvaluationPrice:
        ...


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _positive_finite(value) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return isfinite(number) and number > 0


class OutcomePipeline:
    """Read-only-against-Alpaca outcome persistence pipeline."""

    def __init__(
        self,
        *,
        market_data: MarketPriceProvider = alpaca_service,
        outcome_calculator: OutcomeEngine = outcome_engine,
        regret_classifier: RegretEngine = regret_engine,
    ) -> None:
        self.market_data = market_data
        self.outcome_calculator = outcome_calculator
        self.regret_classifier = regret_classifier

    @staticmethod
    def _existing(
        db: Session,
        *,
        source_type: str,
        source_id: int,
    ) -> OutcomeSnapshot | None:
        return db.scalar(
            select(OutcomeSnapshot).where(
                OutcomeSnapshot.source_type == source_type,
                OutcomeSnapshot.source_id == source_id,
            )
        )

    def _event_for_outcome(
        self,
        db: Session,
        outcome: OutcomeSnapshot,
    ) -> RegretEvent:
        event = db.scalar(
            select(RegretEvent).where(RegretEvent.outcome_id == outcome.id)
        )
        if event is not None:
            return event

        result = self.regret_classifier.classify(
            decision=outcome.decision,
            pnl_amount=outcome.pnl_amount,
        )
        event = RegretEvent(
            outcome_id=outcome.id,
            candidate_id=outcome.candidate_id,
            risk_decision_id=outcome.risk_decision_id,
            symbol=outcome.symbol,
            decision=outcome.decision,
            classification=result.classification,
            pnl_pct=outcome.pnl_pct,
            pnl_amount=outcome.pnl_amount,
            decision_value=result.decision_value,
        )
        db.add(event)
        db.flush()
        return event

    @staticmethod
    def _payload(
        outcome: OutcomeSnapshot,
        event: RegretEvent,
        *,
        idempotent_replay: bool,
    ) -> dict:
        return {
            "status": "EVALUATED",
            "source_type": outcome.source_type,
            "source_id": outcome.source_id,
            "outcome_id": outcome.id,
            "regret_event_id": event.id,
            "classification": event.classification,
            "decision_value": event.decision_value,
            "pnl_pct": outcome.pnl_pct,
            "pnl_amount": outcome.pnl_amount,
            "price_source": outcome.price_source,
            "idempotent_replay": idempotent_replay,
        }

    def _return_existing(
        self,
        db: Session,
        outcome: OutcomeSnapshot,
        *,
        shadow: ShadowTrade | None = None,
    ) -> dict:
        event = self._event_for_outcome(db, outcome)
        if shadow is not None and shadow.status != "EVALUATED":
            shadow.status = "EVALUATED"
        db.commit()
        db.refresh(event)
        return self._payload(outcome, event, idempotent_replay=True)

    def _persist(
        self,
        db: Session,
        *,
        source_type: str,
        source_id: int,
        candidate_id: int,
        risk_decision_id: int,
        symbol: str,
        decision: str,
        entry_price: float,
        evaluation_price: EvaluationPrice,
        notional: float,
        due_at: datetime,
        evaluated_at: datetime,
        shadow: ShadowTrade | None = None,
    ) -> dict:
        calculated = self.outcome_calculator.calculate_long(
            entry_price=entry_price,
            evaluation_price=evaluation_price.price,
            notional=notional,
        )
        outcome = OutcomeSnapshot(
            source_type=source_type,
            source_id=source_id,
            candidate_id=candidate_id,
            risk_decision_id=risk_decision_id,
            symbol=symbol,
            decision=decision,
            entry_price=calculated.entry_price,
            evaluation_price=calculated.evaluation_price,
            quantity=calculated.quantity,
            notional=calculated.notional,
            pnl_pct=calculated.pnl_pct,
            pnl_amount=calculated.pnl_amount,
            due_at=due_at,
            evaluated_at=evaluated_at,
            price_source=evaluation_price.source,
        )

        try:
            db.add(outcome)
            db.flush()
            event = self._event_for_outcome(db, outcome)
            if shadow is not None:
                shadow.status = "EVALUATED"
            db.commit()
            db.refresh(outcome)
            db.refresh(event)
        except IntegrityError:
            db.rollback()
            existing = self._existing(
                db,
                source_type=source_type,
                source_id=source_id,
            )
            if existing is None:
                raise
            return self._return_existing(db, existing, shadow=shadow)

        return self._payload(outcome, event, idempotent_replay=False)

    def evaluate_shadow(
        self,
        *,
        db: Session,
        shadow_id: int,
        now: datetime | None = None,
    ) -> dict:
        shadow = db.get(ShadowTrade, shadow_id)
        if shadow is None:
            raise LookupError(f"ShadowTrade {shadow_id} not found")

        existing = self._existing(
            db,
            source_type="SHADOW",
            source_id=shadow.id,
        )
        if existing is not None:
            return self._return_existing(db, existing, shadow=shadow)
        if shadow.status != "OPEN":
            raise RuntimeError("ShadowTrade is not OPEN and has no outcome")

        evaluated_at = _utc(now or datetime.now(timezone.utc))
        due_at = _utc(shadow.evaluation_due_at)
        if evaluated_at < due_at:
            return {
                "status": "NOT_READY",
                "source_type": "SHADOW",
                "source_id": shadow.id,
                "reason": "ShadowTrade evaluation is not due",
            }

        risk = db.get(RiskDecision, shadow.risk_decision_id)
        if risk is None or risk.decision != "REJECT":
            raise RuntimeError("ShadowTrade has no valid REJECT RiskDecision")

        price = self.market_data.get_evaluation_price(shadow.symbol)
        return self._persist(
            db,
            source_type="SHADOW",
            source_id=shadow.id,
            candidate_id=shadow.candidate_id,
            risk_decision_id=shadow.risk_decision_id,
            symbol=shadow.symbol,
            decision="REJECT",
            entry_price=shadow.hypothetical_entry,
            evaluation_price=price,
            notional=shadow.hypothetical_notional,
            due_at=due_at,
            evaluated_at=evaluated_at,
            shadow=shadow,
        )

    def evaluate_execution(
        self,
        *,
        db: Session,
        execution_id: int,
        now: datetime | None = None,
    ) -> dict:
        execution = db.get(ExecutedTrade, execution_id)
        if execution is None:
            raise LookupError(f"ExecutedTrade {execution_id} not found")

        existing = self._existing(
            db,
            source_type="EXECUTED",
            source_id=execution.id,
        )
        if existing is not None:
            return self._return_existing(db, existing)

        if (
            str(execution.status).strip().lower() != "filled"
            or not _positive_finite(execution.filled_avg_price)
            or not _positive_finite(execution.filled_qty)
        ):
            return {
                "status": "NOT_READY",
                "source_type": "EXECUTED",
                "source_id": execution.id,
                "reason": "Execution does not have a genuine completed fill",
            }

        trade_exit = db.scalar(
            select(TradeExit).where(
                TradeExit.executed_trade_id == execution.id
            )
        )
        if (
            trade_exit is None
            or str(trade_exit.status).strip().lower() != "filled"
            or not _positive_finite(trade_exit.filled_avg_price)
            or not _positive_finite(trade_exit.filled_qty)
        ):
            return {
                "status": "NOT_READY",
                "source_type": "EXECUTED",
                "source_id": execution.id,
                "reason": "POSITION_STILL_OPEN",
            }

        risk = db.get(RiskDecision, execution.risk_decision_id)
        if risk is None or risk.decision != "ACCEPT":
            raise RuntimeError("ExecutedTrade has no valid ACCEPT RiskDecision")
        analysis = db.get(DecisionAnalysis, risk.analysis_id)
        if analysis is None or analysis.candidate_id != execution.candidate_id:
            raise RuntimeError("ExecutedTrade has no valid DecisionAnalysis")

        evaluated_at = _utc(now or datetime.now(timezone.utc))
        entry_price = float(execution.filled_avg_price)
        quantity = float(trade_exit.filled_qty)
        exit_price = float(trade_exit.filled_avg_price)
        due_at = _utc(
            trade_exit.closed_at
            or trade_exit.updated_at
            or trade_exit.created_at
        )
        return self._persist(
            db,
            source_type="EXECUTED",
            source_id=execution.id,
            candidate_id=execution.candidate_id,
            risk_decision_id=execution.risk_decision_id,
            symbol=execution.symbol,
            decision="ACCEPT",
            entry_price=entry_price,
            evaluation_price=EvaluationPrice(
                price=exit_price,
                source="alpaca_exit_fill",
            ),
            notional=entry_price * quantity,
            due_at=due_at,
            evaluated_at=evaluated_at,
        )

    def evaluate_due(
        self,
        *,
        db: Session,
        now: datetime | None = None,
    ) -> dict:
        evaluated_at = _utc(now or datetime.now(timezone.utc))
        shadow_ids = list(
            db.scalars(
                select(ShadowTrade.id).where(
                    ShadowTrade.status == "OPEN",
                    ShadowTrade.evaluation_due_at <= evaluated_at,
                )
            ).all()
        )
        execution_ids = list(
            db.scalars(
                select(ExecutedTrade.id).where(
                    func.lower(ExecutedTrade.status) == "filled"
                )
            ).all()
        )

        items: list[dict] = []
        for source_type, source_id in (
            [("SHADOW", item_id) for item_id in shadow_ids]
            + [("EXECUTED", item_id) for item_id in execution_ids]
        ):
            try:
                if source_type == "SHADOW":
                    result = self.evaluate_shadow(
                        db=db,
                        shadow_id=source_id,
                        now=evaluated_at,
                    )
                else:
                    result = self.evaluate_execution(
                        db=db,
                        execution_id=source_id,
                        now=evaluated_at,
                    )
                items.append(result)
            except Exception:
                db.rollback()
                items.append(
                    {
                        "status": "ERROR",
                        "source_type": source_type,
                        "source_id": source_id,
                        "reason": "Outcome evaluation failed safely",
                    }
                )

        return {
            "evaluated": sum(item["status"] == "EVALUATED" for item in items),
            "not_ready": sum(item["status"] == "NOT_READY" for item in items),
            "errors": sum(item["status"] == "ERROR" for item in items),
            "items": items,
        }


outcome_pipeline = OutcomePipeline()
