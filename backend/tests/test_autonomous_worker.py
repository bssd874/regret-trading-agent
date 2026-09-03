from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.scripts import run_autonomous_agent as worker_module
from backend.scripts.run_autonomous_agent import run_worker
from backend.tests.test_autonomous_agent_service import _settings


def test_worker_exits_safely_when_autonomy_is_disabled(capsys):
    agent = MagicMock()

    result = run_worker(
        config=_settings(autonomous_agent_enabled=False),
        agent=agent,
    )

    assert result == 0
    assert "disabled" in capsys.readouterr().out.lower()
    agent.run_cycle.assert_not_called()


def test_worker_continues_after_one_cycle_error(monkeypatch, capsys):
    monkeypatch.setattr(worker_module.Base.metadata, "create_all", MagicMock())
    agent = MagicMock()
    agent.mode.return_value = "OBSERVE"
    agent.run_cycle.side_effect = [
        RuntimeError("temporary provider failure"),
        SimpleNamespace(id=2, status="COMPLETED"),
    ]
    sessions = [MagicMock(), MagicMock()]
    session_factory = MagicMock(side_effect=sessions)
    sleep_calls = 0

    def stop_after_two_ticks(_seconds):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls == 2:
            raise KeyboardInterrupt

    result = run_worker(
        config=_settings(autonomous_agent_enabled=True),
        agent=agent,
        session_factory=session_factory,
        sleep=stop_after_two_ticks,
    )

    assert result == 0
    assert agent.run_cycle.call_count == 2
    assert all(session.close.called for session in sessions)
    output = capsys.readouterr().out
    assert "failed safely; worker will continue" in output
    assert "AgentCycle 2 finished with status COMPLETED" in output
