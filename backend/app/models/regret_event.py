from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.database import Base


class RegretEvent(Base):
    __tablename__ = "regret_events"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('ACCEPT', 'REJECT')",
            name="ck_regret_decision",
        ),
        CheckConstraint(
            "classification IN "
            "('MISSED_ALPHA', 'AVOIDED_LOSS', "
            "'CORRECT_EXECUTION', 'BAD_EXECUTION')",
            name="ck_regret_classification",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    outcome_id: Mapped[int] = mapped_column(
        ForeignKey("outcome_snapshots.id"),
        unique=True,
        index=True,
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_trades.id"),
        index=True,
    )
    risk_decision_id: Mapped[int] = mapped_column(
        ForeignKey("risk_decisions.id"),
        index=True,
    )
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    decision: Mapped[str] = mapped_column(String(16))
    classification: Mapped[str] = mapped_column(String(32), index=True)
    pnl_pct: Mapped[float] = mapped_column(Float)
    pnl_amount: Mapped[float] = mapped_column(Float)
    decision_value: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
