from datetime import datetime, timezone
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import agent_routes
from backend.app.core.config import settings
from backend.app.db.database import get_db
from backend.app.models.agent_cycle import AgentCycle
from backend.app.services.autonomous_agent_service import AutonomousAgent
from backend.tests.test_autonomous_agent_service import (
    EmptyOutcomes,
    FakeScout,
    _settings,
)
from backend.tests.test_decision_pipeline import build_pipeline


def _client(db_session):
    app = FastAPI()
    app.include_router(agent_routes.router, prefix="/api")

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_agent_status_reports_observe_mode(monkeypatch, db_session):
    monkeypatch.setattr(settings, "autonomous_agent_enabled", True)
    monkeypatch.setattr(settings, "paper_execution_enabled", False)

    with _client(db_session) as client:
        response = client.get("/api/agent/status")

    assert response.status_code == 200
    assert response.json()["enabled"] is True
    assert response.json()["mode"] == "OBSERVE"
    assert response.json()["paper"] is True
    assert response.json()["paper_execution_enabled"] is False


def test_agent_status_reports_autonomous_paper_mode(monkeypatch, db_session):
    monkeypatch.setattr(settings, "autonomous_agent_enabled", True)
    monkeypatch.setattr(settings, "paper_execution_enabled", True)

    with _client(db_session) as client:
        response = client.get("/api/agent/status")

    assert response.status_code == 200
    assert response.json()["mode"] == "AUTONOMOUS_PAPER"
    assert response.json()["paper"] is True


def test_status_and_cycle_endpoints_report_last_cycle(db_session):
    now = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
    cycle = AgentCycle(
        trigger="MANUAL",
        status="COMPLETED",
        mode="OBSERVE",
        started_at=now,
        heartbeat_at=now,
        finished_at=now,
        scouted_count=2,
        analyzed_count=1,
        rejected_count=1,
        shadow_created_count=1,
        summary_json='{"executions_synced": 3, "executions_filled": 1}',
    )
    db_session.add(cycle)
    db_session.commit()
    db_session.refresh(cycle)

    with _client(db_session) as client:
        status = client.get("/api/agent/status")
        listing = client.get("/api/agent/cycles")
        detail = client.get(f"/api/agent/cycles/{cycle.id}")
        missing = client.get("/api/agent/cycles/999")

    body = status.json()
    assert body["last_cycle_status"] == "COMPLETED"
    assert body["last_cycle"]["id"] == cycle.id
    assert body["last_cycle_counts"]["scouted"] == 2
    assert body["executions_synced"] == 3
    assert body["executions_filled"] == 1
    assert body["last_cycle_counts"]["executions_synced"] == 3
    assert body["last_cycle_counts"]["executions_filled"] == 1
    assert body["last_cycle"]["executions_synced"] == 3
    assert body["last_cycle"]["executions_filled"] == 1
    assert listing.json()[0]["shadow_created_count"] == 1
    assert detail.json()["id"] == cycle.id
    assert missing.status_code == 404


def test_manual_run_once_honors_execution_kill_switch(
    monkeypatch,
    db_session,
):
    router = MagicMock()
    agent = AutonomousAgent(
        scout=FakeScout(("MANUAL",)),
        pipeline=build_pipeline(),
        router=router,
        outcomes=EmptyOutcomes(),
        config=_settings(
            autonomous_agent_enabled=False,
            paper_execution_enabled=False,
        ),
    )
    monkeypatch.setattr(agent_routes, "autonomous_agent", agent)

    with _client(db_session) as client:
        response = client.post("/api/agent/run-once")

    assert response.status_code == 200
    assert response.json()["trigger"] == "MANUAL"
    assert response.json()["mode"] == "OBSERVE"
    assert response.json()["execution_held_count"] == 1
    assert response.json()["paper_execution_count"] == 0
    router.route.assert_not_called()


def test_manual_run_once_rejects_overlap(monkeypatch, db_session):
    now = datetime.now(timezone.utc)
    db_session.add(
        AgentCycle(
            trigger="SCHEDULED",
            status="RUNNING",
            mode="OBSERVE",
            started_at=now,
            heartbeat_at=now,
        )
    )
    db_session.commit()
    agent = AutonomousAgent(
        scout=FakeScout(()),
        pipeline=build_pipeline(),
        router=MagicMock(),
        outcomes=EmptyOutcomes(),
        config=_settings(),
    )
    monkeypatch.setattr(agent_routes, "autonomous_agent", agent)

    with _client(db_session) as client:
        response = client.post("/api/agent/run-once")

    assert response.status_code == 409
    assert response.json()["detail"] == "AGENT_CYCLE_ALREADY_RUNNING"
