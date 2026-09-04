"""The scheduler heartbeat: authentication, safety and exit continuity.

Every Alpaca interaction here is mocked. Nothing in this module contacts a
broker, an AI provider or a real scheduler.
"""

import json
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app.api import internal_routes
from backend.app.core.config import Settings, settings
from backend.app.db.database import get_db
from backend.app.main import app
from backend.app.models.agent_cycle import AgentCycle
from backend.app.models.executed_trade import ExecutedTrade
from backend.app.models.shadow_trade import ShadowTrade
from backend.app.models.trade_exit import TradeExit
from backend.app.services.alpaca_service import alpaca_service
from backend.app.services.autonomous_agent_service import (
    AgentCycleAlreadyRunning,
)
from backend.app.services.decision_router import decision_router
from backend.app.services.paper_execution_service import paper_execution_service
from backend.app.services.runtime_control_service import (
    HOLD_REASON_RUNTIME_DISARMED,
    runtime_control_service,
)
from backend.tests.runtime_control_helpers import NOW, seed_control
from backend.tests.test_autonomous_agent_service import _agent, _settings
from backend.tests.test_outcome_pipeline import _executed
from backend.tests.test_decision_router import _create_routing_chain
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
    monkeypatch.setattr(settings, "public_write_api_enabled", False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("REGRET_REQUIRE_DATABASE_URL", raising=False)


def _seed_lifecycle_work(db, candidate_factory, *, symbol="PEND"):
    """A pending BUY, so the heartbeat has genuine lifecycle work to do."""
    candidate = candidate_factory(symbol=symbol, entry_price=100.0)
    risk, _ = _create_routing_chain(db, candidate, decision="ACCEPT")
    execution = _executed(db, candidate, risk, status="accepted")
    db.commit()
    return execution


def _stub_agent(monkeypatch, **overrides):
    agent = MagicMock()
    agent.run_cycle.return_value = SimpleNamespace(
        id=overrides.get("id", 77),
        status=overrides.get("status", "COMPLETED"),
        started_at=None,
        finished_at=None,
    )
    monkeypatch.setattr(internal_routes, "autonomous_agent", agent)
    return agent


# ---------------------------------------------------------------
# 1-4 authentication
# ---------------------------------------------------------------
def test_scheduler_secret_defaults_to_unset():
    configured = Settings(
        _env_file=None,
        alpaca_api_key="k",
        alpaca_secret_key="s",
        alpaca_paper=True,
        azure_openai_api_key="k",
        azure_openai_endpoint="https://example.invalid/openai/v1",
        azure_openai_deployment="d",
        nvidia_api_key="k",
    )
    assert configured.scheduler_trigger_secret is None


def test_heartbeat_is_disabled_when_no_secret_is_configured(
    monkeypatch,
    db_session,
):
    _configured(monkeypatch)
    monkeypatch.setattr(settings, "scheduler_trigger_secret", None)
    agent = _stub_agent(monkeypatch)

    with _client(db_session) as client:
        response = client.post(ENDPOINT, headers=HEADERS)

    assert response.status_code == 503
    agent.run_cycle.assert_not_called()
    assert db_session.scalar(select(func.count()).select_from(AgentCycle)) == 0


def test_wrong_or_missing_scheduler_secret_is_denied(monkeypatch, db_session):
    _configured(monkeypatch)
    agent = _stub_agent(monkeypatch)

    with _client(db_session) as client:
        anonymous = client.post(ENDPOINT)
        wrong = client.post(
            ENDPOINT, headers={"X-Regret-Scheduler-Secret": "not-the-secret"}
        )
        empty = client.post(ENDPOINT, headers={"X-Regret-Scheduler-Secret": ""})

    assert anonymous.status_code == 401
    assert wrong.status_code == 401
    assert empty.status_code == 401
    agent.run_cycle.assert_not_called()


def test_correct_secret_invokes_exactly_one_cycle(
    monkeypatch,
    db_session,
    candidate_factory,
):
    _configured(monkeypatch)
    _seed_lifecycle_work(db_session, candidate_factory)
    agent = _stub_agent(monkeypatch)

    with _client(db_session) as client:
        response = client.post(ENDPOINT, headers=HEADERS)

    body = response.json()
    assert response.status_code == 200
    assert body["cycle_id"] == 77
    assert body["status"] == "COMPLETED"
    assert body["trigger_source"] == "SCHEDULED_HEARTBEAT"
    agent.run_cycle.assert_called_once_with(
        db=db_session,
        trigger="SCHEDULED",
        trigger_source="SCHEDULED_HEARTBEAT",
        lifecycle_only=True,
    )


def test_heartbeat_does_not_reopen_the_public_write_api(monkeypatch, db_session):
    _configured(monkeypatch)
    _stub_agent(monkeypatch)

    with _client(db_session) as client:
        heartbeat = client.post(ENDPOINT, headers=HEADERS)
        scout = client.post("/api/scout/run")
        run_once = client.post("/api/agent/run-once")

    assert heartbeat.status_code == 200
    assert scout.status_code == 403
    assert run_once.status_code == 403


# ---------------------------------------------------------------
# 10 concurrency
# ---------------------------------------------------------------
def test_concurrent_heartbeat_cannot_create_a_duplicate_cycle(
    monkeypatch,
    db_session,
    candidate_factory,
):
    _configured(monkeypatch)
    _seed_lifecycle_work(db_session, candidate_factory)
    agent = _stub_agent(monkeypatch)
    agent.run_cycle.side_effect = AgentCycleAlreadyRunning()

    with _client(db_session) as client:
        response = client.post(ENDPOINT, headers=HEADERS)

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ALREADY_RUNNING"
    assert body["cycle_id"] is None
    assert body["mode"] == "LIFECYCLE_ONLY"
    assert db_session.scalar(select(func.count()).select_from(AgentCycle)) == 0


# ---------------------------------------------------------------
# 15 database fail-closed
# ---------------------------------------------------------------
def test_hosted_automation_refuses_a_sqlite_fallback(monkeypatch, db_session):
    _configured(monkeypatch)
    monkeypatch.setenv("VERCEL", "1")
    agent = _stub_agent(monkeypatch)

    with _client(db_session) as client:
        response = client.post(ENDPOINT, headers=HEADERS)

    assert response.status_code == 503
    assert "SQLite" in response.json()["detail"]
    agent.run_cycle.assert_not_called()


# ---------------------------------------------------------------
# 14 secret containment
# ---------------------------------------------------------------
def test_no_secret_appears_in_any_heartbeat_response(monkeypatch, db_session):
    _configured(monkeypatch)
    monkeypatch.setattr(settings, "admin_control_secret", "TEST_ADMIN_SECRET")
    _stub_agent(monkeypatch)

    with _client(db_session) as client:
        responses = [
            client.post(ENDPOINT, headers=HEADERS),
            client.post(ENDPOINT),
            client.post(
                ENDPOINT, headers={"X-Regret-Scheduler-Secret": "wrong"}
            ),
        ]

    for response in responses:
        blob = json.dumps(response.json())
        assert SCHEDULER_SECRET not in blob
        assert "TEST_ADMIN_SECRET" not in blob


# ---------------------------------------------------------------
# 16 serverless safety
# ---------------------------------------------------------------
def test_the_heartbeat_introduces_no_loop_thread_or_sleep():
    source = Path(internal_routes.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "while True",
        "time.sleep",
        "threading",
        "Thread(",
        "asyncio.create_task",
        "BackgroundTasks",
        "schedule.every",
    ):
        assert forbidden not in source, f"heartbeat must not use {forbidden}"


# =========================================================
# End-to-end behaviour through the real agent
# =========================================================
@pytest.fixture
def paper_broker(monkeypatch):
    monkeypatch.setattr(settings, "paper_execution_enabled", True)
    monkeypatch.setattr(
        alpaca_service,
        "get_account",
        MagicMock(return_value=SimpleNamespace(equity="100000")),
    )
    submit = MagicMock(
        return_value=SimpleNamespace(
            id="paper-heartbeat-1",
            status="accepted",
            filled_qty=None,
            filled_avg_price=None,
        )
    )
    monkeypatch.setattr(
        paper_execution_service, "submit_long_market_order", submit
    )
    return SimpleNamespace(submit=submit)


def _install_agent(monkeypatch, *, symbols=("ONE",), exit_manager=None):
    """Install a real AutonomousAgent driven by deterministic doubles.

    The genuine cycle, router and runtime-control logic all run; only the
    market data, providers and broker are stubbed, so no network call and no
    real order is ever possible.
    """
    agent = _agent(
        symbols=symbols,
        router=decision_router,
        exit_manager=exit_manager,
        config=_settings(
            paper_execution_enabled=True,
            autonomous_new_entries_enabled=True,
        ),
    )
    monkeypatch.setattr(internal_routes, "autonomous_agent", agent)
    return agent


def _real_agent_response(client):
    return client.post(ENDPOINT, headers=HEADERS)


# ---------------------------------------------------------------
# 5, 11, 12, 13 entry semantics under the heartbeat
# ---------------------------------------------------------------
def test_disarmed_heartbeat_cannot_buy_and_never_arms_the_runtime(
    monkeypatch,
    db_session,
    candidate_factory,
    paper_broker,
):
    _configured(monkeypatch)
    _install_agent(monkeypatch)
    seed_control(db_session, state="DISARMED")
    _seed_lifecycle_work(db_session, candidate_factory, symbol="DISPEND")

    with _client(db_session) as client:
        response = _real_agent_response(client)

    body = response.json()
    assert response.status_code == 200
    assert body["mode"] == "LIFECYCLE_ONLY"

    cycle = db_session.scalar(
        select(AgentCycle).order_by(AgentCycle.id.desc()).limit(1)
    )
    summary = json.loads(cycle.summary_json)
    assert summary["trigger_source"] == "SCHEDULED_HEARTBEAT"
    assert summary["cycle_mode"] == "LIFECYCLE_ONLY"
    assert cycle.paper_execution_count == 0
    paper_broker.submit.assert_not_called()

    # No new entry work happened at all: nothing was scouted or decided.
    assert summary["scout"]["status"] == "SKIPPED"
    assert summary["scout"]["reason"] == "LIFECYCLE_ONLY"
    assert summary["candidates"] == []
    assert cycle.scouted_count == 0
    assert cycle.analyzed_count == 0

    # The heartbeat only reads permission; it never grants it.
    control = runtime_control_service.get_control(db_session)
    assert control.state == "DISARMED"
    assert control.new_entries_armed is False
    assert control.executions_used == 0


def test_heartbeat_respects_an_exhausted_execution_budget(
    monkeypatch,
    db_session,
    paper_broker,
):
    _configured(monkeypatch)
    _install_agent(monkeypatch)
    seed_control(
        db_session,
        state="ARMED",
        new_entries_armed=True,
        armed_at=NOW,
        armed_until=NOW + timedelta(days=3650),
        max_new_executions=1,
        executions_used=1,
    )

    with _client(db_session) as client:
        response = _real_agent_response(client)

    assert response.status_code == 200
    assert db_session.scalar(
        select(func.count()).select_from(ExecutedTrade)
    ) == 0
    paper_broker.submit.assert_not_called()


def test_heartbeat_does_not_execute_a_historical_accept(
    monkeypatch,
    db_session,
    candidate_factory,
    paper_broker,
):
    from backend.tests.test_decision_router import _create_routing_chain

    _configured(monkeypatch)
    _install_agent(monkeypatch)
    historical = candidate_factory(symbol="OLDHB")
    historical_risk, _ = _create_routing_chain(
        db_session, historical, decision="ACCEPT"
    )
    seed_control(db_session, state="DISARMED")

    with _client(db_session) as client:
        _real_agent_response(client)

    executions = list(db_session.scalars(select(ExecutedTrade)))
    assert executions == []
    assert db_session.get(type(historical_risk), historical_risk.id) is not None
    paper_broker.submit.assert_not_called()


# ---------------------------------------------------------------
# 6-8 exit safety while disarmed
# ---------------------------------------------------------------
@pytest.mark.parametrize(
    "price,submitted_ago,expected_reason",
    [
        (104.0, timedelta(minutes=30), "TAKE_PROFIT"),
        (98.0, timedelta(minutes=30), "STOP_LOSS"),
        (100.0, timedelta(minutes=61), "TIME_EXIT"),
    ],
)
def test_disarmed_heartbeat_still_exits_an_open_position(
    monkeypatch,
    db_session,
    candidate_factory,
    price,
    submitted_ago,
    expected_reason,
):
    """The whole point of the heartbeat: a stranded position gets closed."""
    _configured(monkeypatch)
    monkeypatch.setattr(settings, "paper_execution_enabled", True)
    seed_control(db_session, state="DISARMED")

    execution, _, _ = _open_position(
        db_session,
        candidate_factory,
        symbol=f"HB{expected_reason[:3]}",
        submitted_ago=submitted_ago,
    )
    sell_provider = _provider()

    # Drive the exit manager the cycle uses, with a deterministic price.
    from backend.app.services.position_exit_service import PositionExitService
    from backend.tests.test_outcome_pipeline import NOW as MARKET_NOW

    exit_service = PositionExitService(
        market_data=FixedMarketData(price),
        execution_provider=sell_provider,
        config=settings,
        now_provider=lambda: MARKET_NOW,
    )
    _install_agent(monkeypatch, exit_manager=exit_service)

    with _client(db_session) as client:
        response = _real_agent_response(client)

    assert response.status_code == 200
    trade_exit = db_session.scalar(select(TradeExit))
    assert trade_exit is not None
    assert trade_exit.reason == expected_reason
    assert trade_exit.executed_trade_id == execution.id
    sell_provider.sell_long_market_position.assert_called_once()

    # Still disarmed: the exit did not require, or grant, entry permission.
    control = runtime_control_service.get_control(db_session)
    assert control.state == "DISARMED"


# ---------------------------------------------------------------
# 9 armed semantics preserved
# ---------------------------------------------------------------
def test_armed_heartbeat_preserves_normal_current_cycle_entry_semantics(
    monkeypatch,
    db_session,
    paper_broker,
):
    _configured(monkeypatch)
    _install_agent(monkeypatch)
    seed_control(
        db_session,
        state="ARMED",
        new_entries_armed=True,
        arm_session_id="heartbeat-session",
        armed_at=NOW,
        armed_until=NOW + timedelta(days=3650),
        max_new_executions=1,
        executions_used=0,
    )

    with _client(db_session) as client:
        response = _real_agent_response(client)

    assert response.status_code == 200
    executions = list(db_session.scalars(select(ExecutedTrade)))
    assert len(executions) == 1
    paper_broker.submit.assert_called_once()

    # One BUY spends the budget and auto-disarms, exactly as for any cycle.
    control = runtime_control_service.get_control(db_session)
    assert control.executions_used == 1
    assert control.state == "DISARMED"
    assert control.last_disarm_reason == "EXECUTION_BUDGET_USED"
    assert db_session.scalar(
        select(func.count()).select_from(ShadowTrade)
    ) == 0
