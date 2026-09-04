"""Internal scheduler heartbeat.

REGRET's position safety depends on something calling the bounded autonomous
cycle regularly: pending fills must be reconciled, and an open position must be
re-evaluated against its recorded target, stop and horizon so TAKE_PROFIT,
STOP_LOSS or TIME_EXIT can fire.

GitHub's cron proved too unreliable to be that clock on its own — in one
observed window the schedule was live for about five hours before its first run,
then produced a single run and nothing for the next several hours. This endpoint
makes the heartbeat provider-neutral: *any* dependable external scheduler can
drive it, and GitHub Actions stays only as a fallback.

The endpoint runs exactly one existing cycle. It contains no trading logic, no
loop, no thread and no sleep, so it is safe on ephemeral serverless runtimes.
It never arms the agent; it only reads the persisted runtime permission.
"""

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.database import get_db
from backend.app.services.autonomous_agent_service import (
    AgentCycleAlreadyRunning,
    autonomous_agent,
)
from backend.app.services.db_diagnostics import automation_database_error


router = APIRouter(prefix="/internal", tags=["internal-scheduler"])

SCHEDULER_SECRET_HEADER = "X-Regret-Scheduler-Secret"

# Recorded in the cycle summary. The persisted `trigger` column stays within
# its existing CHECK constraint, so no migration is needed on a live database.
TRIGGER_SOURCE = "SCHEDULED_HEARTBEAT"


def require_scheduler(
    x_regret_scheduler_secret: str | None = Header(default=None),
) -> None:
    """Fail closed unless the caller presents the configured scheduler secret."""
    configured = (settings.scheduler_trigger_secret or "").strip()
    if not configured:
        raise HTTPException(
            status_code=503,
            detail="Scheduler heartbeat is not configured for this deployment.",
        )

    presented = (x_regret_scheduler_secret or "").strip()
    if not presented or not secrets.compare_digest(presented, configured):
        raise HTTPException(
            status_code=401,
            detail="Scheduler authentication failed.",
        )


@router.post("/scheduled-cycle")
def run_scheduled_cycle(
    _: None = Depends(require_scheduler),
    db: Session = Depends(get_db),
):
    """Run exactly one autonomous cycle on behalf of an external scheduler.

    Ordering is the existing pipeline's, which is already position-first:
    execution reconciliation, exit reconciliation, open-position monitoring and
    exits, outcome evaluation, and only then new-entry scouting — and that last
    step can still only execute while the operator has armed a new entry.
    """
    misconfigured = automation_database_error(settings)
    if misconfigured:
        # A hosted run must never operate against the local SQLite database.
        raise HTTPException(status_code=503, detail=misconfigured)

    try:
        cycle = autonomous_agent.run_cycle(
            db=db,
            trigger="SCHEDULED",
            trigger_source=TRIGGER_SOURCE,
        )
    except AgentCycleAlreadyRunning:
        # The persistent AgentCycle lock is authoritative. A second concurrent
        # heartbeat reports this and submits nothing.
        return {
            "status": "ALREADY_RUNNING",
            "trigger_source": TRIGGER_SOURCE,
            "cycle_id": None,
            "started_at": None,
            "completed_at": None,
        }

    return {
        "status": cycle.status,
        "trigger_source": TRIGGER_SOURCE,
        "cycle_id": cycle.id,
        "started_at": cycle.started_at,
        "completed_at": cycle.finished_at,
    }
