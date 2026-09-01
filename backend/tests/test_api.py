from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes
from backend.app.db.database import get_db
from backend.tests.test_decision_pipeline import build_pipeline


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
