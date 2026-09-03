from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes
from backend.app.db.database import get_db
from backend.app.core.config import settings
from backend.app.services.alpaca_service import alpaca_service
from backend.app.services.paper_execution_service import paper_execution_service
from backend.app.models.trade_exit import TradeExit
from backend.app.services.critic_agent import CriticAgent
from backend.tests.test_critic_fallback import FakeProvider, _valid_critic
from backend.tests.test_decision_pipeline import StubAnalyst, StubCritic, build_pipeline
from backend.tests.test_decision_router import _create_routing_chain
from backend.tests.test_outcome_pipeline import NOW, _executed


def test_analysis_and_decision_endpoints(
    monkeypatch,
    db_session,
    candidate_factory,
):
    candidate = candidate_factory()
    monkeypatch.setattr(routes, "decision_pipeline", build_pipeline())

    app = FastAPI()
    app.include_router(routes.router, prefix="/api")

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db

    with TestClient(app) as client:
        analyzed = client.post(f"/api/candidates/{candidate.id}/analyze")
        assert analyzed.status_code == 200
        body = analyzed.json()
        assert body["risk"]["decision"] == "ACCEPT"
        assert body["order_submitted"] is False

        listing = client.get("/api/decisions")
        assert listing.status_code == 200
        assert len(listing.json()) == 1
        assert listing.json()[0]["decision"] == "ACCEPT"

        detail = client.get(f"/api/decisions/{body['decision_id']}")
        assert detail.status_code == 200
        assert detail.json()["critic"]["provider"] == "nvidia"
        assert detail.json()["order_submitted"] is False


def test_analyze_missing_candidate_returns_404(monkeypatch, db_session):
    monkeypatch.setattr(routes, "decision_pipeline", build_pipeline())
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db

    with TestClient(app) as client:
        response = client.post("/api/candidates/999/analyze")

    assert response.status_code == 404


def test_missing_decision_returns_404(db_session):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db

    with TestClient(app) as client:
        response = client.get("/api/decisions/999")

    assert response.status_code == 404


def _test_client(db_session):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_execution_route_read_and_sync_endpoints(
    monkeypatch,
    db_session,
    candidate_factory,
):
    monkeypatch.setattr(routes, "decision_pipeline", build_pipeline())
    monkeypatch.setattr(settings, "paper_execution_enabled", True)
    monkeypatch.setattr(
        alpaca_service,
        "get_account",
        MagicMock(return_value=SimpleNamespace(equity="100000")),
    )
    submit = MagicMock(
        return_value=SimpleNamespace(
            id="paper-api-order",
            status="accepted",
            filled_qty=None,
            filled_avg_price=None,
        )
    )
    monkeypatch.setattr(
        paper_execution_service,
        "submit_long_market_order",
        submit,
    )
    get_order = MagicMock(
        return_value=SimpleNamespace(
            status="filled",
            filled_qty="2",
            filled_avg_price="50.00",
        )
    )
    monkeypatch.setattr(paper_execution_service, "get_order", get_order)
    candidate = candidate_factory()

    with _test_client(db_session) as client:
        analyzed = client.post(f"/api/candidates/{candidate.id}/analyze").json()
        routed = client.post(f"/api/decisions/{analyzed['decision_id']}/route")
        assert routed.status_code == 200
        execution_id = routed.json()["executed_trade_id"]

        listing = client.get("/api/executions")
        detail = client.get(f"/api/executions/{execution_id}")
        synced = client.post(f"/api/executions/{execution_id}/sync")

    assert listing.status_code == 200
    assert listing.json()[0]["alpaca_order_id"] == "paper-api-order"
    assert detail.status_code == 200
    assert detail.json()["paper"] is True
    assert synced.status_code == 200
    assert synced.json()["status"] == "filled"
    assert synced.json()["filled_qty"] == 2.0
    assert synced.json()["filled_avg_price"] == 50.0
    submit.assert_called_once()
    get_order.assert_called_once_with("paper-api-order")


def test_shadow_route_and_read_endpoints(
    monkeypatch,
    db_session,
    candidate_factory,
):
    pipeline = build_pipeline(
        analyst=StubAnalyst(confidence=0.75),
        critic=StubCritic(adjustment=-0.10),
    )
    monkeypatch.setattr(routes, "decision_pipeline", pipeline)
    monkeypatch.setattr(
        alpaca_service,
        "get_account",
        MagicMock(return_value=SimpleNamespace(equity="100000")),
    )
    submit = MagicMock()
    monkeypatch.setattr(
        paper_execution_service,
        "submit_long_market_order",
        submit,
    )
    candidate = candidate_factory()

    with _test_client(db_session) as client:
        analyzed = client.post(f"/api/candidates/{candidate.id}/analyze").json()
        routed = client.post(f"/api/decisions/{analyzed['decision_id']}/route")
        assert routed.status_code == 200
        shadow_id = routed.json()["shadow_trade_id"]
        replay = client.post(f"/api/decisions/{analyzed['decision_id']}/route")
        listing = client.get("/api/shadow-trades")
        detail = client.get(f"/api/shadow-trades/{shadow_id}")

    assert replay.json()["shadow_trade_id"] == shadow_id
    assert replay.json()["idempotent_replay"] is True
    assert len(listing.json()) == 1
    assert detail.json()["order_submitted"] is False
    submit.assert_not_called()


def test_decision_api_exposes_azure_critic_fallback(
    monkeypatch,
    db_session,
    candidate_factory,
):
    critic = CriticAgent(
        FakeProvider(error=TimeoutError("provider timed out")),
        FakeProvider(payload=_valid_critic()),
    )
    monkeypatch.setattr(
        routes,
        "decision_pipeline",
        build_pipeline(critic=critic),
    )
    candidate = candidate_factory()

    with _test_client(db_session) as client:
        analyzed = client.post(f"/api/candidates/{candidate.id}/analyze")
        decision_id = analyzed.json()["decision_id"]
        detail = client.get(f"/api/decisions/{decision_id}")
        listing = client.get("/api/decisions")

    assert analyzed.json()["critic"]["provider"] == "azure-fallback"
    assert analyzed.json()["critic"]["degraded_mode"] is True
    assert detail.json()["critic"]["provider"] == "azure-fallback"
    assert listing.json()[0]["critic_provider"] == "azure-fallback"


def test_trade_exit_read_only_endpoints(db_session, candidate_factory):
    candidate = candidate_factory(symbol="EXITAPI")
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
        reason="TAKE_PROFIT",
        trigger_price=105.0,
        target_price=analysis.target_price,
        stop_loss=analysis.stop_loss,
        horizon_minutes=analysis.horizon_minutes,
        requested_qty=10.0,
        alpaca_order_id="paper-exit-api",
        status="filled",
        filled_qty=10.0,
        filled_avg_price=105.0,
        triggered_at=NOW,
        submitted_at=NOW,
        closed_at=NOW,
    )
    db_session.add(trade_exit)
    db_session.commit()
    db_session.refresh(trade_exit)

    with _test_client(db_session) as client:
        listing = client.get("/api/exits")
        detail = client.get(f"/api/exits/{trade_exit.id}")
        missing = client.get("/api/exits/999")

    assert listing.status_code == 200
    assert listing.json()[0]["reason"] == "TAKE_PROFIT"
    assert detail.status_code == 200
    assert detail.json()["executed_trade_id"] == execution.id
    assert detail.json()["paper"] is True
    assert missing.status_code == 404
