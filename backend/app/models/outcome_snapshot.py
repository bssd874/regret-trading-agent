from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.database import Base


class OutcomeSnapshot(Base):
    __tablename__ = "outcome_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "source_type",
            "source_id",
            name="uq_outcome_source",
        ),
        CheckConstraint(
            "source_type IN ('SHADOW', 'EXECUTED')",
            name="ck_outcome_source_type",
        ),
        CheckConstraint(
            "decision IN ('ACCEPT', 'REJECT')",
            name="ck_outcome_decision",
        ),
        CheckConstraint(
            "entry_price > 0 AND evaluation_price > 0",
            name="ck_outcome_positive_prices",
        ),
        CheckConstraint(
            "quantity > 0 AND notional > 0",
            name="ck_outcome_positive_size",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(16), index=True)
    source_id: Mapped[int] = mapped_column(Integer, index=True)
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
    entry_price: Mapped[float] = mapped_column(Float)
    evaluation_price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    notional: Mapped[float] = mapped_column(Float)
    pnl_pct: Mapped[float] = mapped_column(Float)
    pnl_amount: Mapped[float] = mapped_column(Float)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    price_source: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
