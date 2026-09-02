from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.app.models.executed_trade import ExecutedTrade
from backend.app.services.execution_sync_service import ExecutionSyncService


def _execution(db_session, candidate):
    execution = ExecutedTrade(
        candidate_id=candidate.id,
        risk_decision_id=1,
        alpaca_order_id="paper-order-1",
        symbol=candidate.symbol,
        side="BUY",
        requested_notional=100.0,
        status="accepted",
    )
    db_session.add(execution)
    db_session.commit()
    db_session.refresh(execution)
    return execution


def test_order_sync_updates_fill_fields_without_mutation(db_session, candidate_factory):
    execution = _execution(db_session, candidate_factory())
    provider = MagicMock()
    provider.get_order.return_value = SimpleNamespace(
        status="filled",
        filled_qty="1.25",
        filled_avg_price="80.50",
    )

    result = ExecutionSyncService(provider).sync(
        db=db_session,
        execution_id=execution.id,
    )

    assert result.status == "filled"
    assert result.filled_qty == 1.25
    assert result.filled_avg_price == 80.5
    provider.get_order.assert_called_once_with("paper-order-1")
    assert not hasattr(provider, "submit_order") or provider.submit_order.call_count == 0


def test_sync_requires_existing_order_id(db_session, candidate_factory):
    execution = _execution(db_session, candidate_factory())
    execution.alpaca_order_id = None
    db_session.commit()
    provider = MagicMock()

    with pytest.raises(ValueError, match="no Alpaca order ID"):
        ExecutionSyncService(provider).sync(
            db=db_session,
            execution_id=execution.id,
        )

    provider.get_order.assert_not_called()
