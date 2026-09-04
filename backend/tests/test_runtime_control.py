"""Operator runtime-control state model, TTLs, budget and dispatch."""

from datetime import timedelta

import pytest

from backend.app.models.agent_runtime_control import AgentRuntimeControl
from backend.app.services.github_dispatch_service import GitHubDispatchError
from backend.app.services.runtime_control_service import (
    ENTRY_ARMED,
    ENTRY_BUDGET_EXHAUSTED,
    ENTRY_DISARMED,
    ENTRY_EXPIRED,
    ENTRY_MASTER_DISABLED,
    ENTRY_STARTING,
    RuntimeControlConflict,
    RuntimeControlUnavailable,
)
from backend.tests.runtime_control_helpers import (
    NOW,
    StubDispatcher,
    make_service,
    seed_control,
)
from backend.tests.test_autonomous_agent_service import _settings


def _config(**overrides):
    values = {"paper_execution_enabled": True}
    values.update(overrides)
    return _settings(**values)


# ---------------------------------------------------------------
# 1-2 safe defaults
# ---------------------------------------------------------------
def test_missing_control_row_is_disarmed(db_session):
    service = make_service(_config())
    assert service.get_control(db_session) is None
    assert service.is_entry_armed(db_session) is False
    assert service.snapshot(db_session)["entry_execution_state"] == (
        ENTRY_DISARMED
    )


def test_freshly_created_control_row_is_disarmed(db_session):
    service = make_service(_config())
    control = service.get_or_create(db_session)
    assert control.state == "DISARMED"
    assert control.new_entries_armed is False
    assert control.executions_used == 0
    assert service.is_entry_armed(db_session) is False


# ---------------------------------------------------------------
# 3-5 arm request and session claim
# ---------------------------------------------------------------
def test_arm_request_moves_to_start_requested_but_not_armed(db_session):
    dispatcher = StubDispatcher()
    service = make_service(_config(), dispatcher=dispatcher)

    snapshot = service.request_arm(db_session)

    control = service.get_control(db_session)
    assert control.state == "START_REQUESTED"
    assert control.new_entries_armed is False
    assert snapshot["entry_execution_state"] == ENTRY_STARTING
    assert snapshot["effective_new_entries_armed"] is False
    assert len(dispatcher.calls) == 1


def test_start_requested_cannot_open_a_new_position(db_session):
    service = make_service(_config(), dispatcher=StubDispatcher())
    service.request_arm(db_session)
    assert service.is_entry_armed(db_session) is False


def test_successful_session_claim_arms_the_agent(db_session):
    service = make_service(_config(), dispatcher=StubDispatcher())
    service.request_arm(db_session)
    session_id = service.get_control(db_session).arm_session_id

    result = service.claim_session(db_session, session_id)

    assert result["claimed"] is True
    control = service.get_control(db_session)
    assert control.state == "ARMED"
    assert control.new_entries_armed is True
    # SQLite returns naive datetimes; the service normalizes on read.
    assert service.snapshot(db_session)["armed_until"] == (
        NOW + timedelta(minutes=15)
    )
    assert service.is_entry_armed(db_session) is True


# ---------------------------------------------------------------
# 6-8 fail-closed paths
# ---------------------------------------------------------------
def test_wrong_session_id_fails_closed(db_session):
    service = make_service(_config(), dispatcher=StubDispatcher())
    service.request_arm(db_session)

    result = service.claim_session(db_session, "not-the-session")

    assert result["claimed"] is False
    assert result["reason"] == "SESSION_MISMATCH"
    assert service.get_control(db_session).state == "START_REQUESTED"
    assert service.is_entry_armed(db_session) is False


