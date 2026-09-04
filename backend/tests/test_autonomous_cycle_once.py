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
        lifecycle_only=True,
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
        lifecycle_only=True,
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


# ---------------------------------------------------------------
# Arm session claim (19-20)
# ---------------------------------------------------------------
def _claiming_runtime(result, *, armed=True):
    runtime = MagicMock()
    runtime.claim_session.return_value = result
    runtime.is_entry_armed.return_value = armed
    return runtime


def test_one_shot_claims_the_arm_session_before_running_the_cycle(
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(once_module.Base.metadata, "create_all", MagicMock())
    agent = MagicMock()
    agent.run_cycle.return_value = SimpleNamespace(id=41, status="COMPLETED")
    session = MagicMock()
    runtime = _claiming_runtime({"claimed": True})

    result = run_cycle_once(
        config=_settings(
            autonomous_agent_enabled=True,
            paper_execution_enabled=True,
        ),
        agent=agent,
        session_factory=MagicMock(return_value=session),
        arm_session_id="session-xyz",
        runtime_control=runtime,
    )

    assert result == 0
    runtime.claim_session.assert_called_once_with(session, "session-xyz")
    agent.run_cycle.assert_called_once_with(
        db=session,
        trigger="SCHEDULED",
        lifecycle_only=False,
    )
    assert "ARMED" in capsys.readouterr().out


def test_unclaimable_session_still_runs_the_cycle_without_arming(
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(once_module.Base.metadata, "create_all", MagicMock())
    agent = MagicMock()
    agent.run_cycle.return_value = SimpleNamespace(id=42, status="COMPLETED")
    session = MagicMock()
    runtime = _claiming_runtime(
        {"claimed": False, "reason": "SESSION_MISMATCH"},
        armed=False,
    )

    result = run_cycle_once(
        config=_settings(
            autonomous_agent_enabled=True,
            paper_execution_enabled=True,
        ),
        agent=agent,
        session_factory=MagicMock(return_value=session),
        arm_session_id="wrong-session",
        runtime_control=runtime,
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "NOT claimed" in output
    assert "SESSION_MISMATCH" in output
    # The cycle still runs, but with no entry permission it stays on the
    # cheap lifecycle half.
    agent.run_cycle.assert_called_once_with(
        db=session,
        trigger="SCHEDULED",
        lifecycle_only=True,
    )


def test_scheduled_run_without_a_session_never_claims_or_arms(monkeypatch):
    monkeypatch.setattr(once_module.Base.metadata, "create_all", MagicMock())
    agent = MagicMock()
    agent.run_cycle.return_value = SimpleNamespace(id=43, status="COMPLETED")
    runtime = MagicMock()

    result = run_cycle_once(
        config=_settings(
            autonomous_agent_enabled=True,
            paper_execution_enabled=True,
        ),
        agent=agent,
        session_factory=MagicMock(return_value=MagicMock()),
        arm_session_id=None,
        runtime_control=runtime,
    )

    assert result == 0
    runtime.claim_session.assert_not_called()
    agent.run_cycle.assert_called_once()


def test_cli_reads_the_arm_session_from_argument_or_environment(monkeypatch):
    parser = once_module.build_parser()
    assert parser.parse_args([]).arm_session_id is None
    assert parser.parse_args(
        ["--arm-session-id", "from-cli"]
    ).arm_session_id == "from-cli"

    captured = {}

    def fake_run(*, arm_session_id=None):
        captured["arm_session_id"] = arm_session_id
        return 0

    monkeypatch.setattr(once_module, "run_cycle_once", fake_run)
    monkeypatch.setenv(once_module.ARM_SESSION_ENV_VAR, "from-env")

    assert once_module.main([]) == 0
    assert captured["arm_session_id"] == "from-env"

    assert once_module.main(["--arm-session-id", "from-cli"]) == 0
    assert captured["arm_session_id"] == "from-cli"
