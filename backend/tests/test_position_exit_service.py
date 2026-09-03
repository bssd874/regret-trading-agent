from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.app.models.trade_exit import TradeExit
from backend.app.services.alpaca_service import EvaluationPrice
from backend.app.services.position_exit_service import PositionExitService
from backend.app.services.paper_execution_service import paper_execution_service
from backend.tests.test_autonomous_agent_service import _settings
from backend.tests.test_decision_router import _create_routing_chain
from backend.tests.test_outcome_pipeline import NOW, _executed


class FixedMarketData:
    def __init__(self, price):
        self.price = price
        self.calls = []

    def get_evaluation_price(self, symbol):
        self.calls.append(symbol)
        return EvaluationPrice(price=self.price, source="test_snapshot")


def _count(db_session):
    return db_session.scalar(select(func.count()).select_from(TradeExit))


def _open_position(
    db_session,
    candidate_factory,
    *,
    symbol="EXIT",
    stop_loss=98.0,
    target_price=104.0,
    horizon_minutes=60,
    submitted_ago=timedelta(minutes=30),
):
    candidate = candidate_factory(symbol=symbol, entry_price=100.0)
    risk, analysis = _create_routing_chain(
        db_session,
        candidate,
        decision="ACCEPT",
    )
    analysis.stop_loss = stop_loss
    analysis.target_price = target_price
    analysis.horizon_minutes = horizon_minutes
    execution = _executed(
        db_session,
        candidate,
        risk,
        status="filled",
        filled_qty=2.5,
        filled_avg_price=100.0,
    )
    execution.submitted_at = NOW - submitted_ago
    db_session.commit()
    return execution, risk, analysis


def _provider(*, status="accepted"):
    provider = MagicMock()
    provider.sell_long_market_position.return_value = SimpleNamespace(
        id="paper-sell-1",
        status=status,
        filled_qty=None,
        filled_avg_price=None,
    )
    return provider


def test_exit_service_uses_existing_paper_execution_service_by_default():
    assert PositionExitService().execution_provider is paper_execution_service


@pytest.mark.parametrize(
    "price,submitted_ago,expected_reason",
    [
        (104.0, timedelta(minutes=30), "TAKE_PROFIT"),
        (98.0, timedelta(minutes=30), "STOP_LOSS"),
        (100.0, timedelta(minutes=61), "TIME_EXIT"),
    ],
)
def test_deterministic_exit_conditions_trigger_expected_sell(
    db_session,
    candidate_factory,
    price,
    submitted_ago,
    expected_reason,
):
    execution, _, _ = _open_position(
        db_session,
        candidate_factory,
        submitted_ago=submitted_ago,
    )
    provider = _provider()
    service = PositionExitService(
        market_data=FixedMarketData(price),
        execution_provider=provider,
        config=_settings(paper_execution_enabled=True),
        now_provider=lambda: NOW,
    )

    result = service.monitor_execution(db=db_session, execution_id=execution.id)
    trade_exit = db_session.get(TradeExit, result["exit_id"])

    assert result["action"] == "EXIT_TRIGGERED"
    assert trade_exit.reason == expected_reason
    assert trade_exit.trigger_price == price
    assert trade_exit.status == "accepted"
    provider.sell_long_market_position.assert_called_once_with(
        symbol=execution.symbol,
        quantity=2.5,
    )


def test_no_condition_returns_hold_without_persisting_or_selling(
    db_session,
    candidate_factory,
):
    execution, _, _ = _open_position(db_session, candidate_factory)
    market = FixedMarketData(101.0)
    provider = _provider()
    service = PositionExitService(
        market_data=market,
        execution_provider=provider,
        config=_settings(paper_execution_enabled=True),
        now_provider=lambda: NOW,
    )

    result = service.monitor_execution(db=db_session, execution_id=execution.id)

    assert result["action"] == "HOLD"
    assert result["reason"] == "NO_EXIT_CONDITION"
    assert _count(db_session) == 0
    provider.sell_long_market_position.assert_not_called()


def test_original_persisted_thesis_is_copied_to_trade_exit(
    db_session,
    candidate_factory,
):
    execution, risk, analysis = _open_position(
        db_session,
        candidate_factory,
        stop_loss=97.25,
        target_price=106.75,
        horizon_minutes=90,
    )
    provider = _provider()
    service = PositionExitService(
        market_data=FixedMarketData(107.0),
        execution_provider=provider,
        config=_settings(paper_execution_enabled=True),
        now_provider=lambda: NOW,
    )

    result = service.monitor_execution(db=db_session, execution_id=execution.id)
    trade_exit = db_session.get(TradeExit, result["exit_id"])

    assert trade_exit.candidate_id == execution.candidate_id
    assert trade_exit.risk_decision_id == risk.id
    assert trade_exit.target_price == analysis.target_price == 106.75
    assert trade_exit.stop_loss == analysis.stop_loss == 97.25
    assert trade_exit.horizon_minutes == analysis.horizon_minutes == 90


