from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.database import Base


class ExecutedTrade(Base):
    __tablename__ = "executed_trades"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_trades.id"),
        index=True,
    )

    risk_decision_id: Mapped[int] = mapped_column(
        ForeignKey("risk_decisions.id"),
        unique=True,
        index=True,
    )

    alpaca_order_id: Mapped[str | None] = mapped_column(
        String(128),
        unique=True,
        nullable=True,
    )

    symbol: Mapped[str] = mapped_column(
        String(16),
        index=True,
    )

    side: Mapped[str] = mapped_column(
        String(8),
        default="BUY",
    )

    requested_notional: Mapped[float] = mapped_column(
        Float
    )

    status: Mapped[str] = mapped_column(
        String(32),
        default="PENDING_SUBMISSION",
    )

    filled_qty: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    filled_avg_price: Mapped[float | None] = (
        mapped_column(
            Float,
            nullable=True,
        )
    )

    submitted_at: Mapped[datetime | None] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=True,
        )
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )