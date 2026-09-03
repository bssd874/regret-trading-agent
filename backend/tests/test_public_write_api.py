from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from backend.app.api import agent_routes, routes
from backend.app.core.config import Settings, settings
from backend.app.db.database import get_db
from backend.app.main import app
from backend.app.models.agent_cycle import AgentCycle
from backend.app.models.candidate_trade import CandidateTrade
from backend.app.models.executed_trade import ExecutedTrade
from backend.app.models.outcome_snapshot import OutcomeSnapshot
from backend.app.models.regret_event import RegretEvent
from backend.app.models.risk_decision import RiskDecision
from backend.app.models.shadow_trade import ShadowTrade
from backend.app.services.paper_execution_service import paper_execution_service
from backend.scripts import run_autonomous_agent as worker_module
from backend.scripts.run_autonomous_agent import run_worker
from backend.tests.test_autonomous_agent_service import _settings


def _settings_values(**overrides):
    values = {
        "alpaca_api_key": "test-key",
        "alpaca_secret_key": "test-secret",
        "alpaca_paper": True,
        "azure_openai_api_key": "test-key",
        "azure_openai_endpoint": "https://example.invalid/openai/v1",
        "azure_openai_deployment": "test-deployment",
        "nvidia_api_key": "test-key",
    }
    values.update(overrides)
    return values


@contextmanager
def _client(db_session, dependency_call=None):
    def override_db():
        if dependency_call is not None:
            dependency_call()
        yield db_session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_public_write_api_defaults_disabled():
    configured = Settings(_env_file=None, **_settings_values())
    assert configured.public_write_api_enabled is False


def test_public_write_gate_blocks_every_registered_mutation_before_work(
    monkeypatch,
    db_session,
):
    monkeypatch.setattr(settings, "public_write_api_enabled", False)

    scout_run = MagicMock()
    pipeline_run = MagicMock()
    route_decision = MagicMock()
    sync_execution = MagicMock()
    evaluate_due = MagicMock()
    evaluate_shadow = MagicMock()
    evaluate_execution = MagicMock()
    run_cycle = MagicMock()
    submit_buy = MagicMock()
    submit_sell = MagicMock()
    dependency_call = MagicMock()

    monkeypatch.setattr(routes.market_scout, "run", scout_run)
    monkeypatch.setattr(routes.decision_pipeline, "run", pipeline_run)
    monkeypatch.setattr(routes.decision_router, "route", route_decision)
    monkeypatch.setattr(routes.execution_sync_service, "sync", sync_execution)
    monkeypatch.setattr(routes.outcome_pipeline, "evaluate_due", evaluate_due)
    monkeypatch.setattr(
        routes.outcome_pipeline,
        "evaluate_shadow",
        evaluate_shadow,
    )
    monkeypatch.setattr(
        routes.outcome_pipeline,
        "evaluate_execution",
        evaluate_execution,
    )
    monkeypatch.setattr(agent_routes.autonomous_agent, "run_cycle", run_cycle)
    monkeypatch.setattr(
        paper_execution_service,
        "submit_long_market_order",
        submit_buy,
    )
    monkeypatch.setattr(
        paper_execution_service,
        "sell_long_market_position",
        submit_sell,
    )

    mutation_paths = (
        "/api/scout/run",
        "/api/candidates/1/analyze",
        "/api/decisions/1/route",
        "/api/executions/1/sync",
        "/api/outcomes/evaluate-due",
        "/api/shadow-trades/1/evaluate",
        "/api/executions/1/evaluate",
        "/api/agent/run-once",
    )

    with _client(db_session, dependency_call) as client:
        responses = [client.post(path) for path in mutation_paths]
        future_method_responses = [
            client.request(method, "/api/future-mutation")
            for method in ("PUT", "PATCH", "DELETE")
        ]

    for response in responses + future_method_responses:
        assert response.status_code == 403
        assert response.json()["detail"] == (
            "Public write API is disabled for this deployment."
        )

    dependency_call.assert_not_called()
    scout_run.assert_not_called()
    pipeline_run.assert_not_called()
    route_decision.assert_not_called()
    sync_execution.assert_not_called()
    evaluate_due.assert_not_called()
    evaluate_shadow.assert_not_called()
    evaluate_execution.assert_not_called()
    run_cycle.assert_not_called()
    submit_buy.assert_not_called()
    submit_sell.assert_not_called()

    for model in (
        AgentCycle,
        CandidateTrade,
        RiskDecision,
        ExecutedTrade,
        ShadowTrade,
        OutcomeSnapshot,
        RegretEvent,
    ):
        assert db_session.query(model).count() == 0


def test_read_only_dashboard_routes_remain_available(monkeypatch, db_session):
    monkeypatch.setattr(settings, "public_write_api_enabled", False)
    paths = (
        "/health",
        "/api/agent/status",
        "/api/agent/cycles",
        "/api/candidates",
        "/api/decisions",
        "/api/executions",
        "/api/exits",
        "/api/outcomes",
        "/api/regret-events",
        "/api/regret/metrics",
    )

    with _client(db_session) as client:
        responses = {path: client.get(path) for path in paths}

    assert {path: response.status_code for path, response in responses.items()} == {
        path: 200 for path in paths
    }


def test_enabling_public_write_api_preserves_development_route(
    monkeypatch,
    db_session,
):
    monkeypatch.setattr(settings, "public_write_api_enabled", True)
    scout_run = MagicMock(return_value=[])
    monkeypatch.setattr(routes.market_scout, "run", scout_run)

    with _client(db_session) as client:
        response = client.post("/api/scout/run")

    assert response.status_code == 200
    assert response.json() == []
    scout_run.assert_called_once_with(db=db_session, limit=5)


def test_manual_agent_trigger_gate_remains_independent(
    monkeypatch,
    db_session,
):
    monkeypatch.setattr(settings, "public_write_api_enabled", True)
    monkeypatch.setattr(settings, "public_agent_trigger_enabled", False)
    blocked_agent = MagicMock()
    monkeypatch.setattr(agent_routes, "autonomous_agent", blocked_agent)

    with _client(db_session) as client:
        response = client.post("/api/agent/run-once")

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Manual autonomous cycle triggering is disabled for this deployment."
    )
    assert db_session.query(AgentCycle).count() == 0
    blocked_agent.run_cycle.assert_not_called()


def test_worker_operates_when_public_http_writes_are_disabled(
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(worker_module.Base.metadata, "create_all", MagicMock())
    agent = MagicMock()
    agent.mode.return_value = "OBSERVE"
    agent.run_cycle.return_value = SimpleNamespace(id=7, status="COMPLETED")
    session = MagicMock()

    def stop_after_cycle(_seconds):
        raise KeyboardInterrupt

    result = run_worker(
        config=_settings(
            autonomous_agent_enabled=True,
            public_write_api_enabled=False,
        ),
        agent=agent,
        session_factory=MagicMock(return_value=session),
        sleep=stop_after_cycle,
    )

    assert result == 0
    agent.run_cycle.assert_called_once_with(db=session, trigger="SCHEDULED")
    session.close.assert_called_once()
    assert "AgentCycle 7 finished" in capsys.readouterr().out
