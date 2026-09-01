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


class CriticAnalysis(Base):
    __tablename__ = "critic_analyses"
    __table_args__ = (
        UniqueConstraint("candidate_id", name="uq_critic_candidate"),
        UniqueConstraint("analysis_id", name="uq_critic_analysis"),
        CheckConstraint(
            "verdict IN ('PASS', 'CHALLENGE')",
            name="ck_critic_verdict",
        ),
        CheckConstraint(
            "confidence_adjustment >= -0.20 "
            "AND confidence_adjustment <= 0",
            name="ck_critic_adjustment",
        ),
        CheckConstraint(
            "thesis_consistency >= 0 AND thesis_consistency <= 1",
            name="ck_critic_consistency",
        ),
        CheckConstraint(
            "verdict != 'PASS' OR confidence_adjustment = 0",
            name="ck_critic_pass_adjustment",
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
        index=True,
    )

    verdict: Mapped[str] = mapped_column(
        String(16)
    )

    confidence_adjustment: Mapped[float] = (
        mapped_column(Float)
    )

    thesis_consistency: Mapped[float] = (
        mapped_column(Float)
    )

    concerns: Mapped[str] = mapped_column(Text)

    provider: Mapped[str] = mapped_column(
        String(32),
        default="nvidia",
    )

    model_name: Mapped[str] = mapped_column(
        String(128)
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
