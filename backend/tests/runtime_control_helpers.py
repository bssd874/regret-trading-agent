"""Shared helpers for exercising the operator runtime-control layer."""

from datetime import datetime, timedelta, timezone

from backend.app.models.agent_runtime_control import AgentRuntimeControl
from backend.app.services.runtime_control_service import RuntimeControlService


NOW = datetime(2026, 1, 5, 15, 30, tzinfo=timezone.utc)


class StubDispatcher:
    """Deterministic stand-in for GitHub workflow_dispatch.

    Never performs network I/O, so no real workflow can be triggered by tests.
    """

    def __init__(self, *, enabled: bool = True, error: Exception | None = None):
        self.enabled = enabled
        self.error = error
        self.calls: list[dict] = []

    def is_enabled(self) -> bool:
        return self.enabled

    def target(self) -> dict:
        return {
            "repository": "example/repo",
            "workflow": "autonomous-observe.yml",
            "ref": "main",
            "enabled": self.enabled,
        }

    def dispatch_cycle(self, *, arm_session_id: str) -> dict:
        self.calls.append({"arm_session_id": arm_session_id})
        if self.error is not None:
            raise self.error
        return {
            "dispatched": True,
            "repository": "example/repo",
            "workflow": "autonomous-observe.yml",
            "ref": "main",
            "status_code": 204,
        }


def make_service(
    config,
    *,
    dispatcher: StubDispatcher | None = None,
    now: datetime | None = None,
) -> RuntimeControlService:
    moment = now or NOW
    return RuntimeControlService(
        config=config,
        dispatcher=dispatcher or StubDispatcher(),
        now_provider=lambda: moment,
    )


def seed_control(
    db,
    *,
    state: str = "DISARMED",
    new_entries_armed: bool = False,
    arm_session_id: str | None = None,
    armed_at: datetime | None = None,
    armed_until: datetime | None = None,
    start_requested_at: datetime | None = None,
    request_expires_at: datetime | None = None,
    max_new_executions: int = 1,
    executions_used: int = 0,
    last_disarm_reason: str | None = None,
) -> AgentRuntimeControl:
    control = db.get(AgentRuntimeControl, AgentRuntimeControl.SINGLETON_ID)
    if control is None:
        control = AgentRuntimeControl(id=AgentRuntimeControl.SINGLETON_ID)
        db.add(control)

    control.state = state
    control.new_entries_armed = new_entries_armed
    control.arm_session_id = arm_session_id
    control.armed_at = armed_at
    control.armed_until = armed_until
    control.start_requested_at = start_requested_at
    control.request_expires_at = request_expires_at
    control.max_new_executions = max_new_executions
    control.executions_used = executions_used
    control.last_disarm_reason = last_disarm_reason
    control.created_at = control.created_at or NOW
    control.updated_at = NOW
    db.commit()
    db.refresh(control)
    return control


def seed_armed(
    db,
    *,
    now: datetime | None = None,
    minutes: int = 15,
    max_new_executions: int = 1,
    executions_used: int = 0,
) -> AgentRuntimeControl:
    moment = now or NOW
    return seed_control(
        db,
        state="ARMED",
        new_entries_armed=True,
        arm_session_id="session-armed",
        armed_at=moment,
        armed_until=moment + timedelta(minutes=minutes),
        max_new_executions=max_new_executions,
        executions_used=executions_used,
    )


def armed_service(db, config, *, now: datetime | None = None, **kwargs):
    """Seed an ARMED control row and return a service bound to `config`."""
    moment = now or NOW
    seed_armed(db, now=moment, **kwargs)
    return make_service(config, now=moment)
