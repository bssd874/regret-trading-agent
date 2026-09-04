"""Disarming NEW entries must never strand an open position.

Runtime entry permission and exit permission are separate concerns. Every test
here runs with the runtime control explicitly DISARMED and asserts that the
autonomous exit lifecycle still functions end to end.
"""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import func, select

from backend.app.models.trade_exit import TradeExit
from backend.app.services.position_exit_service import PositionExitService
from backend.app.services.runtime_control_service import (
    ENTRY_BUDGET_EXHAUSTED,
    ENTRY_DISARMED,
)
from backend.app.services.trade_exit_sync_service import TradeExitSyncService
from backend.tests.runtime_control_helpers import (
    NOW as CONTROL_NOW,
    make_service,
    seed_control,
)
from backend.tests.test_autonomous_agent_service import _settings
from backend.tests.test_outcome_pipeline import NOW
from backend.tests.test_position_exit_service import (
    FixedMarketData,
    _open_position,
    _provider,
)


def _config(**overrides):
    values = {"paper_execution_enabled": True}
    values.update(overrides)
    return _settings(**values)


def _disarmed(db, **overrides):
    """Runtime control with NEW entries blocked, in several shapes."""
    values = {"state": "DISARMED", "new_entries_armed": False}
    values.update(overrides)
    return seed_control(db, **values)


def _exit_service(config, *, price, provider, now=None):
    return PositionExitService(
        market_data=FixedMarketData(price),
        execution_provider=provider,
        config=config,
        now_provider=lambda: now or NOW,
    )


def _count_exits(db):
    return db.scalar(select(func.count()).select_from(TradeExit))


# ---------------------------------------------------------------
# 30-32 every exit reason still fires while disarmed
# ---------------------------------------------------------------
@pytest.mark.parametrize(
    "price,submitted_ago,expected_reason",
    [
        (104.0, timedelta(minutes=30), "TAKE_PROFIT"),
        (98.0, timedelta(minutes=30), "STOP_LOSS"),
        (100.0, timedelta(minutes=61), "TIME_EXIT"),
    ],
)
def test_disarmed_runtime_still_allows_every_autonomous_exit(
    db_session,
    candidate_factory,
    price,
    submitted_ago,
    expected_reason,
):
    _disarmed(db_session)
    config = _config()
    execution, _, _ = _open_position(
        db_session,
        candidate_factory,
        symbol=f"D{expected_reason[:4]}",
        submitted_ago=submitted_ago,
    )
    provider = _provider()

    result = _exit_service(
        config, price=price, provider=provider
    ).monitor_execution(db=db_session, execution_id=execution.id)

    assert result["action"] == "EXIT_TRIGGERED"
    assert result["reason"] == expected_reason
    assert result["order_submitted"] is True
    assert _count_exits(db_session) == 1
    provider.sell_long_market_position.assert_called_once()
    # The runtime layer is genuinely off for this position.
    service = make_service(config)
    assert service.is_entry_armed(db_session) is False


# ---------------------------------------------------------------
# 33-34 both disarm paths leave exits intact
# ---------------------------------------------------------------
@pytest.mark.parametrize(
    "disarm_reason,control_kwargs,expected_state",
    [
        (
            "EXECUTION_BUDGET_USED",
            {
                "state": "ARMED",
                "new_entries_armed": True,
                "armed_at": CONTROL_NOW,
                "armed_until": CONTROL_NOW + timedelta(minutes=15),
                "executions_used": 1,
                "max_new_executions": 1,
            },
            ENTRY_BUDGET_EXHAUSTED,
        ),
        (
            "OPERATOR_DISARM",
            {"state": "DISARMED", "new_entries_armed": False},
            ENTRY_DISARMED,
        ),
    ],
)
def test_exit_still_fires_after_auto_or_manual_disarm(
    db_session,
    candidate_factory,
    disarm_reason,
    control_kwargs,
    expected_state,
):
    seed_control(
        db_session,
        last_disarm_reason=disarm_reason,
        **control_kwargs,
    )
    config = _config()
    execution, _, _ = _open_position(
        db_session,
        candidate_factory,
        symbol="AFTER",
    )
    provider = _provider()

    service = make_service(config)
    assert service.is_entry_armed(db_session) is False
    assert service.entry_execution_state(
        service.get_control(db_session)
    ) == expected_state

    result = _exit_service(
        config, price=104.0, provider=provider
    ).monitor_execution(db=db_session, execution_id=execution.id)

    assert result["action"] == "EXIT_TRIGGERED"
    assert result["reason"] == "TAKE_PROFIT"
    provider.sell_long_market_position.assert_called_once()


# ---------------------------------------------------------------
# 35 pending SELL reconciliation while disarmed
# ---------------------------------------------------------------
def test_pending_sell_reconciles_to_filled_while_disarmed(
    db_session,
    candidate_factory,
):
    _disarmed(db_session)
    config = _config()
    execution, _, _ = _open_position(
        db_session,
        candidate_factory,
        symbol="PEND",
    )
    provider = _provider()
    triggered = _exit_service(
        config, price=104.0, provider=provider
    ).monitor_execution(db=db_session, execution_id=execution.id)
    trade_exit = db_session.get(TradeExit, triggered["exit_id"])
    assert trade_exit.status != "filled"

    sync_provider = MagicMock()
    sync_provider.get_order.return_value = SimpleNamespace(
        status="filled",
        filled_qty="2.5",
        filled_avg_price="104.10",
    )
    synced = TradeExitSyncService(sync_provider).sync(
        db=db_session,
        exit_id=trade_exit.id,
    )

    assert synced.status == "filled"
    assert synced.filled_qty == 2.5
    assert synced.filled_avg_price == 104.10


# ---------------------------------------------------------------
# 36-37 idempotency and realized P&L basis are unchanged
# ---------------------------------------------------------------
def test_exit_idempotency_still_yields_exactly_one_exit_while_disarmed(
    db_session,
    candidate_factory,
):
    _disarmed(db_session)
    config = _config()
    execution, _, _ = _open_position(
        db_session,
        candidate_factory,
        symbol="ONCE",
    )
    provider = _provider()
    service = _exit_service(config, price=104.0, provider=provider)

    first = service.monitor_execution(db=db_session, execution_id=execution.id)
    second = service.monitor_execution(db=db_session, execution_id=execution.id)

    assert first["action"] == "EXIT_TRIGGERED"
    assert second["action"] != "EXIT_TRIGGERED"
    assert _count_exits(db_session) == 1
    provider.sell_long_market_position.assert_called_once()


def test_realized_pnl_uses_the_confirmed_exit_fill_while_disarmed(
    db_session,
    candidate_factory,
):
    _disarmed(db_session)
    config = _config()
    execution, _, _ = _open_position(
        db_session,
        candidate_factory,
        symbol="REAL",
    )
    triggered = _exit_service(
        config, price=104.0, provider=_provider()
    ).monitor_execution(db=db_session, execution_id=execution.id)

    sync_provider = MagicMock()
    sync_provider.get_order.return_value = SimpleNamespace(
        status="filled",
        filled_qty="2.5",
        filled_avg_price="104.10",
    )
    synced = TradeExitSyncService(sync_provider).sync(
        db=db_session,
        exit_id=triggered["exit_id"],
    )

    # Realized values come from the broker's confirmed exit fill, never from
    # the monitoring snapshot price that triggered the exit.
    assert synced.filled_avg_price == 104.10
    assert synced.filled_avg_price != 104.0
    assert synced.filled_qty == execution.filled_qty
