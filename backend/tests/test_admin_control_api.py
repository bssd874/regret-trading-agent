"""Isolated admin control surface: auth, conflicts and secret containment."""

import json
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from backend.app.core.config import Settings, settings
from backend.app.db.database import get_db
from backend.app.main import app
from backend.app.models.agent_cycle import AgentCycle
from backend.app.models.executed_trade import ExecutedTrade
from backend.app.services import runtime_control_service as control_module
from backend.app.services.github_dispatch_service import (
    GitHubDispatchError,
    GitHubDispatchService,
)
from backend.app.services.runtime_control_service import (
    runtime_control_service,
)
from backend.tests.runtime_control_helpers import (
    NOW,
    StubDispatcher,
    seed_control,
)


ADMIN_SECRET = "TEST_ADMIN_CONTROL_SECRET"
HEADERS = {"X-Regret-Admin-Secret": ADMIN_SECRET}


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


def _arm_ready(monkeypatch, *, dispatcher=None):
    """Master capability on, admin configured, dispatch stubbed."""
    monkeypatch.setattr(settings, "admin_control_secret", ADMIN_SECRET)
    monkeypatch.setattr(settings, "paper_execution_enabled", True)
    monkeypatch.setattr(settings, "public_write_api_enabled", False)
    stub = dispatcher or StubDispatcher()
    monkeypatch.setattr(runtime_control_service, "dispatcher", stub)
    monkeypatch.setattr(
        runtime_control_service,
        "now_provider",
        lambda: NOW,
    )
    return stub


# ---------------------------------------------------------------
# 12 / 38-40 / 43 authentication
# ---------------------------------------------------------------
def test_admin_secret_defaults_to_unset():
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
    assert configured.admin_control_secret is None


def test_admin_mutations_fail_closed_when_secret_is_unconfigured(
    monkeypatch,
    db_session,
):
    _arm_ready(monkeypatch)
    monkeypatch.setattr(settings, "admin_control_secret", None)

    with _client(db_session) as client:
        arm = client.post("/api/admin/agent-control/arm-request", headers=HEADERS)
        disarm = client.post("/api/admin/agent-control/disarm", headers=HEADERS)

    assert arm.status_code == 503
    assert disarm.status_code == 503
    assert runtime_control_service.get_control(db_session) is None


def test_missing_or_wrong_admin_secret_is_rejected(monkeypatch, db_session):
    stub = _arm_ready(monkeypatch)

    with _client(db_session) as client:
        missing = client.post("/api/admin/agent-control/arm-request")
        wrong = client.post(
            "/api/admin/agent-control/arm-request",
            headers={"X-Regret-Admin-Secret": "not-the-secret"},
        )
        disarm = client.post("/api/admin/agent-control/disarm")

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert disarm.status_code == 401
    assert stub.calls == []
    assert runtime_control_service.get_control(db_session) is None


# ---------------------------------------------------------------
# 13 / 16-17 arm request and conflicts
# ---------------------------------------------------------------
def test_authenticated_arm_request_dispatches_once_and_reports_starting(
    monkeypatch,
    db_session,
):
    stub = _arm_ready(monkeypatch)

    with _client(db_session) as client:
        response = client.post(
            "/api/admin/agent-control/arm-request",
            headers=HEADERS,
        )

    body = response.json()["runtime_control"]
    assert response.status_code == 200
    assert body["state"] == "START_REQUESTED"
    assert body["entry_execution_state"] == "STARTING"
    assert body["effective_new_entries_armed"] is False
    assert len(stub.calls) == 1


def test_duplicate_arm_requests_conflict_without_a_second_dispatch(
    monkeypatch,
    db_session,
):
    stub = _arm_ready(monkeypatch)

    with _client(db_session) as client:
        first = client.post(
            "/api/admin/agent-control/arm-request", headers=HEADERS
        )
        second = client.post(
            "/api/admin/agent-control/arm-request", headers=HEADERS
        )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "ALREADY_ACTIVE"
    assert len(stub.calls) == 1


def test_arm_request_while_armed_conflicts(monkeypatch, db_session):
    stub = _arm_ready(monkeypatch)
    seed_control(
        db_session,
        state="ARMED",
        new_entries_armed=True,
        armed_at=NOW,
        armed_until=NOW + timedelta(minutes=15),
    )

    with _client(db_session) as client:
        response = client.post(
            "/api/admin/agent-control/arm-request", headers=HEADERS
        )

    assert response.status_code == 409
    assert stub.calls == []