def test_expired_start_request_cannot_be_claimed_later(db_session):
    seed_control(
        db_session,
        state="START_REQUESTED",
        arm_session_id="stale-session",
        start_requested_at=NOW - timedelta(minutes=30),
        request_expires_at=NOW - timedelta(minutes=25),
    )
    service = make_service(_config())

    assert service.entry_execution_state(
        service.get_control(db_session)
    ) == ENTRY_EXPIRED

    result = service.claim_session(db_session, "stale-session")

    assert result["claimed"] is False
    assert result["reason"] == "START_REQUEST_EXPIRED"
    control = service.get_control(db_session)
    assert control.state == "DISARMED"
    assert service.is_entry_armed(db_session) is False


def test_expired_arm_ttl_is_treated_as_disarmed(db_session):
    seed_control(
        db_session,
        state="ARMED",
        new_entries_armed=True,
        armed_at=NOW - timedelta(minutes=60),
        armed_until=NOW - timedelta(minutes=45),
    )
    service = make_service(_config())

    assert service.entry_execution_state(
        service.get_control(db_session)
    ) == ENTRY_EXPIRED
    # Persisted flag still says armed; effective permission must not.
    assert service.get_control(db_session).new_entries_armed is True
    assert service.is_entry_armed(db_session) is False


# ---------------------------------------------------------------
# 9-11 disarm, budget, master override
# ---------------------------------------------------------------
def test_manual_disarm_is_immediate_and_idempotent(db_session):
    service = make_service(_config(), dispatcher=StubDispatcher())
    service.request_arm(db_session)
    service.claim_session(
        db_session, service.get_control(db_session).arm_session_id
    )
    assert service.is_entry_armed(db_session) is True

    first = service.disarm(db_session)
    second = service.disarm(db_session)

    assert first["effective_new_entries_armed"] is False
    assert second["effective_new_entries_armed"] is False
    control = service.get_control(db_session)
    assert control.state == "DISARMED"
    assert control.last_disarm_reason == "OPERATOR_DISARM"


def test_exhausted_budget_reports_budget_exhausted_and_blocks_entry(
    db_session,
):
    seed_control(
        db_session,
        state="ARMED",
        new_entries_armed=True,
        armed_at=NOW,
        armed_until=NOW + timedelta(minutes=15),
        max_new_executions=1,
        executions_used=1,
    )
    service = make_service(_config())

    assert service.entry_execution_state(
        service.get_control(db_session)
    ) == ENTRY_BUDGET_EXHAUSTED
    assert service.is_entry_armed(db_session) is False


def test_master_execution_disabled_overrides_a_persisted_arm(db_session):
    seed_control(
        db_session,
        state="ARMED",
        new_entries_armed=True,
        armed_at=NOW,
        armed_until=NOW + timedelta(minutes=15),
    )
    service = make_service(_config(paper_execution_enabled=False))

    assert service.entry_execution_state(
        service.get_control(db_session)
    ) == ENTRY_MASTER_DISABLED
    assert service.is_entry_armed(db_session) is False
    with pytest.raises(RuntimeControlUnavailable) as exc:
        service.request_arm(db_session)
    assert exc.value.code == "MASTER_EXECUTION_DISABLED"


def test_arm_request_requires_configured_dispatch(db_session):
    service = make_service(
        _config(), dispatcher=StubDispatcher(enabled=False)
    )
    with pytest.raises(RuntimeControlUnavailable) as exc:
        service.request_arm(db_session)
    assert exc.value.code == "DISPATCH_DISABLED"
    assert service.get_control(db_session) is None


# ---------------------------------------------------------------
# 13-15 dispatch behaviour
# ---------------------------------------------------------------
def test_arm_request_dispatches_exactly_one_workflow_with_only_session_id(
    db_session,
):
    dispatcher = StubDispatcher()
    service = make_service(_config(), dispatcher=dispatcher)

    service.request_arm(db_session)

    assert len(dispatcher.calls) == 1
    call = dispatcher.calls[0]
    assert set(call) == {"arm_session_id"}
    assert call["arm_session_id"] == (
        service.get_control(db_session).arm_session_id
    )


