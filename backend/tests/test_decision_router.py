from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import func, select

from backend.app.core.config import settings
from backend.app.models.critic_analysis import CriticAnalysis
from backend.app.models.decision_analysis import DecisionAnalysis
from backend.app.models.executed_trade import ExecutedTrade
from backend.app.models.risk_decision import RiskDecision
from backend.app.models.shadow_trade import ShadowTrade
from backend.app.services.alpaca_service import alpaca_service
from backend.app.services.decision_router import decision_router
from backend.app.services.paper_execution_service import paper_execution_service


@pytest.fixture(autouse=True)
def mocked_alpaca(monkeypatch):
    """Keep every DecisionRouter test isolated from the Alpaca API."""
    get_account = MagicMock(
        return_value=SimpleNamespace(
            equity="100000",
            last_equity="100000",
        )
    )
    submit_order = MagicMock(
        return_value=SimpleNamespace(
            id="paper-order-1",
            status="accepted",
            filled_qty=None,
            filled_avg_price=None,
        )
    )

    monkeypatch.setattr(alpaca_service, "get_account", get_account)
    monkeypatch.setattr(
        paper_execution_service,
        "submit_long_market_order",
        submit_order,
    )

    return SimpleNamespace(
        get_account=get_account,
        submit_order=submit_order,
    )


def _count(db_session, model):
    return db_session.scalar(select(func.count()).select_from(model))


def _create_routing_chain(
    db_session,
    candidate,
    *,
    decision,
    update_candidate_status=True,
):
    analysis = DecisionAnalysis(
        candidate_id=candidate.id,
        symbol=candidate.symbol,
        direction="LONG",
        thesis="Test thesis.",
        analyst_confidence=0.82,
        entry_price=candidate.entry_price,
        stop_loss=candidate.entry_price * 0.98,
        target_price=candidate.entry_price * 1.04,
        horizon_minutes=60,
        invalidation="Test invalidation.",
        evidence_summary="Test evidence.",
        provider="test",
        model_name="test-analyst",
    )
    db_session.add(analysis)
    db_session.flush()

    critic = CriticAnalysis(
        candidate_id=candidate.id,
        analysis_id=analysis.id,
        verdict="PASS",
        confidence_adjustment=0.0,
        thesis_consistency=0.9,
        concerns="[]",
        provider="test",
        model_name="test-critic",
    )
    db_session.add(critic)
    db_session.flush()

    risk = RiskDecision(
        candidate_id=candidate.id,
        analysis_id=analysis.id,
        critic_id=critic.id,
        original_confidence=0.82,
        critic_adjustment=0.0,
        adjusted_confidence=0.82,
        reward_risk_ratio=2.0,
        proposed_position_pct=0.02,
        risk_score=0.82,
        decision=decision,
        reasons="Test risk decision.",
    )
    db_session.add(risk)

    if update_candidate_status:
        candidate.status = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"

    db_session.commit()
    db_session.refresh(risk)
    return risk, analysis


def _create_shadow(db_session, candidate, risk, analysis):
    now = datetime.now(timezone.utc)
    shadow = ShadowTrade(
        candidate_id=candidate.id,
        risk_decision_id=risk.id,
        symbol=candidate.symbol,
        side="BUY",
        hypothetical_entry=analysis.entry_price,
        hypothetical_notional=2000.0,
        stop_loss=analysis.stop_loss,
        target_price=analysis.target_price,
        horizon_minutes=analysis.horizon_minutes,
        status="OPEN",
        opened_at=now,
        evaluation_due_at=now + timedelta(minutes=analysis.horizon_minutes),
    )
    db_session.add(shadow)
    db_session.commit()
    db_session.refresh(shadow)
    return shadow


def _create_execution(db_session, candidate, risk):
    execution = ExecutedTrade(
        candidate_id=candidate.id,
        risk_decision_id=risk.id,
        alpaca_order_id="existing-paper-order",
        symbol=candidate.symbol,
        side="BUY",
        requested_notional=2000.0,
        status="accepted",
    )
    db_session.add(execution)
    db_session.commit()
    db_session.refresh(execution)
    return execution


def test_reject_creates_exactly_one_shadow_trade(
    db_session,
    candidate_factory,
):
    candidate = candidate_factory()
    risk, _ = _create_routing_chain(
        db_session,
        candidate,
        decision="REJECT",
    )

    result = decision_router.route(db=db_session, decision_id=risk.id)

    assert result["route"] == "SHADOW"
    assert result["order_submitted"] is False
    assert _count(db_session, ShadowTrade) == 1
    assert _count(db_session, ExecutedTrade) == 0


