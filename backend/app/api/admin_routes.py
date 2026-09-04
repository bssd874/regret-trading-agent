"""Isolated operator-control routes.

These are deliberately separate from the public API surface:

* they authenticate with their own server-side shared secret;
* they do not depend on ``PUBLIC_WRITE_API_ENABLED``, which stays false so
  every other mutation route remains blocked;
* they fail closed when ``ADMIN_CONTROL_SECRET`` is unset.

Nothing here chooses a symbol, a side, a price or a risk outcome. The operator
only grants or revokes permission for the agent to open a NEW position.
"""

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.database import get_db
from backend.app.services.runtime_control_service import (
    RuntimeControlConflict,
    RuntimeControlUnavailable,
    runtime_control_service,
)


router = APIRouter(prefix="/admin", tags=["admin-control"])

ADMIN_SECRET_HEADER = "X-Regret-Admin-Secret"


def require_admin(
    x_regret_admin_secret: str | None = Header(default=None),
) -> None:
    """Fail closed unless the caller presents the configured admin secret."""
    configured = (settings.admin_control_secret or "").strip()
    if not configured:
        raise HTTPException(
            status_code=503,
            detail="Admin control is not configured for this deployment.",
        )

    presented = (x_regret_admin_secret or "").strip()
    if not presented or not secrets.compare_digest(presented, configured):
        raise HTTPException(
            status_code=401,
            detail="Admin authentication failed.",
        )


@router.get("/agent-control")
def read_agent_control(
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return {"runtime_control": runtime_control_service.snapshot(db)}


@router.post("/agent-control/arm-request")
def request_agent_arm(
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Move to START_REQUESTED and dispatch exactly one one-shot cycle.

    The agent is NOT armed here. It becomes ARMED only when the dispatched
    workflow claims this session, so a failed dispatch cannot strand the
    system in a permissive state.
    """
    try:
        snapshot = runtime_control_service.request_arm(db)
    except RuntimeControlConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": str(exc)},
        ) from None
    except RuntimeControlUnavailable as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": str(exc)},
        ) from None

    return {"runtime_control": snapshot}


@router.post("/agent-control/disarm")
def disarm_agent(
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Block NEW entries immediately. Idempotent.

    Exit processing, reconciliation and outcome evaluation are unaffected: an
    open position keeps its autonomous target / stop / horizon protection.
    """
    snapshot = runtime_control_service.disarm(db, reason="OPERATOR_DISARM")
    return {"runtime_control": snapshot}
