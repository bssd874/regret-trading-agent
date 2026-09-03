from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import Settings, settings
from backend.app.models.decision_analysis import DecisionAnalysis
from backend.app.models.executed_trade import ExecutedTrade
from backend.app.models.risk_decision import RiskDecision
from backend.app.models.trade_exit import TradeExit
from backend.app.services.alpaca_service import EvaluationPrice, alpaca_service
from backend.app.services.paper_execution_service import (
    paper_execution_service,
)


class MarketPriceProvider(Protocol):
    def get_evaluation_price(self, symbol: str) -> EvaluationPrice:
        ...


class ExitExecutionProvider(Protocol):
    def sell_long_market_position(self, *, symbol: str, quantity: float):
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


def _enum_value(value) -> str:
    if value is None:
        return ""
    return str(getattr(value, "value", value))


def _float_or_none(value):
    if value is None:
        return None
    return float(value)


class PositionExitService:
    """Deterministically monitor and exit filled LONG paper positions."""

    def __init__(
        self,
        *,
        market_data: MarketPriceProvider = alpaca_service,
        execution_provider: ExitExecutionProvider = paper_execution_service,
        config: Settings = settings,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.market_data = market_data
        self.execution_provider = execution_provider
        self.config = config
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        return _utc(self.now_provider())

    @staticmethod
    def _existing(db: Session, execution_id: int) -> TradeExit | None:
        return db.scalar(
            select(TradeExit).where(
                TradeExit.executed_trade_id == execution_id
            )
        )

    @staticmethod
    def _load_thesis(
        db: Session,
        execution: ExecutedTrade,
    ) -> tuple[RiskDecision, DecisionAnalysis]:
        risk = db.get(RiskDecision, execution.risk_decision_id)
        if risk is None or str(risk.decision).strip().upper() != "ACCEPT":
            raise RuntimeError("ExecutedTrade has no valid ACCEPT RiskDecision")
        analysis = db.get(DecisionAnalysis, risk.analysis_id)
        if (
            analysis is None
            or analysis.candidate_id != execution.candidate_id
            or analysis.symbol.strip().upper() != execution.symbol.strip().upper()
        ):
            raise RuntimeError("ExecutedTrade has no valid DecisionAnalysis")
        return risk, analysis

    def monitor_execution(self, *, db: Session, execution_id: int) -> dict:
        execution = db.get(ExecutedTrade, execution_id)
        if execution is None:
            raise LookupError(f"ExecutedTrade {execution_id} not found")

        existing = self._existing(db, execution.id)
        if existing is not None:
            return {
                "action": "EXISTING_EXIT",
                "execution_id": execution.id,
                "exit_id": existing.id,
                "reason": existing.reason,
                "status": existing.status,
                "order_submitted": existing.alpaca_order_id is not None,
                "idempotent_replay": True,
            }

        if (
            str(execution.status).strip().lower() != "filled"
            or not _positive_finite(execution.filled_qty)
            or not _positive_finite(execution.filled_avg_price)
        ):
            return {
                "action": "HOLD",
                "execution_id": execution.id,
                "reason": "ENTRY_NOT_FILLED",
            }
        if str(execution.side).strip().upper() != "BUY":
            raise RuntimeError("Only filled BUY/LONG executions may be exited")

        risk, analysis = self._load_thesis(db, execution)
        now = self._now()
        price = self.market_data.get_evaluation_price(execution.symbol)
        current_price = float(price.price)
        if not _positive_finite(current_price):
            raise ValueError("Current market price must be positive and finite")

        stop_loss = float(analysis.stop_loss)
        target_price = float(analysis.target_price)
        horizon_minutes = int(analysis.horizon_minutes)
        base_time = execution.submitted_at or execution.created_at
        expires_at = _utc(base_time) + timedelta(minutes=horizon_minutes)

        if current_price <= stop_loss:
            reason = "STOP_LOSS"
        elif current_price >= target_price:
            reason = "TAKE_PROFIT"
        elif now >= expires_at:
            reason = "TIME_EXIT"
        else:
            return {
                "action": "HOLD",
                "execution_id": execution.id,
                "current_price": current_price,
                "target_price": target_price,
                "stop_loss": stop_loss,
                "expires_at": expires_at.isoformat(),
                "reason": "NO_EXIT_CONDITION",
            }

        if not self.config.paper_execution_enabled:
            return {
                "action": "EXIT_HELD",
                "execution_id": execution.id,
                "exit_reason": reason,
                "current_price": current_price,
                "reason": "PAPER_EXECUTION_DISABLED",
            }

        trade_exit = TradeExit(
            executed_trade_id=execution.id,
            candidate_id=execution.candidate_id,
            risk_decision_id=risk.id,
            symbol=execution.symbol.strip().upper(),
            reason=reason,
            trigger_price=current_price,
            target_price=target_price,
            stop_loss=stop_loss,
            horizon_minutes=horizon_minutes,
            requested_qty=float(execution.filled_qty),
            status="PENDING_SUBMISSION",
            triggered_at=now,
        )
        db.add(trade_exit)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            existing = self._existing(db, execution.id)
            if existing is None:
                raise
            return {
                "action": "EXISTING_EXIT",
                "execution_id": execution.id,
                "exit_id": existing.id,
                "reason": existing.reason,
                "status": existing.status,
                "order_submitted": existing.alpaca_order_id is not None,
                "idempotent_replay": True,
            }
        db.refresh(trade_exit)

        try:
            order = self.execution_provider.sell_long_market_position(
                symbol=trade_exit.symbol,
                quantity=trade_exit.requested_qty,
            )
        except Exception as exc:
            trade_exit.status = "SUBMISSION_FAILED"
            db.commit()
            db.refresh(trade_exit)
            raise RuntimeError(
                "Alpaca paper SELL submission failed; automatic retry is disabled"
            ) from exc

        trade_exit.alpaca_order_id = str(order.id)
        trade_exit.status = _enum_value(getattr(order, "status", None)) or "SUBMITTED"
        trade_exit.filled_qty = _float_or_none(
            getattr(order, "filled_qty", None)
        )
        trade_exit.filled_avg_price = _float_or_none(
            getattr(order, "filled_avg_price", None)
        )
        trade_exit.submitted_at = now
        if trade_exit.status.strip().lower() == "filled":
            trade_exit.closed_at = now
        db.commit()
        db.refresh(trade_exit)

        return {
            "action": "EXIT_TRIGGERED",
            "execution_id": execution.id,
            "exit_id": trade_exit.id,
            "reason": trade_exit.reason,
            "status": trade_exit.status,
            "current_price": current_price,
            "order_submitted": True,
            "idempotent_replay": False,
        }


position_exit_service = PositionExitService()