def test_shadow_values_and_evaluation_deadline_are_persisted(
    db_session,
    candidate_factory,
):
    candidate = candidate_factory(entry_price=80.0)
    risk, analysis = _create_routing_chain(
        db_session,
        candidate,
        decision="REJECT",
    )

    result = decision_router.route(db=db_session, decision_id=risk.id)
    shadow = db_session.get(ShadowTrade, result["shadow_trade_id"])

    assert shadow.hypothetical_entry == analysis.entry_price
    assert shadow.hypothetical_notional == 2000.0
    assert shadow.evaluation_due_at - shadow.opened_at == timedelta(minutes=60)


def test_repeated_reject_returns_same_shadow_without_duplicate(
    db_session,
    candidate_factory,
    mocked_alpaca,
):
    candidate = candidate_factory()
    risk, _ = _create_routing_chain(
        db_session,
        candidate,
        decision="REJECT",
    )

    first = decision_router.route(db=db_session, decision_id=risk.id)
    second = decision_router.route(db=db_session, decision_id=risk.id)

    assert second["shadow_trade_id"] == first["shadow_trade_id"]
    assert second["idempotent_replay"] is True
    assert _count(db_session, ShadowTrade) == 1
    mocked_alpaca.get_account.assert_called_once_with()


def test_reject_never_submits_a_market_order(
    db_session,
    candidate_factory,
    mocked_alpaca,
):
    candidate = candidate_factory()
    risk, _ = _create_routing_chain(
        db_session,
        candidate,
        decision="REJECT",
    )

    decision_router.route(db=db_session, decision_id=risk.id)

    mocked_alpaca.submit_order.assert_not_called()


def test_accept_with_execution_disabled_fails_closed(
    db_session,
    candidate_factory,
    mocked_alpaca,
    monkeypatch,
):
    monkeypatch.setattr(settings, "paper_execution_enabled", False)
    candidate = candidate_factory()
    risk, _ = _create_routing_chain(
        db_session,
        candidate,
        decision="ACCEPT",
    )

    with pytest.raises(RuntimeError, match="kill switch is disabled"):
        decision_router.route(db=db_session, decision_id=risk.id)

    assert _count(db_session, ExecutedTrade) == 0
    mocked_alpaca.get_account.assert_not_called()
    mocked_alpaca.submit_order.assert_not_called()


def test_accept_with_mocked_paper_execution_creates_one_executed_trade(
    db_session,
    candidate_factory,
    mocked_alpaca,
    monkeypatch,
):
    monkeypatch.setattr(settings, "paper_execution_enabled", True)
    monkeypatch.setattr(settings, "execution_position_pct", 0.02)
    candidate = candidate_factory()
    risk, _ = _create_routing_chain(
        db_session,
        candidate,
        decision="ACCEPT",
    )

    result = decision_router.route(db=db_session, decision_id=risk.id)

    assert result["route"] == "PAPER_EXECUTION"
    assert result["alpaca_order_id"] == "paper-order-1"
    assert result["order_submitted"] is True
    assert _count(db_session, ExecutedTrade) == 1
    assert _count(db_session, ShadowTrade) == 0
    mocked_alpaca.submit_order.assert_called_once_with(
        symbol="TEST",
        notional=2000.0,
    )

    execution = db_session.get(ExecutedTrade, result["executed_trade_id"])
    assert execution.alpaca_order_id == "paper-order-1"


def test_accept_uses_more_conservative_configured_allocation(
    db_session,
    candidate_factory,
    mocked_alpaca,
    monkeypatch,
):
    monkeypatch.setattr(settings, "paper_execution_enabled", True)
    monkeypatch.setattr(settings, "execution_position_pct", 0.001)
    candidate = candidate_factory()
    risk, _ = _create_routing_chain(
        db_session,
        candidate,
        decision="ACCEPT",
    )

    result = decision_router.route(db=db_session, decision_id=risk.id)

    assert result["requested_notional"] == 100.0
    mocked_alpaca.submit_order.assert_called_once_with(
        symbol="TEST",
        notional=100.0,
    )


def test_repeated_accept_does_not_submit_a_second_order(
    db_session,
    candidate_factory,
    mocked_alpaca,
    monkeypatch,
):
    monkeypatch.setattr(settings, "paper_execution_enabled", True)
    candidate = candidate_factory()
    risk, _ = _create_routing_chain(
        db_session,
        candidate,
        decision="ACCEPT",
    )

    first = decision_router.route(db=db_session, decision_id=risk.id)
    second = decision_router.route(db=db_session, decision_id=risk.id)

    assert second["executed_trade_id"] == first["executed_trade_id"]
    assert second["idempotent_replay"] is True
    assert _count(db_session, ExecutedTrade) == 1
    mocked_alpaca.submit_order.assert_called_once()


