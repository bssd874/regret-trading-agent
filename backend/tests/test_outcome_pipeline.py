from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.app.models.executed_trade import ExecutedTrade
from backend.app.models.outcome_snapshot import OutcomeSnapshot
from backend.app.models.regret_event import RegretEvent
from backend.app.models.shadow_trade import ShadowTrade
from backend.app.services.alpaca_service import EvaluationPrice
from backend.app.services.outcome_pipeline import OutcomePipeline
from backend.tests.test_decision_router import _create_routing_chain


NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


class FakeMarketData:
    def __init__(self, prices=None, failing_symbols=None):
        self.prices = prices or {}
        self.failing_symbols = set(failing_symbols or [])
        self.calls = []

    def get_evaluation_price(self, symbol):
        self.calls.append(symbol)
        if symbol in self.failing_symbols:
            raise ConnectionError("read-only price unavailable")
        return EvaluationPrice(
            price=self.prices.get(symbol, 110.0),
            source="test_snapshot",
        )


def _count(db_session, model):
    return db_session.scalar(select(func.count()).select_from(model))


def _shadow(db_session, candidate, risk, analysis, *, due_at):
    shadow = ShadowTrade(
        candidate_id=candidate.id,
        risk_decision_id=risk.id,
        symbol=candidate.symbol,
        side="BUY",
        hypothetical_entry=analysis.entry_price,
        hypothetical_notional=1000.0,
        stop_loss=analysis.stop_loss,
        target_price=analysis.target_price,
        horizon_minutes=analysis.horizon_minutes,
        status="OPEN",
        opened_at=due_at - timedelta(minutes=analysis.horizon_minutes),
        evaluation_due_at=due_at,
    )
    db_session.add(shadow)
    db_session.commit()
    db_session.refresh(shadow)
    return shadow


def _executed(
    db_session,
    candidate,
    risk,
    *,
    status="filled",
    filled_qty=10.0,
    filled_avg_price=100.0,
):
    execution = ExecutedTrade(
        candidate_id=candidate.id,
        risk_decision_id=risk.id,
        alpaca_order_id=f"paper-{candidate.id}",
        symbol=candidate.symbol,
        side="BUY",
        requested_notional=1000.0,
        status=status,
        filled_qty=filled_qty,
        filled_avg_price=filled_avg_price,
        submitted_at=NOW - timedelta(hours=2),
    )
    db_session.add(execution)
    db_session.commit()
    db_session.refresh(execution)
    return execution


def test_not_due_shadow_cannot_evaluate(db_session, candidate_factory):
    candidate = candidate_factory()
    risk, analysis = _create_routing_chain(
        db_session, candidate, decision="REJECT"
    )
    shadow = _shadow(
        db_session,
        candidate,
        risk,
        analysis,
        due_at=NOW + timedelta(minutes=1),
    )
    market = FakeMarketData()

    result = OutcomePipeline(market_data=market).evaluate_shadow(
        db=db_session,
        shadow_id=shadow.id,
        now=NOW,
    )

    assert result["status"] == "NOT_READY"
    assert shadow.status == "OPEN"
    assert _count(db_session, OutcomeSnapshot) == 0
    assert market.calls == []


def test_due_shadow_evaluates_and_persists_regret(
    db_session,
    candidate_factory,
):
    candidate = candidate_factory()
    risk, analysis = _create_routing_chain(
        db_session, candidate, decision="REJECT"
    )
    shadow = _shadow(
        db_session,
        candidate,
        risk,
        analysis,
        due_at=NOW - timedelta(minutes=1),
    )

    result = OutcomePipeline(
        market_data=FakeMarketData({candidate.symbol: 110.0})
    ).evaluate_shadow(db=db_session, shadow_id=shadow.id, now=NOW)

    outcome = db_session.get(OutcomeSnapshot, result["outcome_id"])
    assert result["status"] == "EVALUATED"
    assert result["classification"] == "MISSED_ALPHA"
    assert outcome.pnl_amount == pytest.approx(100.0)
    assert outcome.price_source == "test_snapshot"
    assert shadow.status == "EVALUATED"
    assert _count(db_session, RegretEvent) == 1


def test_repeated_shadow_evaluation_is_idempotent_and_unique(
    db_session,
    candidate_factory,
):
    candidate = candidate_factory()
    risk, analysis = _create_routing_chain(
        db_session, candidate, decision="REJECT"
    )
    shadow = _shadow(
        db_session,
        candidate,
        risk,
        analysis,
        due_at=NOW - timedelta(minutes=1),
    )
    market = FakeMarketData()
    pipeline = OutcomePipeline(market_data=market)

    first = pipeline.evaluate_shadow(db=db_session, shadow_id=shadow.id, now=NOW)
    second = pipeline.evaluate_shadow(db=db_session, shadow_id=shadow.id, now=NOW)

    assert second["outcome_id"] == first["outcome_id"]
    assert second["regret_event_id"] == first["regret_event_id"]
    assert second["idempotent_replay"] is True
    assert _count(db_session, OutcomeSnapshot) == 1
    assert _count(db_session, RegretEvent) == 1
    assert market.calls == [candidate.symbol]


