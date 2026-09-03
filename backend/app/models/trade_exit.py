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


class TradeExit(Base):
    __tablename__ = "trade_exits"
    __table_args__ = (
        CheckConstraint(
            "reason IN ('TAKE_PROFIT', 'STOP_LOSS', 'TIME_EXIT')",
            name="ck_trade_exit_reason",
        ),
        CheckConstraint(
            "trigger_price > 0 AND target_price > 0 AND stop_loss > 0",
            name="ck_trade_exit_positive_prices",
        ),
        CheckConstraint(
            "horizon_minutes > 0 AND requested_qty > 0",
            name="ck_trade_exit_positive_size_horizon",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    executed_trade_id: Mapped[int] = mapped_column(
        ForeignKey("executed_trades.id"),
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
    reason: Mapped[str] = mapped_column(String(24), index=True)
    trigger_price: Mapped[float] = mapped_column(Float)
    target_price: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float] = mapped_column(Float)
    horizon_minutes: Mapped[int] = mapped_column(Integer)
    requested_qty: Mapped[float] = mapped_column(Float)
    alpaca_order_id: Mapped[str | None] = mapped_column(
        String(128),
        unique=True,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="PENDING_SUBMISSION",
        index=True,
    )
    filled_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    filled_avg_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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