def test_trade_exit_is_persisted_before_sell_contact(
    db_session,
    candidate_factory,
):
    execution, _, _ = _open_position(db_session, candidate_factory)
    provider = _provider()

    def verify_reservation(*, symbol, quantity):
        reserved = db_session.scalar(select(TradeExit))
        assert reserved is not None
        assert reserved.status == "PENDING_SUBMISSION"
        assert reserved.alpaca_order_id is None
        return SimpleNamespace(
            id="paper-sell-reserved",
            status="accepted",
            filled_qty=None,
            filled_avg_price=None,
        )

    provider.sell_long_market_position.side_effect = verify_reservation
    service = PositionExitService(
        market_data=FixedMarketData(105.0),
        execution_provider=provider,
        config=_settings(paper_execution_enabled=True),
        now_provider=lambda: NOW,
    )

    service.monitor_execution(db=db_session, execution_id=execution.id)

    provider.sell_long_market_position.assert_called_once()


def test_repeated_trigger_returns_same_exit_without_second_sell(
    db_session,
    candidate_factory,
):
    execution, _, _ = _open_position(db_session, candidate_factory)
    market = FixedMarketData(105.0)
    provider = _provider()
    service = PositionExitService(
        market_data=market,
        execution_provider=provider,
        config=_settings(paper_execution_enabled=True),
        now_provider=lambda: NOW,
    )

    first = service.monitor_execution(db=db_session, execution_id=execution.id)
    second = service.monitor_execution(db=db_session, execution_id=execution.id)

    assert second["action"] == "EXISTING_EXIT"
    assert second["exit_id"] == first["exit_id"]
    assert second["idempotent_replay"] is True
    assert _count(db_session) == 1
    assert market.calls == [execution.symbol]
    provider.sell_long_market_position.assert_called_once()


def test_one_execution_cannot_have_two_trade_exits(
    db_session,
    candidate_factory,
):
    execution, risk, analysis = _open_position(db_session, candidate_factory)
    values = {
        "executed_trade_id": execution.id,
        "candidate_id": execution.candidate_id,
        "risk_decision_id": risk.id,
        "symbol": execution.symbol,
        "reason": "TIME_EXIT",
        "trigger_price": 100.0,
        "target_price": analysis.target_price,
        "stop_loss": analysis.stop_loss,
        "horizon_minutes": analysis.horizon_minutes,
        "requested_qty": 2.5,
        "status": "PENDING_SUBMISSION",
        "triggered_at": NOW,
    }
    db_session.add(TradeExit(**values))
    db_session.commit()
    db_session.add(TradeExit(**values))

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_ambiguous_submission_failure_is_persisted_and_never_retried(
    db_session,
    candidate_factory,
):
    execution, _, _ = _open_position(db_session, candidate_factory)
    provider = _provider()
    provider.sell_long_market_position.side_effect = TimeoutError(
        "uncertain paper response"
    )
    service = PositionExitService(
        market_data=FixedMarketData(105.0),
        execution_provider=provider,
        config=_settings(paper_execution_enabled=True),
        now_provider=lambda: NOW,
    )

    with pytest.raises(RuntimeError, match="automatic retry is disabled"):
        service.monitor_execution(db=db_session, execution_id=execution.id)

    failed = db_session.scalar(select(TradeExit))
    assert failed.status == "SUBMISSION_FAILED"
    assert failed.alpaca_order_id is None

    replay = service.monitor_execution(db=db_session, execution_id=execution.id)
    assert replay["action"] == "EXISTING_EXIT"
    assert replay["exit_id"] == failed.id
    provider.sell_long_market_position.assert_called_once()


def test_execution_kill_switch_holds_ready_exit_without_reservation(
    db_session,
    candidate_factory,
):
    execution, _, _ = _open_position(db_session, candidate_factory)
    provider = _provider()
    service = PositionExitService(
        market_data=FixedMarketData(105.0),
        execution_provider=provider,
        config=_settings(paper_execution_enabled=False),
        now_provider=lambda: NOW,
    )

    result = service.monitor_execution(db=db_session, execution_id=execution.id)

    assert result["action"] == "EXIT_HELD"
    assert result["reason"] == "PAPER_EXECUTION_DISABLED"
    assert _count(db_session) == 0
    provider.sell_long_market_position.assert_not_called()


def test_exit_condition_module_has_no_llm_or_direct_alpaca_mutations():
    source = (
        Path(__file__).parents[1]
        / "app"
        / "services"
        / "position_exit_service.py"
    ).read_text(encoding="utf-8")
    assert "DecisionAgent" not in source
    assert "CriticAgent" not in source
    for forbidden in (
        "submit_order",
        "MarketOrderRequest",
        "cancel_order",
        "replace_order",
        "close_position",
        "close_all_positions",
    ):
        assert forbidden not in source
