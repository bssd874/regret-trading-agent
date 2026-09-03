from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.app.models.trade_exit import TradeExit
from backend.app.services.trade_exit_sync_service import TradeExitSyncService
from backend.tests.test_decision_router import _create_routing_chain
from backend.tests.test_outcome_pipeline import NOW, _executed


def _trade_exit(db_session, candidate_factory, *, status="accepted"):
    candidate = candidate_factory(symbol="SYNCEXIT")
    risk, analysis = _create_routing_chain(
        db_session,
        candidate,
        decision="ACCEPT",
    )
    execution = _executed(db_session, candidate, risk)
    trade_exit = TradeExit(
        executed_trade_id=execution.id,
        candidate_id=candidate.id,
        risk_decision_id=risk.id,
        symbol=candidate.symbol,
        reason="TIME_EXIT",
        trigger_price=101.0,
        target_price=analysis.target_price,
        stop_loss=analysis.stop_loss,
        horizon_minutes=analysis.horizon_minutes,
        requested_qty=10.0,
        alpaca_order_id="paper-sell-sync",
        status=status,
        triggered_at=NOW - timedelta(minutes=2),
        submitted_at=NOW - timedelta(minutes=1),
    )
    db_session.add(trade_exit)
    db_session.commit()
    db_session.refresh(trade_exit)
    return trade_exit


def test_pending_sell_reconciles_and_remains_pending_safely(
    db_session,
    candidate_factory,
):
    trade_exit = _trade_exit(db_session, candidate_factory)
    provider = MagicMock()
    provider.get_order.return_value = SimpleNamespace(
        status="accepted",
        filled_qty=None,
        filled_avg_price=None,
    )

    result = TradeExitSyncService(provider).sync(
        db=db_session,
        exit_id=trade_exit.id,
    )

    assert result.status == "accepted"
    assert result.filled_qty is None
    assert result.filled_avg_price is None
    assert result.closed_at is None
    provider.get_order.assert_called_once_with("paper-sell-sync")


def test_pending_sell_later_becomes_filled_with_alpaca_values(
    db_session,
    candidate_factory,
):
    trade_exit = _trade_exit(db_session, candidate_factory)
    provider = MagicMock()
    provider.get_order.side_effect = [
        SimpleNamespace(
            status="accepted",
            filled_qty=None,
            filled_avg_price=None,
        ),
        SimpleNamespace(
            status="filled",
            filled_qty="2.5",
            filled_avg_price="105.75",
            filled_at=NOW,
        ),
    ]
    service = TradeExitSyncService(provider, now_provider=lambda: NOW)

    service.sync(db=db_session, exit_id=trade_exit.id)
    result = service.sync(db=db_session, exit_id=trade_exit.id)

    assert result.status == "filled"
    assert result.filled_qty == 2.5
    assert result.filled_avg_price == 105.75
    assert result.closed_at == NOW.replace(tzinfo=None) or result.closed_at == NOW
    assert provider.get_order.call_count == 2
