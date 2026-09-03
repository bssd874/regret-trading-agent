import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import func, select

from backend.app.models.outcome_snapshot import OutcomeSnapshot
from backend.app.models.regret_event import RegretEvent
from backend.app.models.trade_exit import TradeExit
from backend.app.services.autonomous_agent_service import AutonomousAgent
from backend.app.services.outcome_pipeline import OutcomePipeline
from backend.app.services.position_exit_service import PositionExitService
from backend.app.services.trade_exit_sync_service import TradeExitSyncService
from backend.tests.test_autonomous_agent_service import (
    EmptyOutcomes,
    FixedNowOutcomes,
    HoldExitManager,
    _agent,
    _settings,
)
from backend.tests.test_outcome_pipeline import FakeMarketData, NOW
from backend.tests.test_position_exit_service import (
    FixedMarketData,
    _open_position,
)


def _count(db_session, model):
    return db_session.scalar(select(func.count()).select_from(model))


def test_new_entries_disabled_skips_scout_and_decision_path(db_session):
    scout = MagicMock()
    pipeline = MagicMock()
    router = MagicMock()
    agent = AutonomousAgent(
        scout=scout,
        pipeline=pipeline,
        router=router,
        outcomes=EmptyOutcomes(),
        exit_manager=HoldExitManager(),
        config=_settings(autonomous_new_entries_enabled=False),
        now_provider=lambda: NOW,
    )

    cycle = agent.run_cycle(db=db_session)
    summary = json.loads(cycle.summary_json)

    assert cycle.status == "COMPLETED"
    assert summary["new_entries_enabled_at_start"] is False
    assert summary["scout"]["status"] == "SKIPPED"
    assert summary["scout"]["reason"] == "AUTONOMOUS_NEW_ENTRIES_DISABLED"
    scout.run.assert_not_called()
    pipeline.run.assert_not_called()
    router.route.assert_not_called()


def test_open_position_is_monitored_when_new_entries_are_disabled(
    db_session,
    candidate_factory,
):
    execution, _, _ = _open_position(db_session, candidate_factory)
    scout = MagicMock()
    exit_manager = MagicMock()
    exit_manager.monitor_execution.return_value = {
        "action": "HOLD",
        "execution_id": execution.id,
        "reason": "NO_EXIT_CONDITION",
    }
    agent = AutonomousAgent(
        scout=scout,
        pipeline=MagicMock(),
        router=MagicMock(),
        outcomes=EmptyOutcomes(),
        exit_manager=exit_manager,
        config=_settings(autonomous_new_entries_enabled=False),
        now_provider=lambda: NOW,
    )

    cycle = agent.run_cycle(db=db_session)
    summary = json.loads(cycle.summary_json)

    assert cycle.status == "COMPLETED"
    assert summary["open_positions_checked"] == 1
    assert summary["exit_holds"] == 1
    exit_manager.monitor_execution.assert_called_once_with(
        db=db_session,
        execution_id=execution.id,
    )
    scout.run.assert_not_called()


def test_new_exit_receives_immediate_sync_and_realized_outcome(
    db_session,
    candidate_factory,
):
    execution, _, _ = _open_position(db_session, candidate_factory)
    sell_provider = MagicMock()
    sell_provider.sell_long_market_position.return_value = SimpleNamespace(
        id="paper-sell-immediate",
        status="accepted",
        filled_qty=None,
        filled_avg_price=None,
    )
    lookup_provider = MagicMock()
    lookup_provider.get_order.return_value = SimpleNamespace(
        status="filled",
        filled_qty="2.5",
        filled_avg_price="105.0",
        filled_at=NOW,
    )
    exit_manager = PositionExitService(
        market_data=FixedMarketData(105.0),
        execution_provider=sell_provider,
        config=_settings(paper_execution_enabled=True),
        now_provider=lambda: NOW,
    )
    outcomes = FixedNowOutcomes(OutcomePipeline(market_data=FakeMarketData()))

    cycle = _agent(
        symbols=(),
        outcomes=outcomes,
        exit_manager=exit_manager,
        exit_sync=TradeExitSyncService(
            lookup_provider,
            now_provider=lambda: NOW,
        ),
        config=_settings(
            paper_execution_enabled=True,
            autonomous_new_entries_enabled=False,
        ),
        now_provider=lambda: NOW,
    ).run_cycle(db=db_session)
    summary = json.loads(cycle.summary_json)
    trade_exit = db_session.scalar(select(TradeExit))
    outcome = db_session.scalar(select(OutcomeSnapshot))
    event = db_session.scalar(select(RegretEvent))

    assert cycle.status == "COMPLETED"
    assert summary["exits_triggered"] == 1
    assert summary["exits_synced"] == 1
    assert summary["exits_filled"] == 1
    assert trade_exit.status == "filled"
    assert trade_exit.filled_qty == 2.5
    assert trade_exit.filled_avg_price == 105.0
    assert outcome.entry_price == 100.0
    assert outcome.evaluation_price == 105.0
    assert outcome.quantity == 2.5
    assert outcome.pnl_amount == pytest.approx(12.5)
    assert outcome.price_source == "alpaca_exit_fill"
    assert event.classification == "CORRECT_EXECUTION"
    assert event.decision_value == pytest.approx(12.5)
    sell_provider.sell_long_market_position.assert_called_once()
    lookup_provider.get_order.assert_called_once_with("paper-sell-immediate")


