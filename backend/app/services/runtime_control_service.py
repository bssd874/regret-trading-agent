"""Persisted operator permission for opening NEW autonomous paper positions.

This is deliberately the *second* safety layer. The effective permission is:

    ALPACA_PAPER
    AND PAPER_EXECUTION_ENABLED
    AND state == ARMED (not expired)
    AND executions_used < max_new_executions

An arm can therefore never override the deployment master switch, and an
expired or exhausted session can never permit a new BUY.

Nothing here gates exits. Reconciliation, position monitoring, TAKE_PROFIT,
STOP_LOSS, TIME_EXIT and outcome evaluation are independent of this state by
construction, so disarming can never strand an open position.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import Settings, settings
from backend.app.models.agent_runtime_control import AgentRuntimeControl
from backend.app.services.github_dispatch_service import (
    GitHubDispatchError,
    GitHubDispatchService,
    github_dispatch_service,
)


STATE_DISARMED = "DISARMED"
STATE_START_REQUESTED = "START_REQUESTED"
STATE_ARMED = "ARMED"

# Derived, operator-facing entry state.
ENTRY_MASTER_DISABLED = "MASTER_DISABLED"
ENTRY_DISARMED = "DISARMED"
ENTRY_STARTING = "STARTING"
ENTRY_ARMED = "ARMED"
ENTRY_EXPIRED = "EXPIRED"
ENTRY_BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"

HOLD_REASON_RUNTIME_DISARMED = "RUNTIME_ENTRY_DISARMED"


class RuntimeControlError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class RuntimeControlConflict(RuntimeControlError):
    """The requested transition conflicts with the persisted state."""


class RuntimeControlUnavailable(RuntimeControlError):
    """The control plane cannot honour the request in this configuration."""


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class RuntimeControlService:
    def __init__(
        self,
        *,
        config: Settings = settings,
        dispatcher: GitHubDispatchService = github_dispatch_service,
        now_provider=None,
    ) -> None:
        self.config = config
        self.dispatcher = dispatcher
        self.now_provider = now_provider or (
            lambda: datetime.now(timezone.utc)
        )

    # -----------------------------------------------------
    # Persistence helpers
    # -----------------------------------------------------
    def _now(self) -> datetime:
        return _aware(self.now_provider())

    def get_control(self, db: Session) -> AgentRuntimeControl | None:
        return db.scalar(
            select(AgentRuntimeControl).where(
                AgentRuntimeControl.id == AgentRuntimeControl.SINGLETON_ID
            )
        )

    def get_or_create(self, db: Session) -> AgentRuntimeControl:
        control = self.get_control(db)
        if control is not None:
            return control

        now = self._now()
        control = AgentRuntimeControl(
            id=AgentRuntimeControl.SINGLETON_ID,
            state=STATE_DISARMED,
            new_entries_armed=False,
            max_new_executions=self.config.runtime_max_new_executions,
            executions_used=0,
            created_at=now,
            updated_at=now,
        )
        db.add(control)
        try:
            db.commit()
        except IntegrityError:
            # Another writer created the singleton first.
            db.rollback()
            existing = self.get_control(db)
            if existing is None:
                raise
            return existing
        db.refresh(control)
        return control

    # -----------------------------------------------------
    # Derived state
    # -----------------------------------------------------
    def master_execution_available(self) -> bool:
        return bool(
            self.config.alpaca_paper
            and self.config.paper_execution_enabled
        )

    def entry_execution_state(
        self,
        control: AgentRuntimeControl | None,
        *,
        now: datetime | None = None,
    ) -> str:
        if not self.master_execution_available():
            return ENTRY_MASTER_DISABLED
        if control is None:
            return ENTRY_DISARMED

        moment = now or self._now()
        state = str(control.state or STATE_DISARMED).upper()

        if state == STATE_START_REQUESTED:
            expires = _aware(control.request_expires_at)
            if expires is None or moment >= expires:
                return ENTRY_EXPIRED
            return ENTRY_STARTING

        if state == STATE_ARMED:
            if control.executions_used >= control.max_new_executions:
                return ENTRY_BUDGET_EXHAUSTED
            armed_until = _aware(control.armed_until)
            if armed_until is None or moment >= armed_until:
                return ENTRY_EXPIRED
            if not control.new_entries_armed:
                return ENTRY_DISARMED
            return ENTRY_ARMED

        return ENTRY_DISARMED

    def effective_new_entries_armed(
        self,
        control: AgentRuntimeControl | None,
        *,
        now: datetime | None = None,
    ) -> bool:
        return self.entry_execution_state(control, now=now) == ENTRY_ARMED

    def is_entry_armed(self, db: Session) -> bool:
        """Effective permission to open ONE new paper position right now."""
        return self.effective_new_entries_armed(self.get_control(db))

    # -----------------------------------------------------
    # Read-only projections
    # -----------------------------------------------------
    def snapshot(
        self,
        db: Session,
        *,
        include_session_id: bool = False,
    ) -> dict:
        control = self.get_control(db)
        now = self._now()
        entry_state = self.entry_execution_state(control, now=now)

        payload = {
            "state": (
                str(control.state) if control is not None else STATE_DISARMED
            ),
            "new_entries_armed": (
                bool(control.new_entries_armed)
                if control is not None
                else False
            ),
            "effective_new_entries_armed": (
                entry_state == ENTRY_ARMED
            ),
            "entry_execution_state": entry_state,
            "master_execution_available": self.master_execution_available(),
            "armed_at": _aware(control.armed_at) if control else None,
            "armed_until": _aware(control.armed_until) if control else None,
            "request_expires_at": (
                _aware(control.request_expires_at) if control else None
            ),
            "start_requested_at": (
                _aware(control.start_requested_at) if control else None
            ),
            "executions_used": (
                int(control.executions_used) if control else 0
            ),
            "max_new_executions": (
                int(control.max_new_executions)
                if control
                else self.config.runtime_max_new_executions
            ),
            "last_disarm_reason": (
                control.last_disarm_reason if control else None
            ),
            "last_cycle_id": control.last_cycle_id if control else None,
            "arm_ttl_minutes": self.config.runtime_arm_ttl_minutes,
            "seconds_remaining": self._seconds_remaining(
                control, entry_state, now
            ),
            "dispatch_configured": self.dispatcher.is_enabled(),
        }

        # The session id is an internal correlation value; it is not a
        # credential but there is no reason to publish it, so it is opt-in.
        if include_session_id and control is not None:
            payload["arm_session_id"] = control.arm_session_id

        return payload

    @staticmethod
    def _seconds_remaining(
        control: AgentRuntimeControl | None,
        entry_state: str,
        now: datetime,
    ) -> int:
        if control is None:
            return 0
        if entry_state == ENTRY_ARMED:
            deadline = _aware(control.armed_until)
        elif entry_state == ENTRY_STARTING:
            deadline = _aware(control.request_expires_at)
        else:
            return 0
        if deadline is None:
            return 0
        return max(0, int((deadline - now).total_seconds()))

    def cycle_audit(self, db: Session) -> dict:
        """Compact runtime snapshot persisted into the AgentCycle summary."""
        control = self.get_control(db)
        now = self._now()
        entry_state = self.entry_execution_state(control, now=now)
        armed_until = _aware(control.armed_until) if control else None
        return {
            "state": (
                str(control.state) if control is not None else STATE_DISARMED
            ),
            "effective_armed": entry_state == ENTRY_ARMED,
            "entry_execution_state": entry_state,
            "armed_until": armed_until.isoformat() if armed_until else None,
            "executions_used": int(control.executions_used) if control else 0,
            "max_new_executions": (
                int(control.max_new_executions)
                if control
                else self.config.runtime_max_new_executions
            ),
        }

    # -----------------------------------------------------
    # Transitions
    # -----------------------------------------------------
    def request_arm(self, db: Session) -> dict:
        """DISARMED -> START_REQUESTED, then dispatch exactly one workflow."""
        if not self.master_execution_available():
            raise RuntimeControlUnavailable(
                "Paper execution capability is disabled for this deployment.",
                code="MASTER_EXECUTION_DISABLED",
            )
        if not self.dispatcher.is_enabled():
            raise RuntimeControlUnavailable(
                "GitHub dispatch is not configured for this deployment.",
                code="DISPATCH_DISABLED",
            )

        control = self.get_or_create(db)
        now = self._now()
        entry_state = self.entry_execution_state(control, now=now)
        if entry_state in (ENTRY_STARTING, ENTRY_ARMED):
            raise RuntimeControlConflict(
                "An arm session is already active.",
                code="ALREADY_ACTIVE",
            )

        arm_session_id = uuid.uuid4().hex
        expires_at = now + timedelta(
            minutes=self.config.runtime_start_request_ttl_minutes
        )

        # Claim the transition atomically so two concurrent ARM presses cannot
        # both dispatch a workflow.
        claimed = db.execute(
            update(AgentRuntimeControl)
            .where(
                AgentRuntimeControl.id == control.id,
                AgentRuntimeControl.state == control.state,
            )
            .values(
                state=STATE_START_REQUESTED,
                new_entries_armed=False,
                arm_session_id=arm_session_id,
                start_requested_at=now,
                request_expires_at=expires_at,
                armed_at=None,
                armed_until=None,
                executions_used=0,
                max_new_executions=self.config.runtime_max_new_executions,
                last_disarm_reason=None,
                updated_at=now,
            )
        ).rowcount
        if claimed != 1:
            db.rollback()
            raise RuntimeControlConflict(
                "The runtime control state changed concurrently.",
                code="ALREADY_ACTIVE",
            )
        db.commit()

        try:
            dispatch = self.dispatcher.dispatch_cycle(
                arm_session_id=arm_session_id
            )
        except GitHubDispatchError as exc:
            # Fail closed: never leave a START_REQUESTED that nothing will
            # ever claim.
            self._force_disarm(db, reason="DISPATCH_FAILED")
            raise RuntimeControlUnavailable(
                str(exc),
                code=exc.code,
            ) from None

        snapshot = self.snapshot(db)
        snapshot["dispatch"] = {
            "accepted": True,
            "repository": dispatch.get("repository"),
            "workflow": dispatch.get("workflow"),
            "ref": dispatch.get("ref"),
        }
        return snapshot

    def claim_session(self, db: Session, arm_session_id: str) -> dict:
        """START_REQUESTED -> ARMED, for the dispatched one-shot run only."""
        session_id = (arm_session_id or "").strip()
        result = {"claimed": False, "reason": None}
        if not session_id:
            result["reason"] = "MISSING_SESSION_ID"
            return result

        if not self.master_execution_available():
            result["reason"] = "MASTER_EXECUTION_DISABLED"
            return result

        control = self.get_control(db)
        if control is None:
            result["reason"] = "NO_RUNTIME_CONTROL"
            return result

        now = self._now()
        if str(control.state).upper() != STATE_START_REQUESTED:
            result["reason"] = "NOT_START_REQUESTED"
            return result
        if (control.arm_session_id or "") != session_id:
            result["reason"] = "SESSION_MISMATCH"
            return result

        expires = _aware(control.request_expires_at)
        if expires is None or now >= expires:
            self._force_disarm(db, reason="START_REQUEST_EXPIRED")
            result["reason"] = "START_REQUEST_EXPIRED"
            return result
        if control.executions_used >= control.max_new_executions:
            self._force_disarm(db, reason="EXECUTION_BUDGET_USED")
            result["reason"] = "EXECUTION_BUDGET_USED"
            return result

        armed_until = now + timedelta(
            minutes=self.config.runtime_arm_ttl_minutes
        )
        # The state predicate makes a duplicate claim a no-op: the second
        # attempt finds the row already ARMED and matches zero rows.
        claimed = db.execute(
            update(AgentRuntimeControl)
            .where(
                AgentRuntimeControl.id == control.id,
                AgentRuntimeControl.state == STATE_START_REQUESTED,
                AgentRuntimeControl.arm_session_id == session_id,
            )
            .values(
                state=STATE_ARMED,
                new_entries_armed=True,
                armed_at=now,
                armed_until=armed_until,
                updated_at=now,
            )
        ).rowcount
        if claimed != 1:
            db.rollback()
            result["reason"] = "ALREADY_CLAIMED"
            return result

        db.commit()
        result["claimed"] = True
        result["armed_until"] = armed_until
        return result

    def consume_execution(self, db: Session, *, cycle_id: int | None = None):
        """Record one submitted NEW paper BUY and auto-disarm new entries."""
        control = self.get_control(db)
        if control is None:
            return {"consumed": False, "reason": "NO_RUNTIME_CONTROL"}

        now = self._now()
        used = int(control.executions_used)
        new_used = used + 1
        exhausted = new_used >= int(control.max_new_executions)

        values = {
            "executions_used": new_used,
            "updated_at": now,
        }
        if cycle_id is not None:
            values["last_cycle_id"] = int(cycle_id)
        if exhausted:
            values.update(
                {
                    "state": STATE_DISARMED,
                    "new_entries_armed": False,
                    "last_disarm_reason": "EXECUTION_BUDGET_USED",
                }
            )

        updated = db.execute(
            update(AgentRuntimeControl)
            .where(
                AgentRuntimeControl.id == control.id,
                AgentRuntimeControl.state == STATE_ARMED,
                AgentRuntimeControl.executions_used == used,
            )
            .values(**values)
        ).rowcount
        if updated != 1:
            db.rollback()
            return {"consumed": False, "reason": "STATE_CHANGED"}

        db.commit()
        return {
            "consumed": True,
            "executions_used": new_used,
            "max_new_executions": int(control.max_new_executions),
            "auto_disarmed": exhausted,
        }

    def disarm(self, db: Session, *, reason: str = "OPERATOR_DISARM") -> dict:
        """Operator disarm. Idempotent; never touches exit processing."""
        self.get_or_create(db)
        self._force_disarm(db, reason=reason)
        return self.snapshot(db)

    def _force_disarm(self, db: Session, *, reason: str) -> None:
        now = self._now()
        db.execute(
            update(AgentRuntimeControl)
            .where(AgentRuntimeControl.id == AgentRuntimeControl.SINGLETON_ID)
            .values(
                state=STATE_DISARMED,
                new_entries_armed=False,
                armed_until=None,
                request_expires_at=None,
                last_disarm_reason=reason,
                updated_at=now,
            )
        )
        db.commit()


runtime_control_service = RuntimeControlService()
