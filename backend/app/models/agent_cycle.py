from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.database import Base


class AgentCycle(Base):
    __tablename__ = "agent_cycles"
    __table_args__ = (
        CheckConstraint(
            "trigger IN ('SCHEDULED', 'MANUAL')",
            name="ck_agent_cycle_trigger",
        ),
        CheckConstraint(
            "status IN "
            "('RUNNING', 'COMPLETED', 'PARTIAL_FAILED', 'FAILED', 'ABANDONED')",
            name="ck_agent_cycle_status",
        ),
        CheckConstraint(
            "mode IN ('OBSERVE', 'AUTONOMOUS_PAPER')",
            name="ck_agent_cycle_mode",
        ),
        Index(
            "uq_agent_cycles_one_running",
            "status",
            unique=True,
            sqlite_where=text("status = 'RUNNING'"),
            postgresql_where=text("status = 'RUNNING'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trigger: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    mode: Mapped[str] = mapped_column(String(24), index=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    scouted_count: Mapped[int] = mapped_column(Integer, default=0)
    analyzed_count: Mapped[int] = mapped_column(Integer, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    shadow_created_count: Mapped[int] = mapped_column(Integer, default=0)
    paper_execution_count: Mapped[int] = mapped_column(Integer, default=0)
    execution_held_count: Mapped[int] = mapped_column(Integer, default=0)
    outcomes_evaluated_count: Mapped[int] = mapped_column(Integer, default=0)
    regret_events_created_count: Mapped[int] = mapped_column(Integer, default=0)

    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    errors_json: Mapped[str] = mapped_column(Text, default="[]")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