def test_future_cycle_reconciles_same_pending_exit_to_fill(
    db_session,
    candidate_factory,
):
    _open_position(db_session, candidate_factory)
    sell_provider = MagicMock()
    sell_provider.sell_long_market_position.return_value = SimpleNamespace(
        id="paper-sell-later",
        status="accepted",
        filled_qty=None,
        filled_avg_price=None,
    )
    lookup_provider = MagicMock()
    lookup_provider.get_order.side_effect = [
        SimpleNamespace(
            status="accepted",
            filled_qty=None,
            filled_avg_price=None,
        ),
        SimpleNamespace(
            status="filled",
            filled_qty="2.5",
            filled_avg_price="105.5",
            filled_at=NOW + timedelta(minutes=1),
        ),
    ]
    agent = _agent(
        symbols=(),
        outcomes=EmptyOutcomes(),
        exit_manager=PositionExitService(
            market_data=FixedMarketData(105.0),
            execution_provider=sell_provider,
            config=_settings(paper_execution_enabled=True),
            now_provider=lambda: NOW,
        ),
        exit_sync=TradeExitSyncService(lookup_provider),
        config=_settings(
            paper_execution_enabled=True,
            autonomous_new_entries_enabled=False,
        ),
        now_provider=lambda: NOW,
    )

    first = agent.run_cycle(db=db_session)
    second = agent.run_cycle(db=db_session)
    first_summary = json.loads(first.summary_json)
    second_summary = json.loads(second.summary_json)
    trade_exit = db_session.scalar(select(TradeExit))

    assert first_summary["exits_synced"] == 1
    assert first_summary["exits_filled"] == 0
    assert second_summary["exits_synced"] == 1
    assert second_summary["exits_filled"] == 1
    assert trade_exit.status == "filled"
    assert trade_exit.filled_qty == 2.5
    assert trade_exit.filled_avg_price == 105.5
    sell_provider.sell_long_market_position.assert_called_once()
    assert lookup_provider.get_order.call_count == 2


@pytest.mark.parametrize("terminal_status", ["filled", "canceled", "expired", "rejected"])
def test_terminal_exit_is_not_repolled(
    db_session,
    candidate_factory,
    terminal_status,
):
    execution, risk, analysis = _open_position(db_session, candidate_factory)
    trade_exit = TradeExit(
        executed_trade_id=execution.id,
        candidate_id=execution.candidate_id,
        risk_decision_id=risk.id,
        symbol=execution.symbol,
        reason="TIME_EXIT",
        trigger_price=101.0,
        target_price=analysis.target_price,
        stop_loss=analysis.stop_loss,
        horizon_minutes=analysis.horizon_minutes,
        requested_qty=2.5,
        alpaca_order_id=f"terminal-{terminal_status}",
        status=terminal_status,
        filled_qty=2.5 if terminal_status == "filled" else None,
        filled_avg_price=101.0 if terminal_status == "filled" else None,
        triggered_at=NOW,
        submitted_at=NOW,
        closed_at=NOW if terminal_status == "filled" else None,
    )
    db_session.add(trade_exit)
    db_session.commit()
    provider = MagicMock()

    cycle = _agent(
        symbols=(),
        outcomes=EmptyOutcomes(),
        exit_sync=TradeExitSyncService(provider),
        config=_settings(autonomous_new_entries_enabled=False),
        now_provider=lambda: NOW,
    ).run_cycle(db=db_session)
    summary = json.loads(cycle.summary_json)

    assert summary["exit_reconciliation"]["eligible_count"] == 0
    assert summary["exits_synced"] == 0
    provider.get_order.assert_not_called()


def test_one_exit_sync_failure_does_not_stop_other_exit_or_cycle(
    db_session,
    candidate_factory,
):
    exits = []
    for symbol in ("EXITBAD", "EXITOK"):
        execution, risk, analysis = _open_position(
            db_session,
            candidate_factory,
            symbol=symbol,
        )
        trade_exit = TradeExit(
            executed_trade_id=execution.id,
            candidate_id=execution.candidate_id,
            risk_decision_id=risk.id,
            symbol=symbol,
            reason="TIME_EXIT",
            trigger_price=101.0,
            target_price=analysis.target_price,
            stop_loss=analysis.stop_loss,
            horizon_minutes=analysis.horizon_minutes,
            requested_qty=2.5,
            alpaca_order_id=f"paper-{symbol}",
            status="accepted",
            triggered_at=NOW,
            submitted_at=NOW,
        )
        db_session.add(trade_exit)
        db_session.commit()
        db_session.refresh(trade_exit)
        exits.append(trade_exit)

    provider = MagicMock()

    def get_order(order_id):
        if order_id == "paper-EXITBAD":
            raise ConnectionError("read-only order lookup failed")
        return SimpleNamespace(
            status="filled",
            filled_qty="2.5",
            filled_avg_price="102.0",
            filled_at=NOW,
        )

    provider.get_order.side_effect = get_order
    cycle = _agent(
        symbols=(),
        outcomes=EmptyOutcomes(),
        exit_sync=TradeExitSyncService(provider),
        config=_settings(autonomous_new_entries_enabled=False),
        now_provider=lambda: NOW,
    ).run_cycle(db=db_session)
    summary = json.loads(cycle.summary_json)
    errors = json.loads(cycle.errors_json)

    db_session.refresh(exits[0])
    db_session.refresh(exits[1])
    assert cycle.status == "PARTIAL_FAILED"
    assert exits[0].status == "accepted"
    assert exits[1].status == "filled"
    assert summary["exits_synced"] == 1
    assert summary["exits_filled"] == 1
    assert provider.get_order.call_count == 2
    assert any(item["code"] == "EXIT_SYNC_FAILED" for item in errors)