def test_submission_failure_is_persisted_and_never_retried(
    db_session,
    candidate_factory,
    mocked_alpaca,
    monkeypatch,
):
    monkeypatch.setattr(settings, "paper_execution_enabled", True)
    mocked_alpaca.submit_order.side_effect = TimeoutError("uncertain response")
    candidate = candidate_factory()
    risk, _ = _create_routing_chain(
        db_session,
        candidate,
        decision="ACCEPT",
    )

    with pytest.raises(RuntimeError, match="automatic retry is disabled"):
        decision_router.route(db=db_session, decision_id=risk.id)

    execution = db_session.scalar(select(ExecutedTrade))
    assert execution.status == "SUBMISSION_FAILED"
    assert execution.alpaca_order_id is None

    replay = decision_router.route(db=db_session, decision_id=risk.id)
    assert replay["executed_trade_id"] == execution.id
    assert replay["execution_status"] == "SUBMISSION_FAILED"
    assert replay["order_submitted"] is False
    mocked_alpaca.submit_order.assert_called_once()


def test_unknown_decision_cannot_route(db_session, mocked_alpaca):
    with pytest.raises(LookupError, match="not found"):
        decision_router.route(db=db_session, decision_id=999)

    mocked_alpaca.get_account.assert_not_called()
    mocked_alpaca.submit_order.assert_not_called()


def _assert_failed_candidate_cannot_execute(
    db_session,
    candidate_factory,
    mocked_alpaca,
    failed_status,
):
    candidate = candidate_factory(status=failed_status)
    risk, _ = _create_routing_chain(
        db_session,
        candidate,
        decision="ACCEPT",
        update_candidate_status=False,
    )

    with pytest.raises(RuntimeError, match="status ACCEPTED"):
        decision_router.route(db=db_session, decision_id=risk.id)

    assert _count(db_session, ExecutedTrade) == 0
    assert _count(db_session, ShadowTrade) == 0
    mocked_alpaca.get_account.assert_not_called()
    mocked_alpaca.submit_order.assert_not_called()


def test_analysis_failed_candidate_cannot_execute(
    db_session,
    candidate_factory,
    mocked_alpaca,
):
    _assert_failed_candidate_cannot_execute(
        db_session,
        candidate_factory,
        mocked_alpaca,
        "ANALYSIS_FAILED",
    )


def test_critic_failed_candidate_cannot_execute(
    db_session,
    candidate_factory,
    mocked_alpaca,
):
    _assert_failed_candidate_cannot_execute(
        db_session,
        candidate_factory,
        mocked_alpaca,
        "CRITIC_FAILED",
    )


def test_risk_failed_candidate_cannot_execute(
    db_session,
    candidate_factory,
    mocked_alpaca,
):
    _assert_failed_candidate_cannot_execute(
        db_session,
        candidate_factory,
        mocked_alpaca,
        "RISK_FAILED",
    )


def test_accept_with_existing_shadow_trade_fails_closed(
    db_session,
    candidate_factory,
    mocked_alpaca,
):
    candidate = candidate_factory()
    risk, analysis = _create_routing_chain(
        db_session,
        candidate,
        decision="ACCEPT",
    )
    _create_shadow(db_session, candidate, risk, analysis)

    with pytest.raises(RuntimeError, match="already has ShadowTrade"):
        decision_router.route(db=db_session, decision_id=risk.id)

    assert _count(db_session, ExecutedTrade) == 0
    mocked_alpaca.get_account.assert_not_called()
    mocked_alpaca.submit_order.assert_not_called()


def test_reject_with_existing_executed_trade_fails_closed(
    db_session,
    candidate_factory,
    mocked_alpaca,
):
    candidate = candidate_factory()
    risk, _ = _create_routing_chain(
        db_session,
        candidate,
        decision="REJECT",
    )
    _create_execution(db_session, candidate, risk)

    with pytest.raises(RuntimeError, match="already has execution record"):
        decision_router.route(db=db_session, decision_id=risk.id)

    assert _count(db_session, ShadowTrade) == 0
    mocked_alpaca.get_account.assert_not_called()
    mocked_alpaca.submit_order.assert_not_called()


def test_contradictory_routing_artifacts_fail_closed(
    db_session,
    candidate_factory,
    mocked_alpaca,
):
    candidate = candidate_factory()
    risk, analysis = _create_routing_chain(
        db_session,
        candidate,
        decision="ACCEPT",
    )
    _create_shadow(db_session, candidate, risk, analysis)
    _create_execution(db_session, candidate, risk)

    with pytest.raises(RuntimeError, match="both an ExecutedTrade and ShadowTrade"):
        decision_router.route(db=db_session, decision_id=risk.id)

    mocked_alpaca.get_account.assert_not_called()
    mocked_alpaca.submit_order.assert_not_called()
