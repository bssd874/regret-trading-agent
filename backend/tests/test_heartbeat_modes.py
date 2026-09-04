"""Lifecycle-aware, cost-safe heartbeat: mode selection and provider spend.

The central claim under test is that a frequent heartbeat costs nothing while
no new entry is authorised: no market scout, no analyst, no critic, no new
candidate or risk decision — while every existing-position safety path keeps
working. All broker, market-data and provider interactions are deterministic
doubles; nothing here reaches a network.
"""

import json
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app.api import internal_routes
from backend.app.core.config import settings
from backend.app.db.database import get_db
from backend.app.main import app
from backend.app.models.agent_cycle import AgentCycle
from backend.app.models.candidate_trade import CandidateTrade
from backend.app.models.executed_trade import ExecutedTrade
from backend.app.models.outcome_snapshot import OutcomeSnapshot
from backend.app.models.risk_decision import RiskDecision
from backend.app.models.shadow_trade import ShadowTrade
from backend.app.models.trade_exit import TradeExit
from backend.app.services.alpaca_service import alpaca_service
from backend.app.services.autonomous_agent_service import AutonomousAgent
from backend.app.services.decision_router import decision_router
from backend.app.services.lifecycle_workload_service import (
    has_lifecycle_work,
    lifecycle_workload,
)
from backend.app.services.paper_execution_service import paper_execution_service
from backend.app.services.runtime_control_service import (
    runtime_control_service,
)
from backend.tests.runtime_control_helpers import NOW, seed_control
from backend.tests.test_autonomous_agent_service import (
    EmptyOutcomes,
    HoldExitManager,
    _settings,
)
from backend.tests.test_decision_router import _create_routing_chain
from backend.tests.test_outcome_pipeline import NOW as MARKET_NOW, _executed
from backend.tests.test_position_exit_service import (
    FixedMarketData,
    _open_position,
    _provider,
)


SCHEDULER_SECRET = "TEST_SCHEDULER_TRIGGER_SECRET"
HEADERS = {"X-Regret-Scheduler-Secret": SCHEDULER_SECRET}
ENDPOINT = "/api/internal/scheduled-cycle"


@contextmanager
def _client(db_session):
    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


