"""Automation must fail closed on SQLite, and diagnose safely otherwise."""

from unittest.mock import MagicMock

import pytest

from backend.app.services import db_diagnostics
from backend.app.services.db_diagnostics import (
    SQLITE_IN_AUTOMATION_MESSAGE,
    automation_database_error,
    collect_database_identity,
    diagnostic_only_requested,
    format_diagnostic,
    in_automation,
    safe_db_fingerprint,
)
from backend.scripts import run_autonomous_cycle_once as once_module
from backend.scripts.run_autonomous_cycle_once import (
    run_cycle_once,
    run_database_diagnostic,
)
from backend.tests.test_autonomous_agent_service import _settings


SECRET_SHAPED = (
    "postgresql+psycopg://regret_user:sup3r-s3cret@ep-x.aws.neon.tech/regret"
)


# ---------------------------------------------------------------
# automation detection
# ---------------------------------------------------------------
@pytest.mark.parametrize(
    "environ,expected",
    [
        ({}, False),
        ({"GITHUB_ACTIONS": "true"}, True),
        ({"CI": "true"}, True),
        ({"VERCEL": "1"}, True),
        ({"REGRET_REQUIRE_DATABASE_URL": "true"}, True),
        ({"GITHUB_ACTIONS": "false"}, False),
        ({"CI": ""}, False),
    ],
)
def test_automation_detection(environ, expected):
    assert in_automation(environ) is expected


def test_diagnostic_flag_is_read_from_the_environment():
    assert diagnostic_only_requested({"REGRET_DIAGNOSTIC_ONLY": "true"}) is True
    assert diagnostic_only_requested({"REGRET_DIAGNOSTIC_ONLY": "false"}) is False
    assert diagnostic_only_requested({}) is False


# ---------------------------------------------------------------
# fail closed: no silent SQLite in automation
# ---------------------------------------------------------------
def test_sqlite_in_automation_is_refused():
    config = _settings()
    assert config.database_url.startswith("sqlite")
    assert automation_database_error(
        config, {"GITHUB_ACTIONS": "true"}
    ) == SQLITE_IN_AUTOMATION_MESSAGE


def test_sqlite_outside_automation_remains_the_local_default():
    config = _settings()
    assert automation_database_error(config, {}) is None


def test_configured_postgres_in_automation_is_accepted():
    config = _settings(database_url=SECRET_SHAPED)
    assert automation_database_error(config, {"GITHUB_ACTIONS": "true"}) is None


def test_one_shot_fails_closed_in_automation_without_a_database_url(
    monkeypatch,
    capsys,
):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    create_all = MagicMock()
    monkeypatch.setattr(once_module.Base.metadata, "create_all", create_all)
    agent = MagicMock()
    session_factory = MagicMock()

    result = run_cycle_once(
        config=_settings(autonomous_agent_enabled=True),
        agent=agent,
        session_factory=session_factory,
    )

    assert result == 1
    # Nothing was touched: no schema work, no session, no cycle.
    create_all.assert_not_called()
    session_factory.assert_not_called()
    agent.run_cycle.assert_not_called()
    assert "refused to run" in capsys.readouterr().out