def test_dispatch_failure_returns_conflict_and_leaves_system_disarmed(
    monkeypatch,
    db_session,
):
    _arm_ready(
        monkeypatch,
        dispatcher=StubDispatcher(error=GitHubDispatchError("nope")),
    )

    with _client(db_session) as client:
        response = client.post(
            "/api/admin/agent-control/arm-request", headers=HEADERS
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "DISPATCH_FAILED"
    control = runtime_control_service.get_control(db_session)
    assert control.state == "DISARMED"
    assert control.last_disarm_reason == "DISPATCH_FAILED"


def test_master_execution_disabled_blocks_arm_request(monkeypatch, db_session):
    stub = _arm_ready(monkeypatch)
    monkeypatch.setattr(settings, "paper_execution_enabled", False)

    with _client(db_session) as client:
        response = client.post(
            "/api/admin/agent-control/arm-request", headers=HEADERS
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "MASTER_EXECUTION_DISABLED"
    assert stub.calls == []


# ---------------------------------------------------------------
# disarm
# ---------------------------------------------------------------
def test_disarm_is_authenticated_and_idempotent(monkeypatch, db_session):
    _arm_ready(monkeypatch)
    seed_control(
        db_session,
        state="ARMED",
        new_entries_armed=True,
        armed_at=NOW,
        armed_until=NOW + timedelta(minutes=15),
    )

    with _client(db_session) as client:
        first = client.post("/api/admin/agent-control/disarm", headers=HEADERS)
        second = client.post("/api/admin/agent-control/disarm", headers=HEADERS)

    for response in (first, second):
        assert response.status_code == 200
        body = response.json()["runtime_control"]
        assert body["state"] == "DISARMED"
        assert body["effective_new_entries_armed"] is False


# ---------------------------------------------------------------
# 18 secret containment
# ---------------------------------------------------------------
def test_admin_and_status_responses_never_leak_secrets(monkeypatch, db_session):
    _arm_ready(monkeypatch)
    monkeypatch.setattr(
        settings, "regret_github_dispatch_token", "TEST_DISPATCH_TOKEN_MUST_NOT_APPEAR"
    )

    with _client(db_session) as client:
        arm = client.post(
            "/api/admin/agent-control/arm-request", headers=HEADERS
        )
        read = client.get("/api/admin/agent-control", headers=HEADERS)
        status = client.get("/api/agent/status")

    blobs = [json.dumps(r.json()) for r in (arm, read, status)]
    for blob in blobs:
        assert "TEST_DISPATCH_TOKEN_MUST_NOT_APPEAR" not in blob
        assert ADMIN_SECRET not in blob
    # The public status projection also withholds the arm session id.
    assert "arm_session_id" not in status.json()["runtime_control"]


def test_public_status_exposes_runtime_control_read_only(
    monkeypatch,
    db_session,
):
    _arm_ready(monkeypatch)
    seed_control(
        db_session,
        state="ARMED",
        new_entries_armed=True,
        armed_at=NOW,
        armed_until=NOW + timedelta(minutes=15),
    )

    with _client(db_session) as client:
        response = client.get("/api/agent/status")

    body = response.json()
    assert response.status_code == 200
    assert body["entry_execution_state"] == "ARMED"
    assert body["runtime_control"]["effective_new_entries_armed"] is True
    assert body["runtime_control"]["max_new_executions"] == 1


# ---------------------------------------------------------------
# the admin surface does not reopen the public write API
# ---------------------------------------------------------------
def test_other_public_mutations_stay_blocked_while_admin_works(
    monkeypatch,
    db_session,
):
    _arm_ready(monkeypatch)

    with _client(db_session) as client:
        blocked = client.post("/api/scout/run")
        agent_trigger = client.post("/api/agent/run-once")
        admin = client.get("/api/admin/agent-control", headers=HEADERS)

    assert blocked.status_code == 403
    assert agent_trigger.status_code == 403
    assert admin.status_code == 200
    assert db_session.query(AgentCycle).count() == 0
    assert db_session.query(ExecutedTrade).count() == 0


# ---------------------------------------------------------------
# dispatch service configuration
# ---------------------------------------------------------------
def test_dispatch_service_is_disabled_without_repository_and_token():
    service = GitHubDispatchService(
        config=Settings(
            _env_file=None,
            alpaca_api_key="k",
            alpaca_secret_key="s",
            alpaca_paper=True,
            azure_openai_api_key="k",
            azure_openai_endpoint="https://example.invalid/openai/v1",
            azure_openai_deployment="d",
            nvidia_api_key="k",
        )
    )
    assert service.is_enabled() is False
    assert "token" not in json.dumps(service.target())


def test_dispatch_sends_only_the_session_id_and_never_logs_the_token(
    monkeypatch,
):
    config = Settings(
        _env_file=None,
        alpaca_api_key="k",
        alpaca_secret_key="s",
        alpaca_paper=True,
        azure_openai_api_key="k",
        azure_openai_endpoint="https://example.invalid/openai/v1",
        azure_openai_deployment="d",
        nvidia_api_key="k",
        regret_github_repository="example/repo",
        regret_github_dispatch_token="TEST_GITHUB_DISPATCH_TOKEN",
    )
    service = GitHubDispatchService(config=config)
    post = MagicMock(return_value=MagicMock(status_code=204))
    monkeypatch.setattr(control_module, "settings", settings)
    monkeypatch.setattr(
        "backend.app.services.github_dispatch_service.requests.post", post
    )

    result = service.dispatch_cycle(arm_session_id="session-abc")

    assert result["dispatched"] is True
    kwargs = post.call_args.kwargs
    assert kwargs["json"]["inputs"] == {"arm_session_id": "session-abc"}
    # The token travels only in the Authorization header.
    assert "TEST_GITHUB_DISPATCH_TOKEN" not in json.dumps(kwargs["json"])
    assert kwargs["headers"]["Authorization"] == "Bearer TEST_GITHUB_DISPATCH_TOKEN"
    assert "TEST_GITHUB_DISPATCH_TOKEN" not in json.dumps(service.target())
