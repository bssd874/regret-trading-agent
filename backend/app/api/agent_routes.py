import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.database import get_db
from backend.app.models.agent_cycle import AgentCycle
from backend.app.services.autonomous_agent_service import (
    AgentCycleAlreadyRunning,
    autonomous_agent,
)


router = APIRouter(prefix="/agent", tags=["autonomous-agent"])


def _load_json(value: str, fallback):
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback
    return parsed


def agent_cycle_payload(cycle: AgentCycle) -> dict:
    summary = _load_json(cycle.summary_json, {})
    return {
        "id": cycle.id,
        "trigger": cycle.trigger,
        "status": cycle.status,
        "mode": cycle.mode,
        "started_at": cycle.started_at,
        "heartbeat_at": cycle.heartbeat_at,
        "finished_at": cycle.finished_at,
        "scouted_count": cycle.scouted_count,
        "analyzed_count": cycle.analyzed_count,
        "accepted_count": cycle.accepted_count,
        "rejected_count": cycle.rejected_count,
        "failed_count": cycle.failed_count,
        "shadow_created_count": cycle.shadow_created_count,
        "paper_execution_count": cycle.paper_execution_count,
        "execution_held_count": cycle.execution_held_count,
        "outcomes_evaluated_count": cycle.outcomes_evaluated_count,
        "regret_events_created_count": cycle.regret_events_created_count,
        "executions_synced": int(summary.get("executions_synced", 0)),
        "executions_filled": int(summary.get("executions_filled", 0)),
        "summary": summary,
        "errors": _load_json(cycle.errors_json, []),
        "created_at": cycle.created_at,
    }


@router.get("/status")
def get_agent_status(db: Session = Depends(get_db)):
    last_cycle = db.scalar(
        select(AgentCycle).order_by(desc(AgentCycle.started_at)).limit(1)
    )
    running = db.scalar(
        select(AgentCycle.id)
        .where(AgentCycle.status == "RUNNING")
        .limit(1)
    )
    payload = agent_cycle_payload(last_cycle) if last_cycle is not None else None
    counts = (
        {
            "scouted": last_cycle.scouted_count,
            "analyzed": last_cycle.analyzed_count,
            "accepted": last_cycle.accepted_count,
            "rejected": last_cycle.rejected_count,
            "failed": last_cycle.failed_count,
            "shadows_created": last_cycle.shadow_created_count,
            "paper_executions": last_cycle.paper_execution_count,
            "executions_held": last_cycle.execution_held_count,
            "outcomes_evaluated": last_cycle.outcomes_evaluated_count,
            "regret_events_created": last_cycle.regret_events_created_count,
            "executions_synced": payload["executions_synced"],
            "executions_filled": payload["executions_filled"],
        }
        if last_cycle is not None
        else None
    )

    return {
        "enabled": settings.autonomous_agent_enabled,
        "mode": autonomous_agent.mode(),
        "cycle_seconds": settings.autonomous_cycle_seconds,
        "max_candidates_per_cycle": (
            settings.autonomous_max_candidates_per_cycle
        ),
        "paper": True,
        "paper_execution_enabled": settings.paper_execution_enabled,
        "running": running is not None,
        "last_cycle": payload,
        "last_cycle_status": last_cycle.status if last_cycle else None,
        "last_cycle_started_at": last_cycle.started_at if last_cycle else None,
        "last_cycle_finished_at": last_cycle.finished_at if last_cycle else None,
        "executions_synced": payload["executions_synced"] if payload else 0,
        "executions_filled": payload["executions_filled"] if payload else 0,
        "last_cycle_counts": counts,
    }


@router.get("/cycles")
def get_agent_cycles(
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    cycles = list(
        db.scalars(
            select(AgentCycle)
            .order_by(desc(AgentCycle.started_at))
            .limit(limit)
        ).all()
    )
    return [agent_cycle_payload(cycle) for cycle in cycles]


@router.get("/cycles/{cycle_id}")
def get_agent_cycle(
    cycle_id: int,
    db: Session = Depends(get_db),
):
    cycle = db.get(AgentCycle, cycle_id)
    if cycle is None:
        raise HTTPException(status_code=404, detail="AgentCycle not found")
    return agent_cycle_payload(cycle)


@router.post("/run-once")
def run_agent_once(db: Session = Depends(get_db)):
    try:
        cycle = autonomous_agent.run_cycle(db=db, trigger="MANUAL")
    except AgentCycleAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return agent_cycle_payload(cycle)
