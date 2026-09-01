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


class RiskDecision(Base):
    __tablename__ = "risk_decisions"
    __table_args__ = (
        UniqueConstraint("candidate_id", name="uq_risk_candidate"),
        UniqueConstraint("analysis_id", name="uq_risk_analysis"),
        UniqueConstraint("critic_id", name="uq_risk_critic"),
        CheckConstraint(
            "decision IN ('ACCEPT', 'REJECT')",
            name="ck_risk_decision",
        ),
        CheckConstraint(
            "original_confidence >= 0 AND original_confidence <= 1",
            name="ck_risk_original_confidence",
        ),
        CheckConstraint(
            "critic_adjustment >= -0.20 AND critic_adjustment <= 0",
            name="ck_risk_critic_adjustment",
        ),
        CheckConstraint(
            "adjusted_confidence >= 0 AND adjusted_confidence <= 1",
            name="ck_risk_adjusted_confidence",
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

    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("decision_analyses.id"),
    )

    critic_id: Mapped[int] = mapped_column(
        ForeignKey("critic_analyses.id"),
    )

    original_confidence: Mapped[float] = (
        mapped_column(Float)
    )

    critic_adjustment: Mapped[float] = (
        mapped_column(Float)
    )

    adjusted_confidence: Mapped[float] = (
        mapped_column(Float)
    )

    reward_risk_ratio: Mapped[float] = (
        mapped_column(Float)
    )

    proposed_position_pct: Mapped[float] = (
        mapped_column(Float)
    )

    risk_score: Mapped[float] = mapped_column(Float)

    decision: Mapped[str] = mapped_column(
        String(16)
    )

    reasons: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
