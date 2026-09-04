from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.app.services.autonomous_agent_service import (
    AgentCycleAlreadyRunning,
)
from backend.scripts import run_autonomous_cycle_once as once_module
from backend.scripts.run_autonomous_cycle_once import run_cycle_once
from backend.tests.test_autonomous_agent_service import _settings


def test_one_shot_invocation_runs_exactly_one_scheduled_cycle(
    monkeypatch,
    capsys,
):
    create_all = MagicMock()
    monkeypatch.setattr(once_module.Base.metadata, "create_all", create_all)
    agent = MagicMock()
    agent.run_cycle.return_value = SimpleNamespace(id=31, status="COMPLETED")
    session = MagicMock()
    session_factory = MagicMock(return_value=session)
    engine_bind = object()

    result = run_cycle_once(
        config=_settings(
            autonomous_agent_enabled=True,
            paper_execution_enabled=False,
        ),
        agent=agent,
        session_factory=session_factory,
        engine_bind=engine_bind,
    )

    assert result == 0
    create_all.assert_called_once_with(bind=engine_bind)
    session_factory.assert_called_once_with()
    agent.run_cycle.assert_called_once_with(
        db=session,
        trigger="SCHEDULED",
    )
    session.close.assert_called_once_with()
    assert "one-shot process exiting" in capsys.readouterr().out


def test_one_shot_respects_disabled_configuration(monkeypatch, capsys):
    create_all = MagicMock()
    monkeypatch.setattr(once_module.Base.metadata, "create_all", create_all)
    agent = MagicMock()

    result = run_cycle_once(
        config=_settings(autonomous_agent_enabled=False),
        agent=agent,
    )

    assert result == 0
    create_all.assert_not_called()
    agent.run_cycle.assert_not_called()
    assert "disabled" in capsys.readouterr().out.lower()


def test_one_shot_respects_existing_cycle_lock(monkeypatch, capsys):
    monkeypatch.setattr(once_module.Base.metadata, "create_all", MagicMock())
    agent = MagicMock()
    agent.run_cycle.side_effect = AgentCycleAlreadyRunning()
    session = MagicMock()

    result = run_cycle_once(
        config=_settings(autonomous_agent_enabled=True),
        agent=agent,
        session_factory=MagicMock(return_value=session),
    )

    assert result == 0
    agent.run_cycle.assert_called_once_with(
        db=session,
        trigger="SCHEDULED",
    )
    session.close.assert_called_once_with()
    assert "AGENT_CYCLE_ALREADY_RUNNING" in capsys.readouterr().out


def test_one_shot_returns_nonzero_on_initialization_failure(
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(
        once_module.Base.metadata,
        "create_all",
        MagicMock(side_effect=RuntimeError("database unavailable")),
    )
    agent = MagicMock()
    session_factory = MagicMock()

    result = run_cycle_once(
        config=_settings(autonomous_agent_enabled=True),
        agent=agent,
        session_factory=session_factory,
    )

    assert result == 1
    session_factory.assert_not_called()
    agent.run_cycle.assert_not_called()
    assert "initialization failed safely" in capsys.readouterr().out


def test_one_shot_returns_nonzero_on_fatal_cycle_failure(
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(once_module.Base.metadata, "create_all", MagicMock())
    agent = MagicMock()
    agent.run_cycle.side_effect = RuntimeError("fatal provider setup")
    session = MagicMock()

    result = run_cycle_once(
        config=_settings(autonomous_agent_enabled=True),
        agent=agent,
        session_factory=MagicMock(return_value=session),
    )

    assert result == 1
    agent.run_cycle.assert_called_once()
    session.close.assert_called_once_with()
    assert "failed safely" in capsys.readouterr().out


def test_one_shot_observe_configuration_keeps_execution_disabled(monkeypatch):
    monkeypatch.setattr(once_module.Base.metadata, "create_all", MagicMock())
    config = _settings(
        autonomous_agent_enabled=True,
        autonomous_new_entries_enabled=True,
        paper_execution_enabled=False,
    )
    agent = MagicMock()
    agent.config = config
    agent.run_cycle.return_value = SimpleNamespace(id=32, status="COMPLETED")

    result = run_cycle_once(
        config=config,
        agent=agent,
        session_factory=MagicMock(return_value=MagicMock()),
    )

    assert result == 0
    assert agent.config.paper_execution_enabled is False
    agent.run_cycle.assert_called_once()