def test_dispatch_failure_auto_disarms_the_request(db_session):
    dispatcher = StubDispatcher(
        error=GitHubDispatchError("boom", code="DISPATCH_FAILED")
    )
    service = make_service(_config(), dispatcher=dispatcher)

    with pytest.raises(RuntimeControlUnavailable) as exc:
        service.request_arm(db_session)

    assert exc.value.code == "DISPATCH_FAILED"
    control = service.get_control(db_session)
    assert control.state == "DISARMED"
    assert control.new_entries_armed is False
    assert control.last_disarm_reason == "DISPATCH_FAILED"
    assert service.is_entry_armed(db_session) is False


# ---------------------------------------------------------------
# 16-17 idempotency / conflict
# ---------------------------------------------------------------
def test_duplicate_arm_while_start_requested_conflicts(db_session):
    dispatcher = StubDispatcher()
    service = make_service(_config(), dispatcher=dispatcher)
    service.request_arm(db_session)

    with pytest.raises(RuntimeControlConflict) as exc:
        service.request_arm(db_session)

    assert exc.value.code == "ALREADY_ACTIVE"
    assert len(dispatcher.calls) == 1


def test_duplicate_arm_while_armed_conflicts(db_session):
    dispatcher = StubDispatcher()
    service = make_service(_config(), dispatcher=dispatcher)
    service.request_arm(db_session)
    service.claim_session(
        db_session, service.get_control(db_session).arm_session_id
    )

    with pytest.raises(RuntimeControlConflict):
        service.request_arm(db_session)

    assert len(dispatcher.calls) == 1


# ---------------------------------------------------------------
# 19-20 single claim
# ---------------------------------------------------------------
def test_session_can_only_be_claimed_once(db_session):
    service = make_service(_config(), dispatcher=StubDispatcher())
    service.request_arm(db_session)
    session_id = service.get_control(db_session).arm_session_id

    first = service.claim_session(db_session, session_id)
    second = service.claim_session(db_session, session_id)

    assert first["claimed"] is True
    assert second["claimed"] is False
    assert second["reason"] == "NOT_START_REQUESTED"


def test_consume_execution_spends_budget_and_auto_disarms(db_session):
    seed_control(
        db_session,
        state="ARMED",
        new_entries_armed=True,
        armed_at=NOW,
        armed_until=NOW + timedelta(minutes=15),
    )
    service = make_service(_config())

    result = service.consume_execution(db_session, cycle_id=42)

    assert result["consumed"] is True
    assert result["executions_used"] == 1
    assert result["auto_disarmed"] is True
    control = service.get_control(db_session)
    assert control.state == "DISARMED"
    assert control.new_entries_armed is False
    assert control.last_disarm_reason == "EXECUTION_BUDGET_USED"
    assert control.last_cycle_id == 42
    assert service.is_entry_armed(db_session) is False


def test_consume_execution_is_rejected_when_not_armed(db_session):
    seed_control(db_session, state="DISARMED")
    service = make_service(_config())

    result = service.consume_execution(db_session)

    assert result["consumed"] is False
    assert db_session.get(
        AgentRuntimeControl, AgentRuntimeControl.SINGLETON_ID
    ).executions_used == 0


def test_snapshot_never_exposes_the_session_id_by_default(db_session):
    service = make_service(_config(), dispatcher=StubDispatcher())
    service.request_arm(db_session)

    public = service.snapshot(db_session)
    internal = service.snapshot(db_session, include_session_id=True)

    assert "arm_session_id" not in public
    assert internal["arm_session_id"]


def test_snapshot_reports_remaining_seconds_while_armed(db_session):
    seed_control(
        db_session,
        state="ARMED",
        new_entries_armed=True,
        armed_at=NOW,
        armed_until=NOW + timedelta(minutes=15),
    )
    service = make_service(_config())

    snapshot = service.snapshot(db_session)

    assert snapshot["entry_execution_state"] == ENTRY_ARMED
    assert snapshot["seconds_remaining"] == 900
    assert snapshot["executions_used"] == 0
    assert snapshot["max_new_executions"] == 1
