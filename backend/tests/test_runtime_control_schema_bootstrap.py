"""Provisioning the runtime-control table on an already-populated database.

The deployed API skips `create_all` on Vercel, so the new table would never
appear on its own. These tests reproduce that exact shape — every table except
`agent_runtime_controls` — and prove the bootstrap fixes it without touching
anything else.

Nothing here contacts Alpaca, an AI provider or a scheduler.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import sessionmaker

from backend.app import models as _models  # noqa: F401
from backend.app.db.database import Base
from backend.app.models.agent_cycle import AgentCycle
from backend.app.models.agent_runtime_control import AgentRuntimeControl
from backend.app.services.runtime_control_service import RuntimeControlService
from backend.scripts.ensure_runtime_control_schema import (
    STATUS_ALREADY_EXISTS,
    STATUS_CREATED,
    TABLE_NAME,
    ensure_runtime_control_schema,
)
from backend.tests.runtime_control_helpers import StubDispatcher
from backend.tests.test_autonomous_agent_service import _settings


NOW = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def legacy_engine(tmp_path):
    """A database shaped like production before this feature: no new table."""
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    tables = [
        table
        for name, table in Base.metadata.tables.items()
        if name != TABLE_NAME
    ]
    Base.metadata.create_all(engine, tables=tables)

    # A pre-existing cycle, so we can prove no data is lost.
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(
        AgentCycle(
            trigger="SCHEDULED",
            status="COMPLETED",
            mode="OBSERVE",
            started_at=NOW,
            heartbeat_at=NOW,
            finished_at=NOW,
            summary_json="{}",
            errors_json="[]",
            created_at=NOW,
        )
    )
    session.commit()
    session.close()
    return engine


def _cycle_ddl(engine) -> str:
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type='table' AND name='agent_cycles'"
            )
        ).scalar_one()


def _run(engine, **kwargs):
    return ensure_runtime_control_schema(
        config=_settings(),
        engine_bind=engine,
        session_factory=sessionmaker(bind=engine),
        environ={},
        **kwargs,
    )


# ---------------------------------------------------------------
# creation and idempotency
# ---------------------------------------------------------------
def test_bootstrap_creates_the_missing_table(legacy_engine, capsys):
    assert inspect(legacy_engine).has_table(TABLE_NAME) is False

    result = _run(legacy_engine)

    output = capsys.readouterr().out
    assert result == 0
    assert inspect(legacy_engine).has_table(TABLE_NAME) is True
    assert f"RUNTIME_CONTROL_TABLE={STATUS_CREATED}" in output
    assert "RUNTIME_CONTROL_TABLE_PRESENT=true" in output


def test_bootstrap_is_idempotent(legacy_engine, capsys):
    first = _run(legacy_engine)
    first_output = capsys.readouterr().out
    second = _run(legacy_engine)
    second_output = capsys.readouterr().out

    assert first == second == 0
    assert f"RUNTIME_CONTROL_TABLE={STATUS_CREATED}" in first_output
    assert f"RUNTIME_CONTROL_TABLE={STATUS_ALREADY_EXISTS}" in second_output
    # Exactly one table, no duplicate schema object.
    names = inspect(legacy_engine).get_table_names()
    assert names.count(TABLE_NAME) == 1


def test_bootstrap_on_an_already_current_database_is_a_no_op(tmp_path, capsys):
    engine = create_engine(f"sqlite:///{tmp_path / 'current.db'}")
    Base.metadata.create_all(engine)

    result = _run(engine)

    assert result == 0
    assert f"RUNTIME_CONTROL_TABLE={STATUS_ALREADY_EXISTS}" in (
        capsys.readouterr().out
    )


# ---------------------------------------------------------------
# non-destructive: nothing else is touched
# ---------------------------------------------------------------
def test_bootstrap_leaves_the_agent_cycle_table_untouched(legacy_engine):
    before_ddl = _cycle_ddl(legacy_engine)
    before_columns = {
        column["name"] for column in inspect(legacy_engine).get_columns("agent_cycles")
    }

    _run(legacy_engine)

    assert _cycle_ddl(legacy_engine) == before_ddl
    assert {
        column["name"]
        for column in inspect(legacy_engine).get_columns("agent_cycles")
    } == before_columns


def test_bootstrap_does_not_alter_the_agent_cycle_trigger_constraint(
    legacy_engine,
):
    """The production CHECK on `trigger` must survive verbatim."""
    before = _cycle_ddl(legacy_engine)
    assert "trigger IN ('SCHEDULED', 'MANUAL')" in before

    _run(legacy_engine)

    after = _cycle_ddl(legacy_engine)
    assert "trigger IN ('SCHEDULED', 'MANUAL')" in after
    assert before == after


def test_bootstrap_preserves_every_existing_row(legacy_engine):
    Session = sessionmaker(bind=legacy_engine)
    session = Session()
    before = session.scalar(select(func.count()).select_from(AgentCycle))
    session.close()
    assert before == 1

    _run(legacy_engine)

    session = Session()
    after = session.scalar(select(func.count()).select_from(AgentCycle))
    cycle = session.scalar(select(AgentCycle))
    session.close()
    assert after == 1
    assert cycle.trigger == "SCHEDULED"
    assert cycle.status == "COMPLETED"


def test_bootstrap_keeps_every_pre_existing_table(legacy_engine):
    before = set(inspect(legacy_engine).get_table_names())

    _run(legacy_engine)

    after = set(inspect(legacy_engine).get_table_names())
    assert before.issubset(after)
    assert after - before == {TABLE_NAME}


# ---------------------------------------------------------------
# runtime semantics after provisioning
# ---------------------------------------------------------------
def test_the_table_starts_empty_and_the_runtime_default_is_disarmed(
    legacy_engine,
):
    _run(legacy_engine)
    Session = sessionmaker(bind=legacy_engine)
    session = Session()

    # Schema creation arms nothing: the table is created empty.
    assert session.scalar(
        select(func.count()).select_from(AgentRuntimeControl)
    ) == 0

    service = RuntimeControlService(
        config=_settings(paper_execution_enabled=True),
        dispatcher=StubDispatcher(),
    )
    # A missing row reads as DISARMED, and the lazily created row agrees.
    assert service.is_entry_armed(session) is False
    control = service.get_or_create(session)
    assert control.state == "DISARMED"
    assert control.new_entries_armed is False
    assert control.executions_used == 0
    assert control.max_new_executions == 1
    assert service.is_entry_armed(session) is False
    session.close()


def test_status_route_recovers_once_the_table_exists(legacy_engine):
    """The 500 this bootstrap exists to prevent."""
    from fastapi.testclient import TestClient

    from backend.app.db.database import get_db
    from backend.app.main import app

    Session = sessionmaker(bind=legacy_engine)
    session = Session()

    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app, raise_server_exceptions=False)
        before = client.get("/api/agent/status")
        session.rollback()

        _run(legacy_engine)

        after = client.get("/api/agent/status")
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.close()

    assert before.status_code == 500
    assert after.status_code == 200
    assert after.json()["runtime_control"]["state"] == "DISARMED"
    assert after.json()["entry_execution_state"] in {
        "DISARMED",
        "MASTER_DISABLED",
    }


# ---------------------------------------------------------------
# fail closed
# ---------------------------------------------------------------
def test_hosted_sqlite_bootstrap_is_refused(legacy_engine, capsys):
    session_factory = MagicMock()

    result = ensure_runtime_control_schema(
        config=_settings(),
        engine_bind=legacy_engine,
        session_factory=session_factory,
        environ={"VERCEL": "1"},
    )

    assert result == 1
    assert "refused to run" in capsys.readouterr().out
    # Nothing was created and no session was opened.
    assert inspect(legacy_engine).has_table(TABLE_NAME) is False
    session_factory.assert_not_called()


@pytest.mark.parametrize(
    "environ", [{"GITHUB_ACTIONS": "true"}, {"CI": "true"}, {"REGRET_REQUIRE_DATABASE_URL": "true"}]
)
def test_every_automation_signal_refuses_sqlite(legacy_engine, environ):
    result = ensure_runtime_control_schema(
        config=_settings(),
        engine_bind=legacy_engine,
        session_factory=MagicMock(),
        environ=environ,
    )
    assert result == 1
    assert inspect(legacy_engine).has_table(TABLE_NAME) is False


def test_a_configured_postgres_url_is_accepted_in_automation(legacy_engine):
    """The guard targets an unconfigured SQLite fallback, not automation."""
    result = ensure_runtime_control_schema(
        config=_settings(
            database_url=(
                "postgresql+psycopg://TEST_USER:TEST_PASSWORD"
                "@fake.invalid/test_db"
            )
        ),
        engine_bind=legacy_engine,
        session_factory=sessionmaker(bind=legacy_engine),
        environ={"GITHUB_ACTIONS": "true"},
    )
    assert result == 0
    assert inspect(legacy_engine).has_table(TABLE_NAME) is True


def test_bootstrap_reports_a_failure_without_leaking_detail(capsys):
    # Not an Engine at all, so SQLAlchemy inspection genuinely raises.
    not_an_engine = object()

    result = ensure_runtime_control_schema(
        config=_settings(),
        engine_bind=not_an_engine,
        session_factory=MagicMock(),
        environ={},
    )

    output = capsys.readouterr().out
    assert result == 1
    assert "failed safely" in output
    assert "://" not in output


# ---------------------------------------------------------------
# the bootstrap is not a trading surface
# ---------------------------------------------------------------
def test_bootstrap_contacts_no_provider_and_submits_no_order(
    legacy_engine,
    monkeypatch,
):
    from backend.app.services import market_scout as scout_module
    from backend.app.services.paper_execution_service import (
        paper_execution_service,
    )

    submit = MagicMock()
    sell = MagicMock()
    scout = MagicMock()
    monkeypatch.setattr(
        paper_execution_service, "submit_long_market_order", submit
    )
    monkeypatch.setattr(
        paper_execution_service, "sell_long_market_position", sell
    )
    monkeypatch.setattr(scout_module.market_scout, "run", scout)

    assert _run(legacy_engine) == 0

    submit.assert_not_called()
    sell.assert_not_called()
    scout.assert_not_called()


def test_bootstrap_output_carries_no_connection_material(
    legacy_engine, capsys
):
    _run(legacy_engine)
    output = capsys.readouterr().out
    for forbidden in ("://", "@", "TEST_PASSWORD", "sqlite:///", "password"):
        assert forbidden not in output
