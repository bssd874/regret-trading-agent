import inspect

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from backend.app.core.config import Settings
from backend.app.db.database import build_engine
from backend.app.main import app, health
from backend.app.models.agent_cycle import AgentCycle


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


def test_database_url_absent_uses_sqlite_development_fallback():
    configured = Settings(_env_file=None, **_settings_values())
    assert configured.database_url == "sqlite:///./regret.db"


@pytest.mark.parametrize("scheme", ["postgres://", "postgresql://"])
def test_hosted_postgres_url_uses_psycopg_driver(scheme):
    configured = Settings(
        _env_file=None,
        **_settings_values(
            database_url=f"{scheme}user:password@db.example:5432/regret"
        ),
    )
    assert configured.database_url.startswith("postgresql+psycopg://")
    engine = build_engine(configured.database_url)
    try:
        assert engine.url.drivername == "postgresql+psycopg"
        assert engine.url.database == "regret"
        assert engine.url.host == "db.example"
    finally:
        engine.dispose()


def test_public_agent_trigger_defaults_disabled():
    configured = Settings(_env_file=None, **_settings_values())
    assert configured.public_agent_trigger_enabled is False


def test_running_cycle_unique_index_is_partial_on_postgres():
    index = next(
        item
        for item in AgentCycle.__table__.indexes
        if item.name == "uq_agent_cycles_one_running"
    )
    ddl = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    assert "UNIQUE INDEX" in ddl
    assert "WHERE status = 'RUNNING'" in ddl


def test_cors_origins_parse_comma_separated_and_json_values():
    comma = Settings(
        _env_file=None,
        **_settings_values(
            cors_allowed_origins="https://demo.example,http://localhost:3000/"
        ),
    )
    encoded = Settings(
        _env_file=None,
        **_settings_values(cors_allowed_origins='["https://demo.example"]'),
    )
    assert comma.cors_allowed_origins == [
        "https://demo.example",
        "http://localhost:3000",
    ]
    assert encoded.cors_allowed_origins == ["https://demo.example"]


@pytest.mark.parametrize(
    "origins",
    ["*", "ftp://demo.example", "https://user:password@demo.example", ""],
)
def test_cors_rejects_unsafe_or_empty_origins(origins):
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            **_settings_values(cors_allowed_origins=origins),
        )


def test_health_endpoint_is_inexpensive_and_mutation_free():
    response = TestClient(app).get("/health")
    source = inspect.getsource(health)
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "REGRET",
        "paper_trading": True,
    }
    for forbidden in (
        "run_cycle",
        "market_scout",
        "decision_pipeline",
        "submit_order",
        "alpaca_service",
        "db.add",
        "db.commit",
    ):
        assert forbidden not in source