def test_unfilled_execution_is_not_evaluated(db_session, candidate_factory):
    candidate = candidate_factory()
    risk, _ = _create_routing_chain(db_session, candidate, decision="ACCEPT")
    execution = _executed(
        db_session,
        candidate,
        risk,
        status="accepted",
        filled_qty=None,
        filled_avg_price=None,
    )
    market = FakeMarketData()

    result = OutcomePipeline(market_data=market).evaluate_execution(
        db=db_session,
        execution_id=execution.id,
        now=NOW,
    )

    assert result["status"] == "NOT_READY"
    assert _count(db_session, OutcomeSnapshot) == 0
    assert market.calls == []


@pytest.mark.parametrize(
    "evaluation_price,classification,expected_pnl",
    [
        (110.0, "CORRECT_EXECUTION", 100.0),
        (90.0, "BAD_EXECUTION", -100.0),
    ],
)
def test_filled_execution_can_evaluate(
    db_session,
    candidate_factory,
    evaluation_price,
    classification,
    expected_pnl,
):
    candidate = candidate_factory()
    risk, _ = _create_routing_chain(db_session, candidate, decision="ACCEPT")
    execution = _executed(db_session, candidate, risk)

    result = OutcomePipeline(
        market_data=FakeMarketData({candidate.symbol: evaluation_price})
    ).evaluate_execution(db=db_session, execution_id=execution.id, now=NOW)

    outcome = db_session.get(OutcomeSnapshot, result["outcome_id"])
    assert result["classification"] == classification
    assert outcome.quantity == pytest.approx(10.0)
    assert outcome.notional == pytest.approx(1000.0)
    assert outcome.pnl_amount == pytest.approx(expected_pnl)


def test_evaluation_price_failure_leaves_shadow_open(
    db_session,
    candidate_factory,
):
    candidate = candidate_factory(symbol="FAIL")
    risk, analysis = _create_routing_chain(
        db_session, candidate, decision="REJECT"
    )
    shadow = _shadow(
        db_session,
        candidate,
        risk,
        analysis,
        due_at=NOW - timedelta(minutes=1),
    )

    with pytest.raises(ConnectionError):
        OutcomePipeline(
            market_data=FakeMarketData(failing_symbols={"FAIL"})
        ).evaluate_shadow(db=db_session, shadow_id=shadow.id, now=NOW)

    assert shadow.status == "OPEN"
    assert _count(db_session, OutcomeSnapshot) == 0
    assert _count(db_session, RegretEvent) == 0


def test_evaluate_due_continues_when_one_item_fails(
    db_session,
    candidate_factory,
):
    good = candidate_factory(symbol="GOOD")
    good_risk, good_analysis = _create_routing_chain(
        db_session, good, decision="REJECT"
    )
    _shadow(
        db_session,
        good,
        good_risk,
        good_analysis,
        due_at=NOW - timedelta(minutes=1),
    )
    bad = candidate_factory(symbol="BAD")
    bad_risk, bad_analysis = _create_routing_chain(
        db_session, bad, decision="REJECT"
    )
    _shadow(
        db_session,
        bad,
        bad_risk,
        bad_analysis,
        due_at=NOW - timedelta(minutes=1),
    )

    result = OutcomePipeline(
        market_data=FakeMarketData(
            prices={"GOOD": 105.0},
            failing_symbols={"BAD"},
        )
    ).evaluate_due(db=db_session, now=NOW)

    assert result["evaluated"] == 1
    assert result["errors"] == 1
    assert _count(db_session, OutcomeSnapshot) == 1
    assert _count(db_session, RegretEvent) == 1


def test_outcome_snapshot_source_uniqueness(db_session, candidate_factory):
    candidate = candidate_factory()
    risk, analysis = _create_routing_chain(
        db_session, candidate, decision="REJECT"
    )
    shadow = _shadow(
        db_session,
        candidate,
        risk,
        analysis,
        due_at=NOW - timedelta(minutes=1),
    )
    pipeline = OutcomePipeline(market_data=FakeMarketData())
    result = pipeline.evaluate_shadow(db=db_session, shadow_id=shadow.id, now=NOW)
    original = db_session.get(OutcomeSnapshot, result["outcome_id"])
    duplicate = OutcomeSnapshot(
        source_type=original.source_type,
        source_id=original.source_id,
        candidate_id=original.candidate_id,
        risk_decision_id=original.risk_decision_id,
        symbol=original.symbol,
        decision=original.decision,
        entry_price=original.entry_price,
        evaluation_price=original.evaluation_price,
        quantity=original.quantity,
        notional=original.notional,
        pnl_pct=original.pnl_pct,
        pnl_amount=original.pnl_amount,
        due_at=original.due_at,
        evaluated_at=original.evaluated_at,
        price_source=original.price_source,
    )
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_regret_event_outcome_uniqueness(db_session, candidate_factory):
    candidate = candidate_factory()
    risk, analysis = _create_routing_chain(
        db_session, candidate, decision="REJECT"
    )
    shadow = _shadow(
        db_session,
        candidate,
        risk,
        analysis,
        due_at=NOW - timedelta(minutes=1),
    )
    result = OutcomePipeline(market_data=FakeMarketData()).evaluate_shadow(
        db=db_session,
        shadow_id=shadow.id,
        now=NOW,
    )
    original = db_session.get(RegretEvent, result["regret_event_id"])
    db_session.add(
        RegretEvent(
            outcome_id=original.outcome_id,
            candidate_id=original.candidate_id,
            risk_decision_id=original.risk_decision_id,
            symbol=original.symbol,
            decision=original.decision,
            classification=original.classification,
            pnl_pct=original.pnl_pct,
            pnl_amount=original.pnl_amount,
            decision_value=original.decision_value,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
