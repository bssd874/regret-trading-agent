from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.database import Base


class AgentRuntimeControl(Base):
    """Operator-controlled permission for opening NEW autonomous positions.

    This is the second safety layer. `PAPER_EXECUTION_ENABLED` remains the
    deployment-level master capability; this row only records whether an
    operator has currently armed the agent for a new entry. It never grants
    execution capability on its own, and it never gates exits.

    The table is used as a singleton: row id 1.
    """

    __tablename__ = "agent_runtime_controls"
    __table_args__ = (
        CheckConstraint(
            "state IN ('DISARMED', 'START_REQUESTED', 'ARMED')",
            name="ck_agent_runtime_control_state",
        ),
        CheckConstraint(
            "max_new_executions >= 1",
            name="ck_agent_runtime_control_max_executions",
        ),
        CheckConstraint(
            "executions_used >= 0",
            name="ck_agent_runtime_control_executions_used",
        ),
    )

    SINGLETON_ID = 1

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    state: Mapped[str] = mapped_column(String(16), default="DISARMED")
    new_entries_armed: Mapped[bool] = mapped_column(Boolean, default=False)

    # Opaque correlation id for one arm attempt. Not a credential.
    arm_session_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    start_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    request_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    armed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    armed_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    max_new_executions: Mapped[int] = mapped_column(Integer, default=1)
    executions_used: Mapped[int] = mapped_column(Integer, default=0)

    last_disarm_reason: Mapped[str | None] = mapped_column(
        String(48),
        nullable=True,
    )
    last_cycle_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
