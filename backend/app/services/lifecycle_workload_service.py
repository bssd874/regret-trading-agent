"""Cheap, database-only answer to: is there any lifecycle work to do?

A frequent heartbeat exists to keep *existing* positions safe. When there is
nothing to reconcile, no position to monitor and no outcome due, the tick
should cost nothing: no market-data request, no provider call, and not even an
AgentCycle row.

Every query here reads the local database only. The predicates deliberately
mirror the ones the real pipeline uses, so this can never report "idle" while
the pipeline would have found work:

* pending BUY  -> ExecutedTrade in a non-terminal status
* open position -> filled ExecutedTrade with no filled TradeExit
* pending SELL -> TradeExit in a non-terminal status
* due outcome  -> OPEN ShadowTrade past its evaluation_due_at, or a filled
                  ExecutedTrade with no OutcomeSnapshot yet
"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.executed_trade import ExecutedTrade
from backend.app.models.outcome_snapshot import OutcomeSnapshot
from backend.app.models.shadow_trade import ShadowTrade
from backend.app.models.trade_exit import TradeExit


# Mirrors autonomous_agent_service.TERMINAL_EXECUTION_STATUSES /
# TERMINAL_EXIT_STATUSES.
TERMINAL_STATUSES = ("filled", "canceled", "expired", "rejected")


def _count(db: Session, stmt) -> int:
    return int(db.scalar(stmt) or 0)


def lifecycle_workload(db: Session, *, now: datetime | None = None) -> dict:
    """Summarise outstanding lifecycle work. Reads only; writes nothing."""
    moment = now or datetime.now(timezone.utc)

    pending_executions = _count(
        db,
        select(func.count())
        .select_from(ExecutedTrade)
        .where(func.lower(ExecutedTrade.status).notin_(TERMINAL_STATUSES)),
    )

    pending_exits = _count(
        db,
        select(func.count())
        .select_from(TradeExit)
        .where(func.lower(TradeExit.status).notin_(TERMINAL_STATUSES)),
    )

    # A filled entry whose exit has not filled is still an open position.
    filled_exit_ids = select(TradeExit.executed_trade_id).where(
        func.lower(TradeExit.status) == "filled"
    )
    open_positions = _count(
        db,
        select(func.count())
        .select_from(ExecutedTrade)
        .where(
            func.lower(ExecutedTrade.status) == "filled",
            ExecutedTrade.id.notin_(filled_exit_ids),
        ),
    )

    due_shadow_trades = _count(
        db,
        select(func.count())
        .select_from(ShadowTrade)
        .where(
            ShadowTrade.status == "OPEN",
            ShadowTrade.evaluation_due_at <= moment,
        ),
    )

    evaluated_execution_ids = select(OutcomeSnapshot.source_id).where(
        OutcomeSnapshot.source_type == "EXECUTED"
    )
    unevaluated_executions = _count(
        db,
        select(func.count())
        .select_from(ExecutedTrade)
        .where(
            func.lower(ExecutedTrade.status) == "filled",
            ExecutedTrade.id.notin_(evaluated_execution_ids),
        ),
    )

    counts = {
        "pending_executions": pending_executions,
        "pending_exits": pending_exits,
        "open_positions": open_positions,
        "due_shadow_trades": due_shadow_trades,
        "unevaluated_executions": unevaluated_executions,
    }
    return {**counts, "has_work": any(counts.values())}


def has_lifecycle_work(db: Session, *, now: datetime | None = None) -> bool:
    return bool(lifecycle_workload(db, now=now)["has_work"])
