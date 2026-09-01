from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.database import Base


class DecisionAnalysis(Base):
    __tablename__ = "decision_analyses"
    __table_args__ = (
        UniqueConstraint("candidate_id", name="uq_decision_candidate"),
        CheckConstraint(
            "analyst_confidence >= 0 AND analyst_confidence <= 1",
            name="ck_decision_confidence",
        ),
        CheckConstraint(
            "entry_price > 0 AND stop_loss > 0 AND target_price > 0",
            name="ck_decision_positive_prices",
        ),
        CheckConstraint(
            "stop_loss < entry_price AND target_price > entry_price",
            name="ck_decision_price_order",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_trades.id"),
        index=True,
    )

    symbol: Mapped[str] = mapped_column(
        String(16),
        index=True,
    )

    direction: Mapped[str] = mapped_column(
        String(8),
        default="LONG",
    )

    thesis: Mapped[str] = mapped_column(Text)

    analyst_confidence: Mapped[float] = (
        mapped_column(Float)
    )

    entry_price: Mapped[float] = mapped_column(Float)

    stop_loss: Mapped[float] = mapped_column(Float)

    target_price: Mapped[float] = mapped_column(Float)

    horizon_minutes: Mapped[int] = mapped_column(
        Integer
    )

    invalidation: Mapped[str] = mapped_column(Text)

    evidence_summary: Mapped[str] = mapped_column(
        Text
    )

    provider: Mapped[str] = mapped_column(
        String(32),
        default="azure",
    )

    model_name: Mapped[str] = mapped_column(
        String(128)
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
