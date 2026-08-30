from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.database import Base


class CandidateTrade(Base):
    __tablename__ = "candidate_trades"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
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

    strategy: Mapped[str] = mapped_column(
        String(32),
        default="momentum",
    )

    entry_price: Mapped[float] = mapped_column(Float)

    price_change_pct: Mapped[float] = mapped_column(
        Float,
        default=0.0,
    )

    volume_ratio: Mapped[float] = mapped_column(
        Float,
        default=1.0,
    )

    scout_score: Mapped[float] = mapped_column(
        Float,
        default=0.0,
    )

    source: Mapped[str] = mapped_column(
        String(32),
        default="watchlist",
    )

    status: Mapped[str] = mapped_column(
        String(16),
        default="NEW",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )