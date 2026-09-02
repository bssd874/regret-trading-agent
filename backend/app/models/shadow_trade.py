from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.database import Base


class ShadowTrade(Base):
    __tablename__ = "shadow_trades"

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

    symbol: Mapped[str] = mapped_column(
        String(16),
        index=True,
    )

    side: Mapped[str] = mapped_column(
        String(8),
        default="BUY",
    )

    hypothetical_entry: Mapped[float] = mapped_column(
        Float
    )

    hypothetical_notional: Mapped[float] = (
        mapped_column(Float)
    )

    stop_loss: Mapped[float] = mapped_column(Float)

    target_price: Mapped[float] = mapped_column(Float)

    horizon_minutes: Mapped[int] = mapped_column(
        Integer
    )

    status: Mapped[str] = mapped_column(
        String(32),
        default="OPEN",
    )

    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    evaluation_due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )