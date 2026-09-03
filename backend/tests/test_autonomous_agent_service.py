import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import func, select

from backend.app.core.config import Settings, settings
from backend.app.models.agent_cycle import AgentCycle
from backend.app.models.candidate_trade import CandidateTrade
from backend.app.models.executed_trade import ExecutedTrade
from backend.app.models.outcome_snapshot import OutcomeSnapshot
from backend.app.models.regret_event import RegretEvent
from backend.app.models.risk_decision import RiskDecision
from backend.app.models.shadow_trade import ShadowTrade
from backend.app.services.alpaca_service import alpaca_service
from backend.app.services.autonomous_agent_service import (
    AGENT_CYCLE_ALREADY_RUNNING,
    AgentCycleAlreadyRunning,
    AutonomousAgent,
)
from backend.app.services.decision_router import decision_router
from backend.app.services.execution_sync_service import ExecutionSyncService
from backend.app.services.outcome_pipeline import OutcomePipeline
from backend.app.services.paper_execution_service import paper_execution_service
from backend.tests.test_decision_pipeline import (
    BrokenAccountProvider,
    BrokenAnalyst,
    BrokenCritic,
    StubAnalyst,
    StubCritic,
    build_pipeline,
)
from backend.tests.test_decision_router import _create_routing_chain
from backend.tests.test_outcome_pipeline import FakeMarketData, NOW, _executed, _shadow


def _settings(**overrides) -> Settings:
    values = {
        "alpaca_api_key": "test-key",
        "alpaca_secret_key": "test-secret",
        "alpaca_paper": True,
        "azure_openai_api_key": "test-key",
        "azure_openai_endpoint": "https://example.invalid/openai/v1",
        "azure_openai_deployment": "test-deployment",
        "nvidia_api_key": "test-key",
        "autonomous_agent_enabled": True,
        "autonomous_cycle_seconds": 300,
        "autonomous_max_candidates_per_cycle": 2,
        "autonomous_stale_cycle_seconds": 900,
        "paper_execution_enabled": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


class FakeScout:
    def __init__(self, symbols):
        self.symbols = list(symbols)
        self.limits = []

    def run(self, db, limit=5):
        self.limits.append(limit)
        candidates = []
        for index, symbol in enumerate(self.symbols):
            candidate = CandidateTrade(
                symbol=symbol,
                side="BUY",
                strategy="momentum",
                entry_price=100.0 + index,
                price_change_pct=3.0,
                volume_ratio=2.0,
                scout_score=5.0 - index / 10,
                source="autonomous_test",
                status="NEW",
            )
            db.add(candidate)
            candidates.append(candidate)
        db.commit()
        for candidate in candidates:
            db.refresh(candidate)
        return candidates


class EmptyOutcomes:
    def __init__(self):
        self.calls = 0

    def evaluate_due(self, *, db):
        self.calls += 1
        return {"evaluated": 0, "not_ready": 0, "errors": 0, "items": []}


class ErrorOutcomes:
    def evaluate_due(self, *, db):
        return {
            "evaluated": 0,
            "not_ready": 0,
            "errors": 1,
            "items": [
                {
                    "status": "ERROR",
                    "source_type": "SHADOW",
                    "source_id": 44,
                    "reason": "Outcome evaluation failed safely",
                }
            ],
        }


class DispatchPipeline:
    def __init__(self, by_symbol):
        self.by_symbol = by_symbol
        self.calls = []

    def run(self, *, db, candidate_id):
        candidate = db.get(CandidateTrade, candidate_id)
        self.calls.append(candidate.symbol)
        return self.by_symbol[candidate.symbol].run(
            db=db,
            candidate_id=candidate_id,
        )


def _count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def _agent(
    *,
    symbols=("ONE",),
    pipeline=None,
    router=None,
    outcomes=None,
    execution_sync=None,
    config=None,
    now_provider=None,
):
    return AutonomousAgent(
        scout=FakeScout(symbols),
        pipeline=pipeline or build_pipeline(),
        router=router or MagicMock(),
        outcomes=outcomes or EmptyOutcomes(),
        **({"execution_sync": execution_sync} if execution_sync else {}),
        config=config or _settings(),
        now_provider=now_provider,
    )


def test_cycle_persists_and_completes_successfully(db_session):
    router = MagicMock()
    cycle = _agent(router=router).run_cycle(db=db_session, trigger="MANUAL")

    persisted = db_session.get(AgentCycle, cycle.id)
    assert persisted is not None
    assert persisted.status == "COMPLETED"
    assert persisted.mode == "OBSERVE"
    assert persisted.trigger == "MANUAL"
    assert persisted.scouted_count == 1
    assert persisted.analyzed_count == 1
    assert persisted.accepted_count == 1
    assert persisted.execution_held_count == 1
    assert persisted.finished_at is not None
    router.route.assert_not_called()


def test_accept_execution_off_is_held_without_mutating_or_shadowing(db_session):
    router = MagicMock()
    cycle = _agent(router=router).run_cycle(db=db_session)
    risk = db_session.scalar(select(RiskDecision))
    summary = json.loads(cycle.summary_json)

    assert risk.decision == "ACCEPT"
    assert summary["candidates"][0]["action"] == "EXECUTION_HELD"
    assert summary["candidates"][0]["reason"] == "PAPER_EXECUTION_DISABLED"
    assert _count(db_session, ShadowTrade) == 0
    assert _count(db_session, ExecutedTrade) == 0
    assert cycle.paper_execution_count == 0
    router.route.assert_not_called()


def test_reject_routes_to_shadow_and_never_uses_paper_execution(
    monkeypatch,
    db_session,
):
    monkeypatch.setattr(
        alpaca_service,
        "get_account",
        MagicMock(return_value=SimpleNamespace(equity="100000")),
    )
    mutate = MagicMock()
    monkeypatch.setattr(
        paper_execution_service,
        "submit_long_market_order",
        mutate,
    )
    pipeline = build_pipeline(
        analyst=StubAnalyst(confidence=0.75),
        critic=StubCritic(adjustment=-0.10),
    )

    cycle = _agent(
        pipeline=pipeline,
        router=decision_router,
    ).run_cycle(db=db_session)

    risk = db_session.scalar(select(RiskDecision))
    assert risk.decision == "REJECT"
    assert cycle.rejected_count == 1
    assert cycle.shadow_created_count == 1
    assert cycle.paper_execution_count == 0
    assert _count(db_session, ShadowTrade) == 1
    assert _count(db_session, ExecutedTrade) == 0
    mutate.assert_not_called()


def test_accept_execution_on_routes_current_cycle_through_existing_router(
    monkeypatch,
    db_session,
):
    monkeypatch.setattr(settings, "paper_execution_enabled", True)
    monkeypatch.setattr(
        alpaca_service,
        "get_account",
        MagicMock(return_value=SimpleNamespace(equity="100000")),
    )
    mutate = MagicMock(
        return_value=SimpleNamespace(
            id="paper-autonomous-1",
            status="accepted",
            filled_qty=None,
            filled_avg_price=None,
        )
    )
    monkeypatch.setattr(
        paper_execution_service,
        "submit_long_market_order",
        mutate,
    )
    provider = MagicMock()
    provider.get_order.return_value = SimpleNamespace(
        status="filled",
        filled_qty="1.5",
        filled_avg_price="101.25",
    )

    cycle = _agent(
        router=decision_router,
        execution_sync=ExecutionSyncService(provider),
        config=_settings(paper_execution_enabled=True),
    ).run_cycle(db=db_session)
    execution = db_session.scalar(select(ExecutedTrade))
    summary = json.loads(cycle.summary_json)

    assert cycle.mode == "AUTONOMOUS_PAPER"
    assert cycle.accepted_count == 1
    assert cycle.paper_execution_count == 1
    assert cycle.execution_held_count == 0
    assert _count(db_session, ExecutedTrade) == 1
    assert _count(db_session, ShadowTrade) == 0
    assert execution.status == "filled"
    assert execution.filled_qty == 1.5
    assert execution.filled_avg_price == 101.25
    assert summary["executions_synced"] == 1
    assert summary["executions_filled"] == 1
    assert summary["candidates"][0]["immediate_sync"]["status"] == "filled"
    mutate.assert_called_once()
    provider.get_order.assert_called_once_with("paper-autonomous-1")


@pytest.mark.parametrize(
    "initial_status",
    ["accepted", "new", "pending", "partially_filled"],
)
def test_non_terminal_execution_is_automatically_synchronized_and_stays_pending(
    db_session,
    candidate_factory,
    initial_status,
):
    candidate = candidate_factory(symbol=f"P{initial_status[:5].upper()}")
    risk, _ = _create_routing_chain(db_session, candidate, decision="ACCEPT")
    execution = _executed(
        db_session,
        candidate,
        risk,
        status=initial_status,
        filled_qty=None,
        filled_avg_price=None,
    )
    provider = MagicMock()
    synchronized_status = (
        "accepted" if initial_status == "pending" else initial_status
    )
    provider.get_order.return_value = SimpleNamespace(
        status=synchronized_status,
        filled_qty="0.5" if initial_status == "partially_filled" else None,
        filled_avg_price=(
            "100.5" if initial_status == "partially_filled" else None
        ),
    )

    cycle = _agent(
        symbols=(),
        execution_sync=ExecutionSyncService(provider),
    ).run_cycle(db=db_session)
    summary = json.loads(cycle.summary_json)

    db_session.refresh(execution)
    assert cycle.status == "COMPLETED"
    assert execution.status == synchronized_status
    if initial_status == "partially_filled":
        assert execution.filled_qty == 0.5
        assert execution.filled_avg_price == 100.5
    else:
        assert execution.filled_qty is None
        assert execution.filled_avg_price is None
    assert summary["executions_synced"] == 1
    assert summary["executions_filled"] == 0
    provider.get_order.assert_called_once_with(execution.alpaca_order_id)


def test_future_cycle_continues_sync_and_persists_later_fill(
    db_session,
    candidate_factory,
):
    candidate = candidate_factory(symbol="LATER")
    risk, _ = _create_routing_chain(db_session, candidate, decision="ACCEPT")
    execution = _executed(
        db_session,
        candidate,
        risk,
        status="pending",
        filled_qty=None,
        filled_avg_price=None,
    )
    provider = MagicMock()
    provider.get_order.side_effect = [
        SimpleNamespace(
            status="accepted",
            filled_qty=None,
            filled_avg_price=None,
        ),
        SimpleNamespace(
            status="filled",
            filled_qty="2.75",
            filled_avg_price="99.40",
        ),
    ]
    agent = _agent(
        symbols=(),
        execution_sync=ExecutionSyncService(provider),
    )

    first = agent.run_cycle(db=db_session)
    second = agent.run_cycle(db=db_session)
    first_summary = json.loads(first.summary_json)
    second_summary = json.loads(second.summary_json)

    db_session.refresh(execution)
    assert first.status == "COMPLETED"
    assert second.status == "COMPLETED"
    assert first_summary["executions_synced"] == 1
    assert first_summary["executions_filled"] == 0
    assert second_summary["executions_synced"] == 1
    assert second_summary["executions_filled"] == 1
    assert execution.status == "filled"
    assert execution.filled_qty == 2.75
    assert execution.filled_avg_price == 99.4
    assert provider.get_order.call_count == 2


@pytest.mark.parametrize(
    "terminal_status",
    ["filled", "CANCELED", "expired", "REJECTED"],
)
def test_terminal_execution_is_not_unnecessarily_synchronized(
    db_session,
    candidate_factory,
    terminal_status,
):
    candidate = candidate_factory(symbol=terminal_status[:6].upper())
    risk, _ = _create_routing_chain(db_session, candidate, decision="ACCEPT")
    _executed(
        db_session,
        candidate,
        risk,
        status=terminal_status,
        filled_qty=1.0 if terminal_status.lower() == "filled" else None,
        filled_avg_price=(
            100.0 if terminal_status.lower() == "filled" else None
        ),
    )
    provider = MagicMock()

    cycle = _agent(
        symbols=(),
        execution_sync=ExecutionSyncService(provider),
    ).run_cycle(db=db_session)
    summary = json.loads(cycle.summary_json)

    assert cycle.status == "COMPLETED"
    assert summary["executions_synced"] == 0
    assert summary["executions_filled"] == 0
    assert summary["execution_reconciliation"]["eligible_count"] == 0
    provider.get_order.assert_not_called()


def test_one_execution_sync_failure_does_not_stop_reconciliation_or_cycle(
    db_session,
    candidate_factory,
):
    failed_candidate = candidate_factory(symbol="SYNCBAD")
    failed_risk, _ = _create_routing_chain(
        db_session,
        failed_candidate,
        decision="ACCEPT",
    )
    failed_execution = _executed(
        db_session,
        failed_candidate,
        failed_risk,
        status="accepted",
        filled_qty=None,
        filled_avg_price=None,
    )
    good_candidate = candidate_factory(symbol="SYNCOK")
    good_risk, _ = _create_routing_chain(
        db_session,
        good_candidate,
        decision="ACCEPT",
    )
    good_execution = _executed(
        db_session,
        good_candidate,
        good_risk,
        status="accepted",
        filled_qty=None,
        filled_avg_price=None,
    )
    provider = MagicMock()

    def get_order(order_id):
        if order_id == failed_execution.alpaca_order_id:
            raise ConnectionError("paper order lookup unavailable")
        return SimpleNamespace(
            status="filled",
            filled_qty="3",
            filled_avg_price="102",
        )

    provider.get_order.side_effect = get_order
    cycle = _agent(
        symbols=(),
        execution_sync=ExecutionSyncService(provider),
    ).run_cycle(db=db_session)
    summary = json.loads(cycle.summary_json)
    errors = json.loads(cycle.errors_json)

    db_session.refresh(failed_execution)
    db_session.refresh(good_execution)
    assert cycle.status == "PARTIAL_FAILED"
    assert failed_execution.status == "accepted"
    assert good_execution.status == "filled"
    assert summary["executions_synced"] == 1
    assert summary["executions_filled"] == 1
    assert provider.get_order.call_count == 2
    assert any(item["code"] == "EXECUTION_SYNC_FAILED" for item in errors)


class FixedNowOutcomes:
    def __init__(self, pipeline):
        self.pipeline = pipeline

    def evaluate_due(self, *, db):
        return self.pipeline.evaluate_due(db=db, now=NOW)


def test_reconciled_fill_is_eligible_for_existing_outcome_engine(
    db_session,
    candidate_factory,
):
    candidate = candidate_factory(symbol="OUTCOME")
    risk, _ = _create_routing_chain(db_session, candidate, decision="ACCEPT")
    execution = _executed(
        db_session,
        candidate,
        risk,
        status="accepted",
        filled_qty=None,
        filled_avg_price=None,
    )
    provider = MagicMock()
    provider.get_order.return_value = SimpleNamespace(
        status="filled",
        filled_qty="10",
        filled_avg_price="100",
    )
    outcomes = FixedNowOutcomes(
        OutcomePipeline(market_data=FakeMarketData({candidate.symbol: 110.0}))
    )

    cycle = _agent(
        symbols=(),
        outcomes=outcomes,
        execution_sync=ExecutionSyncService(provider),
    ).run_cycle(db=db_session)

    db_session.refresh(execution)
    assert cycle.status == "COMPLETED"
    assert execution.status == "filled"
    assert cycle.outcomes_evaluated_count == 1
    assert cycle.regret_events_created_count == 1
    assert _count(db_session, OutcomeSnapshot) == 1
    assert _count(db_session, RegretEvent) == 1


def test_one_candidate_failure_does_not_stop_following_candidate(db_session):
    pipeline = DispatchPipeline(
        {
            "BAD": build_pipeline(analyst=BrokenAnalyst()),
            "GOOD": build_pipeline(),
        }
    )
    router = MagicMock()

    cycle = _agent(
        symbols=("BAD", "GOOD"),
        pipeline=pipeline,
        router=router,
    ).run_cycle(db=db_session)

    statuses = {
        candidate.symbol: candidate.status
        for candidate in db_session.scalars(select(CandidateTrade)).all()
    }
    assert pipeline.calls == ["BAD", "GOOD"]
    assert statuses == {"BAD": "ANALYSIS_FAILED", "GOOD": "ACCEPTED"}
    assert cycle.status == "PARTIAL_FAILED"
    assert cycle.failed_count == 1
    assert cycle.analyzed_count == 1
    assert cycle.execution_held_count == 1
    router.route.assert_not_called()


@pytest.mark.parametrize(
    "pipeline,expected_status",
    [
        (build_pipeline(analyst=BrokenAnalyst()), "ANALYSIS_FAILED"),
        (build_pipeline(critic=BrokenCritic()), "CRITIC_FAILED"),
        (
            build_pipeline(account_provider=BrokenAccountProvider()),
            "RISK_FAILED",
        ),
    ],
)
def test_failed_pipeline_stage_never_routes(
    db_session,
    pipeline,
    expected_status,
):
    router = MagicMock()
    cycle = _agent(pipeline=pipeline, router=router).run_cycle(db=db_session)

    candidate = db_session.scalar(select(CandidateTrade))
    assert candidate.status == expected_status
    assert cycle.status == "FAILED"
    assert cycle.failed_count == 1
    assert _count(db_session, RiskDecision) == 0
    assert _count(db_session, ShadowTrade) == 0
    assert _count(db_session, ExecutedTrade) == 0
    router.route.assert_not_called()


def test_max_candidate_limit_is_enforced(db_session):
    scout = FakeScout(("ONE", "TWO", "THREE"))
    pipeline = DispatchPipeline(
        {
            "ONE": build_pipeline(),
            "TWO": build_pipeline(),
            "THREE": build_pipeline(),
        }
    )
    agent = AutonomousAgent(
        scout=scout,
        pipeline=pipeline,
        router=MagicMock(),
        outcomes=EmptyOutcomes(),
        config=_settings(autonomous_max_candidates_per_cycle=2),
    )

    cycle = agent.run_cycle(db=db_session)

    assert scout.limits == [2]
    assert pipeline.calls == ["ONE", "TWO"]
    assert cycle.scouted_count == 3
    assert cycle.analyzed_count == 2
    third = db_session.scalar(
        select(CandidateTrade).where(CandidateTrade.symbol == "THREE")
    )
    assert third.status == "NEW"


def test_historical_accept_is_never_automatically_executed(
    db_session,
    candidate_factory,
):
    candidate = candidate_factory(symbol="OLD")
    risk, _ = _create_routing_chain(
        db_session,
        candidate,
        decision="ACCEPT",
    )
    router = MagicMock()

    cycle = _agent(
        symbols=(),
        router=router,
        config=_settings(paper_execution_enabled=True),
    ).run_cycle(db=db_session)

    assert cycle.status == "COMPLETED"
    assert cycle.accepted_count == 0
    assert db_session.get(RiskDecision, risk.id).decision == "ACCEPT"
    assert _count(db_session, ExecutedTrade) == 0
    router.route.assert_not_called()


def test_only_a_newly_persisted_risk_can_route(db_session, candidate_factory):
    candidate = candidate_factory(symbol="STALE")
    _create_routing_chain(db_session, candidate, decision="ACCEPT")
    router = MagicMock()
    scout = MagicMock()
    scout.run.return_value = [candidate]
    pipeline = MagicMock()
    agent = AutonomousAgent(
        scout=scout,
        pipeline=pipeline,
        router=router,
        outcomes=EmptyOutcomes(),
        config=_settings(paper_execution_enabled=True),
    )

    cycle = agent.run_cycle(db=db_session)

    assert cycle.status == "FAILED"
    assert cycle.failed_count == 1
    assert _count(db_session, ExecutedTrade) == 0
    router.route.assert_not_called()


def test_due_outcomes_are_evaluated_and_counted(
    db_session,
    candidate_factory,
):
    candidate = candidate_factory(symbol="DUE")
    risk, analysis = _create_routing_chain(
        db_session,
        candidate,
        decision="REJECT",
    )
    _shadow(
        db_session,
        candidate,
        risk,
        analysis,
        due_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    outcomes = OutcomePipeline(
        market_data=FakeMarketData({candidate.symbol: 105.0})
    )

    cycle = _agent(symbols=(), outcomes=outcomes).run_cycle(db=db_session)

    assert cycle.status == "COMPLETED"
    assert cycle.outcomes_evaluated_count == 1
    assert cycle.regret_events_created_count == 1
    assert _count(db_session, OutcomeSnapshot) == 1
    assert _count(db_session, RegretEvent) == 1


def test_outcome_errors_are_recorded_without_killing_cycle(db_session):
    cycle = _agent(symbols=(), outcomes=ErrorOutcomes()).run_cycle(
        db=db_session
    )
    errors = json.loads(cycle.errors_json)

    assert cycle.status == "PARTIAL_FAILED"
    assert len(errors) == 2
    assert all(item["code"] == "OUTCOME_ITEM_FAILED" for item in errors)


def test_recent_running_cycle_rejects_overlap(db_session):
    now = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
    running = AgentCycle(
        trigger="SCHEDULED",
        status="RUNNING",
        mode="OBSERVE",
        started_at=now - timedelta(seconds=30),
        heartbeat_at=now - timedelta(seconds=5),
    )
    db_session.add(running)
    db_session.commit()

    with pytest.raises(
        AgentCycleAlreadyRunning,
        match=AGENT_CYCLE_ALREADY_RUNNING,
    ):
        _agent(symbols=(), now_provider=lambda: now).run_cycle(db=db_session)

    assert _count(db_session, AgentCycle) == 1
    assert running.status == "RUNNING"


def test_stale_running_cycle_is_abandoned_before_new_claim(db_session):
    now = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
    stale = AgentCycle(
        trigger="SCHEDULED",
        status="RUNNING",
        mode="OBSERVE",
        started_at=now - timedelta(hours=1),
        heartbeat_at=now - timedelta(seconds=901),
    )
    db_session.add(stale)
    db_session.commit()

    current = _agent(symbols=(), now_provider=lambda: now).run_cycle(
        db=db_session
    )

    db_session.refresh(stale)
    assert stale.status == "ABANDONED"
    assert stale.finished_at == now.replace(tzinfo=None) or stale.finished_at == now
    assert current.status == "COMPLETED"
    assert _count(db_session, AgentCycle) == 2