def test_one_shot_still_runs_locally_on_sqlite(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setattr(once_module.Base.metadata, "create_all", MagicMock())
    agent = MagicMock()
    agent.run_cycle.return_value = MagicMock(id=99, status="COMPLETED")

    result = run_cycle_once(
        config=_settings(autonomous_agent_enabled=True),
        agent=agent,
        session_factory=MagicMock(return_value=MagicMock()),
    )

    assert result == 0
    agent.run_cycle.assert_called_once()


# ---------------------------------------------------------------
# diagnostic mode is read-only and inert
# ---------------------------------------------------------------
def test_diagnostic_reports_safe_identity_for_the_current_database(db_session):
    report = collect_database_identity(db_session)

    assert report["db_engine"] == "sqlite"
    assert report["db_name"] == "local-sqlite"
    assert report["agent_cycle_count"] == 0
    assert report["latest_agent_cycle_id"] is None
    assert report["executed_trade_count"] == 0
    assert report["shadow_trade_count"] == 0
    assert report["runtime_control_present"] is True
    assert len(report["safe_db_fingerprint"]) == 64


def test_diagnostic_mode_never_runs_the_agent_or_contacts_providers(
    monkeypatch,
    db_session,
    capsys,
):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("CI", raising=False)

    agent = MagicMock()
    monkeypatch.setattr(once_module, "autonomous_agent", agent)
    submit_order = MagicMock()
    monkeypatch.setattr(
        "backend.app.services.paper_execution_service."
        "paper_execution_service.submit_long_market_order",
        submit_order,
    )
    sell = MagicMock()
    monkeypatch.setattr(
        "backend.app.services.paper_execution_service."
        "paper_execution_service.sell_long_market_position",
        sell,
    )
    scout = MagicMock()
    monkeypatch.setattr("backend.app.services.market_scout.market_scout.run", scout)
    pipeline = MagicMock()
    monkeypatch.setattr(
        "backend.app.services.decision_pipeline.decision_pipeline.run", pipeline
    )

    result = run_database_diagnostic(
        config=_settings(),
        session_factory=MagicMock(return_value=db_session),
    )

    assert result == 0
    agent.run_cycle.assert_not_called()
    submit_order.assert_not_called()
    sell.assert_not_called()
    scout.assert_not_called()
    pipeline.assert_not_called()
    assert "DB_ENGINE=sqlite" in capsys.readouterr().out


def test_diagnostic_creates_no_rows(db_session):
    from sqlalchemy import func, select

    from backend.app.models.agent_cycle import AgentCycle

    before = db_session.scalar(select(func.count()).select_from(AgentCycle))
    collect_database_identity(db_session)
    after = db_session.scalar(select(func.count()).select_from(AgentCycle))
    assert before == after == 0


def test_diagnostic_fails_closed_in_automation_without_a_database_url(
    monkeypatch,
    capsys,
):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    session_factory = MagicMock()

    result = run_database_diagnostic(
        config=_settings(),
        session_factory=session_factory,
    )

    assert result == 1
    session_factory.assert_not_called()
    assert "refused to run" in capsys.readouterr().out


def test_diagnostic_returns_nonzero_when_the_database_is_unreachable(
    monkeypatch,
    capsys,
):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("CI", raising=False)

    def explode():
        raise RuntimeError("could not connect")

    result = run_database_diagnostic(
        config=_settings(),
        session_factory=explode,
    )

    output = capsys.readouterr().out
    assert result == 1
    assert "failed safely" in output
    assert "could not connect" not in output


# ---------------------------------------------------------------
# secret containment
# ---------------------------------------------------------------
def test_diagnostic_output_contains_no_connection_material(db_session, capsys):
    run_database_diagnostic(
        config=_settings(database_url="sqlite:///./regret.db"),
        session_factory=MagicMock(return_value=db_session),
    )
    output = capsys.readouterr().out

    for forbidden in (
        "postgresql",
        "psycopg",
        "neon.tech",
        "sup3r-s3cret",
        "regret_user",
        "5432",
        "sslmode",
        "@",
        "://",
    ):
        assert forbidden not in output, f"diagnostic leaked {forbidden!r}"

    assert set(
        line.split("=", 1)[0] for line in output.strip().splitlines()
    ) == {
        "DB_ENGINE",
        "DB_NAME",
        "AGENT_CYCLE_COUNT",
        "LATEST_AGENT_CYCLE_ID",
        "EXECUTED_TRADE_COUNT",
        "SHADOW_TRADE_COUNT",
        "RUNTIME_CONTROL_PRESENT",
        "SAFE_DB_FINGERPRINT",
    }


def test_fingerprint_is_stable_and_derived_only_from_non_secret_identity():
    first = safe_db_fingerprint("postgresql", "regret", "16401")
    again = safe_db_fingerprint("postgresql", "regret", "16401")
    other = safe_db_fingerprint("postgresql", "regret_other", "16401")

    assert first == again
    assert first != other
    assert len(first) == 64
    # The digest is not derived from, and cannot disclose, the credentials.
    assert "sup3r-s3cret" not in first


def test_formatted_diagnostic_renders_a_missing_cycle_id_as_none():
    lines = format_diagnostic(
        {
            "db_engine": "postgresql",
            "db_name": "regret",
            "agent_cycle_count": 0,
            "latest_agent_cycle_id": None,
            "executed_trade_count": 0,
            "shadow_trade_count": 0,
            "runtime_control_present": False,
            "safe_db_fingerprint": "abc",
        }
    )
    assert "LATEST_AGENT_CYCLE_ID=none" in lines
    assert "RUNTIME_CONTROL_PRESENT=false" in lines


def test_module_exposes_the_documented_automation_variables():
    assert db_diagnostics.AUTOMATION_ENV_VARS == ("GITHUB_ACTIONS", "CI", "VERCEL")
    assert db_diagnostics.DIAGNOSTIC_ONLY_ENV_VAR == "REGRET_DIAGNOSTIC_ONLY"