def _configured(monkeypatch):
    monkeypatch.setattr(settings, "scheduler_trigger_secret", SCHEDULER_SECRET)
    monkeypatch.setattr(settings, "paper_execution_enabled", True)
    for name in ("GITHUB_ACTIONS", "CI", "VERCEL", "REGRET_REQUIRE_DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)


class SpyScout:
    """Records every scout invocation. Contacts no market data."""

    def __init__(self, candidates=()):
        self.calls = 0
        self.candidates = list(candidates)

    def run(self, db, limit=5):
        self.calls += 1
        return self.candidates[:limit]


class SpyPipeline:
    """Records analyst/critic pipeline invocations."""

    def __init__(self):
        self.calls = 0

    def run(self, *, db, candidate_id):
        self.calls += 1
        raise AssertionError(
            "the pipeline must not run while new entries are disarmed"
        )


@pytest.fixture
def spies(monkeypatch):
    """Install an agent whose expensive collaborators are all observable."""
    monkeypatch.setattr(settings, "paper_execution_enabled", True)
    monkeypatch.setattr(
        alpaca_service,
        "get_account",
        MagicMock(return_value=SimpleNamespace(equity="100000")),
    )
    submit = MagicMock(
        return_value=SimpleNamespace(
            id="paper-mode-1",
            status="accepted",
            filled_qty=None,
            filled_avg_price=None,
        )
    )
    monkeypatch.setattr(
        paper_execution_service, "submit_long_market_order", submit
    )

    scout = SpyScout()
    pipeline = SpyPipeline()
    market_data = FixedMarketData(100.0)

    agent = AutonomousAgent(
        scout=scout,
        pipeline=pipeline,
        router=decision_router,
        outcomes=EmptyOutcomes(),
        exit_manager=HoldExitManager(),
        config=_settings(
            paper_execution_enabled=True,
            autonomous_new_entries_enabled=True,
        ),
    )
    monkeypatch.setattr(internal_routes, "autonomous_agent", agent)
    return SimpleNamespace(
        scout=scout,
        pipeline=pipeline,
        submit=submit,
        market_data=market_data,
        agent=agent,
    )


def _pending_buy(db, candidate_factory, *, symbol="HBPEND"):
    candidate = candidate_factory(symbol=symbol, entry_price=100.0)
    risk, _ = _create_routing_chain(db, candidate, decision="ACCEPT")
    execution = _executed(db, candidate, risk, status="accepted")
    db.commit()
    return execution


def _armed(db, **overrides):
    values = {
        "state": "ARMED",
        "new_entries_armed": True,
        "armed_at": NOW,
        "armed_until": NOW + timedelta(days=3650),
        "max_new_executions": 1,
        "executions_used": 0,
    }
    values.update(overrides)
    return seed_control(db, **values)


def _post(client):
    return client.post(ENDPOINT, headers=HEADERS)


# ===============================================================
# 1-5 mode selection
# ===============================================================
def test_disarmed_heartbeat_selects_lifecycle_only(
    monkeypatch, db_session, candidate_factory, spies
):
    _configured(monkeypatch)
    seed_control(db_session, state="DISARMED")
    _pending_buy(db_session, candidate_factory)

    with _client(db_session) as client:
        body = _post(client).json()

    assert body["mode"] == "LIFECYCLE_ONLY"


def test_expired_arm_selects_lifecycle_only(
    monkeypatch, db_session, candidate_factory, spies
):
    _configured(monkeypatch)
    _armed(
        db_session,
        armed_at=NOW - timedelta(hours=2),
        armed_until=NOW - timedelta(hours=1),
    )
    _pending_buy(db_session, candidate_factory)

    with _client(db_session) as client:
        body = _post(client).json()

    assert body["mode"] == "LIFECYCLE_ONLY"
    assert runtime_control_service.is_entry_armed(db_session) is False


def test_exhausted_budget_selects_lifecycle_only(
    monkeypatch, db_session, candidate_factory, spies
):
    _configured(monkeypatch)
    _armed(db_session, executions_used=1, max_new_executions=1)
    _pending_buy(db_session, candidate_factory)

    with _client(db_session) as client:
        body = _post(client).json()

    assert body["mode"] == "LIFECYCLE_ONLY"


def test_effectively_armed_heartbeat_selects_full_cycle(
    monkeypatch, db_session, spies
):
    _configured(monkeypatch)
    _armed(db_session)

    with _client(db_session) as client:
        body = _post(client).json()

    assert body["mode"] == "FULL_CYCLE"
    # FULL_CYCLE genuinely reaches the expensive half.
    assert spies.scout.calls == 1


def test_immediate_arm_session_runs_a_full_cycle(monkeypatch, db_session):
    """A claimed ARM session must still scout, analyse and critique."""
    from backend.scripts.run_autonomous_cycle_once import run_cycle_once

    monkeypatch.setattr(settings, "paper_execution_enabled", True)
    _armed(db_session)
    agent = MagicMock()
    agent.run_cycle.return_value = SimpleNamespace(id=5, status="COMPLETED")

    result = run_cycle_once(
        config=_settings(
            autonomous_agent_enabled=True, paper_execution_enabled=True
        ),
        agent=agent,
        session_factory=MagicMock(return_value=db_session),
        engine_bind=MagicMock(),
    )

    assert result == 0
    # An effective arm keeps ARM & START on the full pipeline.
    assert agent.run_cycle.call_args.kwargs["lifecycle_only"] is False


# ===============================================================
# 6-11 cost safety: LIFECYCLE_ONLY spends nothing on discovery
# ===============================================================
def test_lifecycle_only_never_touches_scout_analyst_or_critic(
    monkeypatch, db_session, candidate_factory, spies
):
    _configured(monkeypatch)
    seed_control(db_session, state="DISARMED")
    _pending_buy(db_session, candidate_factory)

    candidates_before = db_session.scalar(
        select(func.count()).select_from(CandidateTrade)
    )
    risks_before = db_session.scalar(
        select(func.count()).select_from(RiskDecision)
    )

    with _client(db_session) as client:
        response = _post(client)

    assert response.status_code == 200
    # 6, 7, 8 — the expensive collaborators were never called. SpyPipeline
    # raises if invoked, so a pipeline call could not pass silently.
    assert spies.scout.calls == 0
    assert spies.pipeline.calls == 0
    # 9, 10 — no new candidate and no new risk decision.
    assert db_session.scalar(
        select(func.count()).select_from(CandidateTrade)
    ) == candidates_before
    assert db_session.scalar(
        select(func.count()).select_from(RiskDecision)
    ) == risks_before
    # 11 — no BUY.
    spies.submit.assert_not_called()


def test_lifecycle_only_creates_no_new_shadow_trade(
    monkeypatch, db_session, candidate_factory, spies
):
    _configured(monkeypatch)
    seed_control(db_session, state="DISARMED")
    _pending_buy(db_session, candidate_factory)
    before = db_session.scalar(select(func.count()).select_from(ShadowTrade))

    with _client(db_session) as client:
        _post(client)

    assert db_session.scalar(
        select(func.count()).select_from(ShadowTrade)
    ) == before


# ===============================================================
# 12-13 idle fast path
# ===============================================================
def test_idle_disarmed_heartbeat_does_no_work_at_all(
    monkeypatch, db_session, spies
):
    _configured(monkeypatch)
    seed_control(db_session, state="DISARMED")

    with _client(db_session) as client:
        response = _post(client)

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "IDLE"
    assert body["cycle_id"] is None
    assert body["workload"]["has_work"] is False
    # No providers, no market scanning, and not even an AgentCycle row.
    assert spies.scout.calls == 0
    assert spies.pipeline.calls == 0
    spies.submit.assert_not_called()
    assert db_session.scalar(select(func.count()).select_from(AgentCycle)) == 0


def test_idle_detection_matches_the_pipeline_predicates(
    db_session, candidate_factory
):
    """Every kind of outstanding work must defeat the idle fast path."""
    assert has_lifecycle_work(db_session) is False

    execution = _pending_buy(db_session, candidate_factory, symbol="WORK")
    workload = lifecycle_workload(db_session)
    assert workload["pending_executions"] == 1
    assert workload["has_work"] is True

    # A filled entry with no exit is an open position, and is also unevaluated.
    execution.status = "filled"
    execution.filled_qty = 2.0
    execution.filled_avg_price = 100.0
    db_session.commit()
    workload = lifecycle_workload(db_session)
    assert workload["pending_executions"] == 0
    assert workload["open_positions"] == 1
    assert workload["unevaluated_executions"] == 1
    assert workload["has_work"] is True


def test_a_due_shadow_trade_defeats_the_idle_path(
    monkeypatch, db_session, candidate_factory, spies
):
    from backend.tests.test_outcome_pipeline import _shadow

    _configured(monkeypatch)
    seed_control(db_session, state="DISARMED")
    candidate = candidate_factory(symbol="SHDUE")
    risk, analysis = _create_routing_chain(
        db_session, candidate, decision="REJECT"
    )
    _shadow(
        db_session,
        candidate,
        risk,
        analysis,
        due_at=MARKET_NOW - timedelta(hours=1),
    )
    db_session.commit()

    assert lifecycle_workload(db_session)["due_shadow_trades"] == 1

    with _client(db_session) as client:
        body = _post(client).json()

    assert body["status"] != "IDLE"
    assert body["mode"] == "LIFECYCLE_ONLY"
    # Still no discovery spend.
    assert spies.scout.calls == 0


# ===============================================================
# 14-22 exit safety survives lifecycle-only
# ===============================================================
def _exit_agent(monkeypatch, *, price, provider):
    from backend.app.services.position_exit_service import PositionExitService

    exit_service = PositionExitService(
        market_data=FixedMarketData(price),
        execution_provider=provider,
        config=settings,
        now_provider=lambda: MARKET_NOW,
    )
    scout = SpyScout()
    agent = AutonomousAgent(
        scout=scout,
        pipeline=SpyPipeline(),
        router=decision_router,
        outcomes=EmptyOutcomes(),
        exit_manager=exit_service,
        config=_settings(
            paper_execution_enabled=True,
            autonomous_new_entries_enabled=True,
        ),
    )
    monkeypatch.setattr(internal_routes, "autonomous_agent", agent)
    return scout


@pytest.mark.parametrize(
    "price,submitted_ago,expected_reason",
    [
        (104.0, timedelta(minutes=30), "TAKE_PROFIT"),
        (98.0, timedelta(minutes=30), "STOP_LOSS"),
        (100.0, timedelta(minutes=61), "TIME_EXIT"),
    ],
)
def test_lifecycle_only_still_exits_an_open_position(
    monkeypatch,
    db_session,
    candidate_factory,
    price,
    submitted_ago,
    expected_reason,
):
    _configured(monkeypatch)
    seed_control(db_session, state="DISARMED")
    execution, _, _ = _open_position(
        db_session,
        candidate_factory,
        symbol=f"LO{expected_reason[:3]}",
        submitted_ago=submitted_ago,
    )
    provider = _provider()
    scout = _exit_agent(monkeypatch, price=price, provider=provider)

    with _client(db_session) as client:
        body = _post(client).json()

    assert body["mode"] == "LIFECYCLE_ONLY"
    trade_exit = db_session.scalar(select(TradeExit))
    assert trade_exit is not None
    assert trade_exit.reason == expected_reason
    assert trade_exit.executed_trade_id == execution.id
    provider.sell_long_market_position.assert_called_once()
    # The exit cost no discovery spend.
    assert scout.calls == 0


def test_lifecycle_only_reconciles_a_pending_buy(
    monkeypatch, db_session, candidate_factory
):
    _configured(monkeypatch)
    seed_control(db_session, state="DISARMED")
    execution = _pending_buy(db_session, candidate_factory, symbol="RECON")

    sync_provider = MagicMock()
    sync_provider.get_order.return_value = SimpleNamespace(
        status="filled", filled_qty="2.0", filled_avg_price="101.0"
    )
    from backend.app.services.execution_sync_service import ExecutionSyncService

    scout = SpyScout()
    agent = AutonomousAgent(
        scout=scout,
        pipeline=SpyPipeline(),
        router=decision_router,
        outcomes=EmptyOutcomes(),
        execution_sync=ExecutionSyncService(sync_provider),
        exit_manager=HoldExitManager(),
        config=_settings(paper_execution_enabled=True),
    )
    monkeypatch.setattr(internal_routes, "autonomous_agent", agent)

    with _client(db_session) as client:
        body = _post(client).json()

    db_session.refresh(execution)
    assert body["mode"] == "LIFECYCLE_ONLY"
    assert execution.status == "filled"
    assert execution.filled_qty == 2.0
    assert scout.calls == 0


def test_lifecycle_only_exit_remains_idempotent(
    monkeypatch, db_session, candidate_factory
):
    _configured(monkeypatch)
    seed_control(db_session, state="DISARMED")
    _open_position(db_session, candidate_factory, symbol="IDEM")
    provider = _provider()
    _exit_agent(monkeypatch, price=104.0, provider=provider)

    with _client(db_session) as client:
        _post(client)
        _post(client)

    assert db_session.scalar(select(func.count()).select_from(TradeExit)) == 1
    provider.sell_long_market_position.assert_called_once()


def test_lifecycle_only_evaluates_an_existing_shadow_trade(
    monkeypatch, db_session, candidate_factory
):
    """An existing ShadowTrade still reaches its counterfactual outcome."""
    from backend.app.services.outcome_pipeline import OutcomePipeline
    from backend.tests.test_outcome_pipeline import FakeMarketData, _shadow

    _configured(monkeypatch)
    seed_control(db_session, state="DISARMED")
    candidate = candidate_factory(symbol="SHEVAL", entry_price=100.0)
    risk, analysis = _create_routing_chain(
        db_session, candidate, decision="REJECT"
    )
    _shadow(
        db_session,
        candidate,
        risk,
        analysis,
        due_at=MARKET_NOW - timedelta(hours=1),
    )
    db_session.commit()

    scout = SpyScout()
    agent = AutonomousAgent(
        scout=scout,
        pipeline=SpyPipeline(),
        router=decision_router,
        outcomes=OutcomePipeline(
            market_data=FakeMarketData({"SHEVAL": 90.0}),
        ),
        exit_manager=HoldExitManager(),
        config=_settings(paper_execution_enabled=True),
    )
    monkeypatch.setattr(internal_routes, "autonomous_agent", agent)

    with _client(db_session) as client:
        body = _post(client).json()

    assert body["mode"] == "LIFECYCLE_ONLY"
    snapshot = db_session.scalar(
        select(OutcomeSnapshot).where(OutcomeSnapshot.source_type == "SHADOW")
    )
    assert snapshot is not None
    assert snapshot.symbol == "SHEVAL"
    # Reached AVOIDED_LOSS / MISSED_ALPHA without any discovery spend.
    assert scout.calls == 0


# ===============================================================
# 23-29 full cycle behaviour and the auto-disarm handover
# ===============================================================
def test_armed_heartbeat_reaches_scout_and_may_buy_once(
    monkeypatch, db_session, candidate_factory
):
    from backend.tests.test_autonomous_agent_service import (
        FakeScout,
        build_pipeline,
    )

    _configured(monkeypatch)
    _armed(db_session)
    monkeypatch.setattr(
        alpaca_service,
        "get_account",
        MagicMock(return_value=SimpleNamespace(equity="100000")),
    )
    submit = MagicMock(
        return_value=SimpleNamespace(
            id="paper-full-1",
            status="accepted",
            filled_qty=None,
            filled_avg_price=None,
        )
    )
    monkeypatch.setattr(
        paper_execution_service, "submit_long_market_order", submit
    )
    agent = AutonomousAgent(
        scout=FakeScout(("FULL",)),
        pipeline=build_pipeline(),
        router=decision_router,
        outcomes=EmptyOutcomes(),
        exit_manager=HoldExitManager(),
        config=_settings(
            paper_execution_enabled=True,
            autonomous_new_entries_enabled=True,
        ),
    )
    monkeypatch.setattr(internal_routes, "autonomous_agent", agent)

    with _client(db_session) as client:
        first = _post(client).json()

    # 23, 24, 25 — the full pipeline ran and produced exactly one BUY.
    assert first["mode"] == "FULL_CYCLE"
    cycle = db_session.scalar(
        select(AgentCycle).order_by(AgentCycle.id.desc()).limit(1)
    )
    summary = json.loads(cycle.summary_json)
    assert summary["cycle_mode"] == "FULL_CYCLE"
    assert cycle.scouted_count == 1
    assert cycle.analyzed_count == 1
    assert db_session.scalar(
        select(func.count()).select_from(ExecutedTrade)
    ) == 1
    submit.assert_called_once()

    # 26 — the BUY consumed the budget and auto-disarmed new entries.
    control = runtime_control_service.get_control(db_session)
    assert control.executions_used == 1
    assert control.state == "DISARMED"

    # 27 — the very next heartbeat hands over to LIFECYCLE_ONLY.
    with _client(db_session) as client:
        second = _post(client).json()
    assert second["mode"] == "LIFECYCLE_ONLY"
    assert db_session.scalar(
        select(func.count()).select_from(ExecutedTrade)
    ) == 1
    submit.assert_called_once()


def test_reject_while_armed_keeps_the_budget_and_stays_full_cycle(
    monkeypatch, db_session
):
    from backend.tests.test_autonomous_agent_service import (
        FakeScout,
        StubAnalyst,
        StubCritic,
        build_pipeline,
    )

    _configured(monkeypatch)
    _armed(db_session)
    submit = MagicMock()
    monkeypatch.setattr(
        paper_execution_service, "submit_long_market_order", submit
    )
    agent = AutonomousAgent(
        scout=FakeScout(("REJ",)),
        pipeline=build_pipeline(
            analyst=StubAnalyst(confidence=0.40),
            critic=StubCritic(adjustment=-0.15),
        ),
        router=decision_router,
        outcomes=EmptyOutcomes(),
        exit_manager=HoldExitManager(),
        config=_settings(
            paper_execution_enabled=True,
            autonomous_new_entries_enabled=True,
        ),
    )
    monkeypatch.setattr(internal_routes, "autonomous_agent", agent)

    with _client(db_session) as client:
        body = _post(client).json()

    # 28 — REJECT became a ShadowTrade and spent no budget.
    assert body["mode"] == "FULL_CYCLE"
    assert db_session.scalar(
        select(func.count()).select_from(ShadowTrade)
    ) == 1
    submit.assert_not_called()
    control = runtime_control_service.get_control(db_session)
    assert control.executions_used == 0
    assert control.state == "ARMED"
    # Still effectively armed, so a later heartbeat runs FULL_CYCLE again.
    assert runtime_control_service.is_entry_armed(db_session) is True


def test_historical_accept_still_cannot_execute_under_any_mode(
    monkeypatch, db_session, candidate_factory, spies
):
    _configured(monkeypatch)
    seed_control(db_session, state="DISARMED")
    historical = candidate_factory(symbol="HISTHB")
    _create_routing_chain(db_session, historical, decision="ACCEPT")
    _pending_buy(db_session, candidate_factory, symbol="OTHER")
    before = db_session.scalar(
        select(func.count()).select_from(ExecutedTrade)
    )

    with _client(db_session) as client:
        _post(client)

    assert db_session.scalar(
        select(func.count()).select_from(ExecutedTrade)
    ) == before
    spies.submit.assert_not_called()


# ===============================================================
# the GitHub cron fallback is lifecycle-aware too
# ===============================================================
def test_cron_fallback_runs_lifecycle_only_while_disarmed(db_session):
    """The fallback must not burn provider quota while nothing is armed."""
    from backend.scripts.run_autonomous_cycle_once import run_cycle_once

    seed_control(db_session, state="DISARMED")
    agent = MagicMock()
    agent.run_cycle.return_value = SimpleNamespace(id=8, status="COMPLETED")

    result = run_cycle_once(
        config=_settings(
            autonomous_agent_enabled=True, paper_execution_enabled=True
        ),
        agent=agent,
        session_factory=MagicMock(return_value=db_session),
        engine_bind=MagicMock(),
    )

    assert result == 0
    assert agent.run_cycle.call_args.kwargs["lifecycle_only"] is True


def test_cron_fallback_runs_a_full_cycle_once_a_session_is_claimed(
    monkeypatch, db_session
):
    from backend.scripts.run_autonomous_cycle_once import run_cycle_once

    monkeypatch.setattr(settings, "paper_execution_enabled", True)
    _armed(db_session)
    agent = MagicMock()
    agent.run_cycle.return_value = SimpleNamespace(id=9, status="COMPLETED")

    result = run_cycle_once(
        config=_settings(
            autonomous_agent_enabled=True, paper_execution_enabled=True
        ),
        agent=agent,
        session_factory=MagicMock(return_value=db_session),
        engine_bind=MagicMock(),
    )

    assert result == 0
    assert agent.run_cycle.call_args.kwargs["lifecycle_only"] is False
