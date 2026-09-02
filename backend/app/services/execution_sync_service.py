from sqlalchemy.orm import Session

from backend.app.models.executed_trade import ExecutedTrade
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


class ExecutionSyncService:
    """Synchronize persisted state using read-only Alpaca order retrieval."""

    def __init__(
        self,
        execution_provider: PaperExecutionService = paper_execution_service,
    ) -> None:
        self.execution_provider = execution_provider

    def sync(self, *, db: Session, execution_id: int) -> ExecutedTrade:
        execution = db.get(ExecutedTrade, execution_id)
        if execution is None:
            raise LookupError(f"ExecutedTrade {execution_id} not found")
        if not execution.alpaca_order_id:
            raise ValueError("Execution has no Alpaca order ID")

        order = self.execution_provider.get_order(execution.alpaca_order_id)

        execution.status = _enum_value(getattr(order, "status", None)) or execution.status
        execution.filled_qty = _float_or_none(
            getattr(order, "filled_qty", None)
        )
        execution.filled_avg_price = _float_or_none(
            getattr(order, "filled_avg_price", None)
        )
        db.commit()
        db.refresh(execution)
        return execution


execution_sync_service = ExecutionSyncService()
