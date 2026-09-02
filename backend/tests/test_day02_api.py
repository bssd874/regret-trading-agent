from datetime import timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes
from backend.app.db.database import get_db
from backend.app.services.outcome_pipeline import OutcomePipeline
from backend.tests.test_decision_router import _create_routing_chain
from backend.tests.test_outcome_pipeline import (
    FakeMarketData,
    NOW,
    _executed,
    _shadow,
)


def _client(db_session):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_day02_shadow_outcome_event_and_metrics_endpoints(
    monkeypatch,
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
        due_at=NOW - timedelta(days=2),
    )
    monkeypatch.setattr(
        routes,
        "outcome_pipeline",
        OutcomePipeline(market_data=FakeMarketData({candidate.symbol: 110.0})),
    )

    with _client(db_session) as client:
        evaluated = client.post(f"/api/shadow-trades/{shadow.id}/evaluate")
        replay = client.post(f"/api/shadow-trades/{shadow.id}/evaluate")
        outcome_id = evaluated.json()["outcome_id"]
        event_id = evaluated.json()["regret_event_id"]
        outcomes = client.get("/api/outcomes")
        outcome = client.get(f"/api/outcomes/{outcome_id}")
        events = client.get("/api/regret-events")
        event = client.get(f"/api/regret-events/{event_id}")
        metrics = client.get("/api/regret/metrics")

    assert evaluated.status_code == 200
    assert evaluated.json()["classification"] == "MISSED_ALPHA"
    assert replay.json()["idempotent_replay"] is True
    assert len(outcomes.json()) == 1
    assert outcome.json()["price_source"] == "test_snapshot"
    assert len(events.json()) == 1
    assert event.json()["classification"] == "MISSED_ALPHA"
    assert metrics.json()["total_decisions_evaluated"] == 1


def test_day02_evaluate_due_and_execution_not_ready_endpoints(
    monkeypatch,
    db_session,
    candidate_factory,
):
    rejected = candidate_factory(symbol="DUE")
    rejected_risk, analysis = _create_routing_chain(
        db_session, rejected, decision="REJECT"
    )
    _shadow(
        db_session,
        rejected,
        rejected_risk,
        analysis,
        due_at=NOW - timedelta(days=1),
    )
    accepted = candidate_factory(symbol="UNFILLED")
    accepted_risk, _ = _create_routing_chain(
        db_session, accepted, decision="ACCEPT"
    )
    execution = _executed(
        db_session,
        accepted,
        accepted_risk,
        status="accepted",
        filled_qty=None,
        filled_avg_price=None,
    )
    monkeypatch.setattr(
        routes,
        "outcome_pipeline",
        OutcomePipeline(market_data=FakeMarketData({"DUE": 105.0})),
    )

    with _client(db_session) as client:
        batch = client.post("/api/outcomes/evaluate-due")
        unfilled = client.post(f"/api/executions/{execution.id}/evaluate")
        missing_outcome = client.get("/api/outcomes/999")
        missing_event = client.get("/api/regret-events/999")

    assert batch.status_code == 200
    assert batch.json()["evaluated"] == 1
    assert unfilled.status_code == 200
    assert unfilled.json()["status"] == "NOT_READY"
    assert missing_outcome.status_code == 404
    assert missing_event.status_code == 404
