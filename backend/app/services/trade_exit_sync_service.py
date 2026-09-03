from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.app.models.trade_exit import TradeExit
from backend.app.services.paper_execution_service import (
    PaperExecutionService,
    paper_execution_service,
)


def _enum_value(value) -> str:
    if value is None:
        return ""
    return str(getattr(value, "value", value))


def _float_or_none(value):
    if value is None:
        return None
    return float(value)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _filled_at_or_now(value, now: datetime) -> datetime:
    if isinstance(value, datetime):
        return _utc(value)
    if value:
        try:
            return _utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
        except ValueError:
            pass
    return _utc(now)


class TradeExitSyncService:
    """Synchronize a persisted SELL using read-only order retrieval."""

    def __init__(
        self,
        execution_provider: PaperExecutionService = paper_execution_service,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.execution_provider = execution_provider
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def sync(self, *, db: Session, exit_id: int) -> TradeExit:
        trade_exit = db.get(TradeExit, exit_id)
        if trade_exit is None:
            raise LookupError(f"TradeExit {exit_id} not found")
        if not trade_exit.alpaca_order_id:
            raise ValueError("TradeExit has no Alpaca order ID")

        order = self.execution_provider.get_order(trade_exit.alpaca_order_id)
        status = _enum_value(getattr(order, "status", None))
        trade_exit.status = status or trade_exit.status
        trade_exit.filled_qty = _float_or_none(
            getattr(order, "filled_qty", None)
        )
        trade_exit.filled_avg_price = _float_or_none(
            getattr(order, "filled_avg_price", None)
        )
        if trade_exit.status.strip().lower() == "filled":
            trade_exit.closed_at = _filled_at_or_now(
                getattr(order, "filled_at", None),
                self.now_provider(),
            )

        db.commit()
        db.refresh(trade_exit)
        return trade_exit


trade_exit_sync_service = TradeExitSyncService()
