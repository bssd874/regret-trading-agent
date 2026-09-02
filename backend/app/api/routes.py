import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.app.db.database import get_db
from backend.app.models.candidate_trade import CandidateTrade
from backend.app.models.critic_analysis import CriticAnalysis
from backend.app.models.decision_analysis import DecisionAnalysis
from backend.app.models.risk_decision import RiskDecision
from backend.app.schemas.candidate_trade import CandidateTradeResponse
from backend.app.schemas.decision import (
    AnalyzeCandidateResponse,
    DecisionDetail,
    DecisionListItem,
)
from backend.app.services.alpaca_service import alpaca_service
from backend.app.services.decision_pipeline import decision_pipeline
from backend.app.services.market_scout import market_scout

from backend.app.models.executed_trade import ExecutedTrade
from backend.app.models.outcome_snapshot import OutcomeSnapshot
from backend.app.models.regret_event import RegretEvent
from backend.app.models.shadow_trade import ShadowTrade
from backend.app.services.decision_router import decision_router
from backend.app.services.execution_sync_service import (
    execution_sync_service,
)
from backend.app.services.outcome_pipeline import outcome_pipeline
from backend.app.services.regret_metrics_service import regret_metrics_service


router = APIRouter()


def _execution_payload(execution: ExecutedTrade) -> dict:
    return {
        "id": execution.id,
        "candidate_id": execution.candidate_id,
        "risk_decision_id": execution.risk_decision_id,
        "symbol": execution.symbol,
        "side": execution.side,
        "requested_notional": execution.requested_notional,
        "alpaca_order_id": execution.alpaca_order_id,
        "status": execution.status,
        "filled_qty": execution.filled_qty,
        "filled_avg_price": execution.filled_avg_price,
        "submitted_at": execution.submitted_at,
        "created_at": execution.created_at,
        "paper": True,
    }


def _outcome_payload(outcome: OutcomeSnapshot) -> dict:
    return {
        "id": outcome.id,
        "source_type": outcome.source_type,
        "source_id": outcome.source_id,
        "candidate_id": outcome.candidate_id,
        "risk_decision_id": outcome.risk_decision_id,
        "symbol": outcome.symbol,
        "decision": outcome.decision,
        "entry_price": outcome.entry_price,
        "evaluation_price": outcome.evaluation_price,
        "quantity": outcome.quantity,
        "notional": outcome.notional,
        "pnl_pct": outcome.pnl_pct,
        "pnl_amount": outcome.pnl_amount,
        "due_at": outcome.due_at,
        "evaluated_at": outcome.evaluated_at,
        "price_source": outcome.price_source,
        "created_at": outcome.created_at,
    }


def _regret_event_payload(event: RegretEvent) -> dict:
    return {
        "id": event.id,
        "outcome_id": event.outcome_id,
        "candidate_id": event.candidate_id,
        "risk_decision_id": event.risk_decision_id,
        "symbol": event.symbol,
        "decision": event.decision,
        "classification": event.classification,
        "pnl_pct": event.pnl_pct,
        "pnl_amount": event.pnl_amount,
        "decision_value": event.decision_value,
        "created_at": event.created_at,
    }


def _load_json_list(value: str) -> list[str]:
    try:
        result = json.loads(value or "[]")
    except (json.JSONDecodeError, TypeError):
        return []

    return result if isinstance(result, list) else []


def _decision_payload(
    risk: RiskDecision,
    analysis: DecisionAnalysis,
    critic: CriticAnalysis,
) -> dict:
    return {
        "id": risk.id,
        "candidate_id": risk.candidate_id,
        "analyst": {
            "provider": "azure",
            "model": analysis.model_name,
            "symbol": analysis.symbol,
            "direction": analysis.direction,
            "thesis": analysis.thesis,
            "confidence": risk.original_confidence,
            "entry_price": analysis.entry_price,
            "stop_loss": analysis.stop_loss,
            "target_price": analysis.target_price,
            "horizon_minutes": analysis.horizon_minutes,
            "invalidation": analysis.invalidation,
            "evidence": _load_json_list(analysis.evidence_summary),
        },
        "critic": {
            "provider": critic.provider,
            "model": critic.model_name,
            "verdict": critic.verdict,
            "confidence_adjustment": critic.confidence_adjustment,
            "thesis_consistency": critic.thesis_consistency,
            "concerns": _load_json_list(critic.concerns),
            "degraded_mode": critic.provider == "azure-fallback",
        },
        "consensus": {
            "original_confidence": risk.original_confidence,
            "critic_adjustment": risk.critic_adjustment,
            "adjusted_confidence": risk.adjusted_confidence,
        },
        "risk": {
            "decision": risk.decision,
            "reward_risk_ratio": risk.reward_risk_ratio,
            "proposed_position_pct": risk.proposed_position_pct,
            "risk_score": risk.risk_score,
            "reasons": _load_json_list(risk.reasons),
        },
        "created_at": risk.created_at,
        "order_submitted": False,
    }


@router.get("/account")
def get_account():
    account = alpaca_service.get_account()

    return {
        "status": getattr(account.status, "value", str(account.status)),
        "cash": float(account.cash),
        "equity": float(account.equity),
        "buying_power": float(account.buying_power),
        "paper": True,
    }


@router.get("/market/movers")
def get_market_movers():
    movers = alpaca_service.get_market_movers(top=10)

    return {
        "gainers": [
            {
                "symbol": item.symbol,
                "price": item.price,
                "percent_change": item.percent_change,
            }
            for item in movers.gainers
        ],
        "losers": [
            {
                "symbol": item.symbol,
                "price": item.price,
                "percent_change": item.percent_change,
            }
            for item in movers.losers
        ],
    }


@router.post(
    "/scout/run",
    response_model=list[CandidateTradeResponse],
)
def run_scout(db: Session = Depends(get_db)):
    return market_scout.run(db=db, limit=5)


@router.get(
    "/candidates",
    response_model=list[CandidateTradeResponse],
)
def get_candidates(db: Session = Depends(get_db)):
    statement = (
        select(CandidateTrade)
        .order_by(desc(CandidateTrade.created_at))
        .limit(50)
    )
    return list(db.scalars(statement).all())


@router.post(
    "/candidates/{candidate_id}/analyze",
    response_model=AnalyzeCandidateResponse,
)
def analyze_candidate(
    candidate_id: int,
    db: Session = Depends(get_db),
):
    try:
        return decision_pipeline.run(db=db, candidate_id=candidate_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/decisions",
    response_model=list[DecisionListItem],
)
def get_decisions(db: Session = Depends(get_db)):
    statement = (
        select(RiskDecision, DecisionAnalysis, CriticAnalysis)
        .join(
            DecisionAnalysis,
            DecisionAnalysis.id == RiskDecision.analysis_id,
        )
        .join(
            CriticAnalysis,
            CriticAnalysis.id == RiskDecision.critic_id,
        )
        .order_by(desc(RiskDecision.created_at))
        .limit(50)
    )

    return [
        {
            "id": risk.id,
            "candidate_id": risk.candidate_id,
            "symbol": analysis.symbol,
            "analyst_confidence": risk.original_confidence,
            "critic_adjustment": risk.critic_adjustment,
            "adjusted_confidence": risk.adjusted_confidence,
            "critic_verdict": critic.verdict,
            "critic_provider": critic.provider,
            "degraded_mode": critic.provider == "azure-fallback",
            "reward_risk_ratio": risk.reward_risk_ratio,
            "risk_score": risk.risk_score,
            "decision": risk.decision,
            "reasons": _load_json_list(risk.reasons),
            "created_at": risk.created_at,
            "order_submitted": False,
        }
        for risk, analysis, critic in db.execute(statement).all()
    ]


@router.get(
    "/decisions/{decision_id}",
    response_model=DecisionDetail,
)
def get_decision(
    decision_id: int,
    db: Session = Depends(get_db),
):
    statement = (
        select(RiskDecision, DecisionAnalysis, CriticAnalysis)
        .join(
            DecisionAnalysis,
            DecisionAnalysis.id == RiskDecision.analysis_id,
        )
        .join(
            CriticAnalysis,
            CriticAnalysis.id == RiskDecision.critic_id,
        )
        .where(RiskDecision.id == decision_id)
    )
    row = db.execute(statement).one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail="Decision not found")

    risk, analysis, critic = row
    return _decision_payload(risk, analysis, critic)

@router.post("/decisions/{decision_id}/route")
def route_decision(
    decision_id: int,
    db: Session = Depends(get_db),
):
    try:
        return decision_router.route(
            db=db,
            decision_id=decision_id,
        )

    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

@router.get("/executions")
def get_executions(
    db: Session = Depends(get_db),
):
    statement = (
        select(ExecutedTrade)
        .order_by(
            desc(ExecutedTrade.created_at)
        )
        .limit(50)
    )

    rows = list(
        db.scalars(statement).all()
    )

    return [_execution_payload(row) for row in rows]

@router.get("/executions/{execution_id}")
def get_execution(
    execution_id: int,
    db: Session = Depends(get_db),
):
    execution = db.get(
        ExecutedTrade,
        execution_id,
    )

    if execution is None:
        raise HTTPException(
            status_code=404,
            detail="Execution not found",
        )

    return _execution_payload(execution)


@router.post("/executions/{execution_id}/sync")
def sync_execution(
    execution_id: int,
    db: Session = Depends(get_db),
):
    try:
        execution = execution_sync_service.sync(
            db=db,
            execution_id=execution_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Alpaca paper order synchronization failed",
        ) from exc

    return _execution_payload(execution)

@router.get("/shadow-trades")
def get_shadow_trades(
    db: Session = Depends(get_db),
):
    statement = (
        select(ShadowTrade)
        .order_by(
            desc(ShadowTrade.opened_at)
        )
        .limit(50)
    )

    rows = list(
        db.scalars(statement).all()
    )

    return [
        {
            "id": row.id,
            "candidate_id":
                row.candidate_id,
            "risk_decision_id":
                row.risk_decision_id,
            "symbol": row.symbol,
            "side": row.side,
            "hypothetical_entry":
                row.hypothetical_entry,
            "hypothetical_notional":
                row.hypothetical_notional,
            "stop_loss":
                row.stop_loss,
            "target_price":
                row.target_price,
            "horizon_minutes":
                row.horizon_minutes,
            "status":
                row.status,
            "opened_at":
                row.opened_at,
            "evaluation_due_at":
                row.evaluation_due_at,
            "order_submitted":
                False,
        }
        for row in rows
    ]

@router.get("/shadow-trades/{shadow_id}")
def get_shadow_trade(
    shadow_id: int,
    db: Session = Depends(get_db),
):
    shadow = db.get(
        ShadowTrade,
        shadow_id,
    )

    if shadow is None:
        raise HTTPException(
            status_code=404,
            detail="ShadowTrade not found",
        )

    return {
        "id": shadow.id,
        "candidate_id":
            shadow.candidate_id,
        "risk_decision_id":
            shadow.risk_decision_id,
        "symbol": shadow.symbol,
        "side": shadow.side,
        "hypothetical_entry":
            shadow.hypothetical_entry,
        "hypothetical_notional":
            shadow.hypothetical_notional,
        "stop_loss":
            shadow.stop_loss,
        "target_price":
            shadow.target_price,
        "horizon_minutes":
            shadow.horizon_minutes,
        "status":
            shadow.status,
        "opened_at":
            shadow.opened_at,
        "evaluation_due_at":
            shadow.evaluation_due_at,
        "order_submitted":
            False,
    }


def _evaluate_or_http_error(callback):
    try:
        return callback()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Read-only market outcome evaluation failed",
        ) from exc


@router.post("/outcomes/evaluate-due")
def evaluate_due_outcomes(db: Session = Depends(get_db)):
    return outcome_pipeline.evaluate_due(db=db)


@router.post("/shadow-trades/{shadow_id}/evaluate")
def evaluate_shadow_trade(
    shadow_id: int,
    db: Session = Depends(get_db),
):
    return _evaluate_or_http_error(
        lambda: outcome_pipeline.evaluate_shadow(
            db=db,
            shadow_id=shadow_id,
        )
    )


@router.post("/executions/{execution_id}/evaluate")
def evaluate_executed_trade(
    execution_id: int,
    db: Session = Depends(get_db),
):
    return _evaluate_or_http_error(
        lambda: outcome_pipeline.evaluate_execution(
            db=db,
            execution_id=execution_id,
        )
    )


@router.get("/outcomes")
def get_outcomes(db: Session = Depends(get_db)):
    rows = list(
        db.scalars(
            select(OutcomeSnapshot)
            .order_by(desc(OutcomeSnapshot.evaluated_at))
            .limit(100)
        ).all()
    )
    return [_outcome_payload(row) for row in rows]


@router.get("/outcomes/{outcome_id}")
def get_outcome(
    outcome_id: int,
    db: Session = Depends(get_db),
):
    outcome = db.get(OutcomeSnapshot, outcome_id)
    if outcome is None:
        raise HTTPException(status_code=404, detail="OutcomeSnapshot not found")
    return _outcome_payload(outcome)


@router.get("/regret-events")
def get_regret_events(db: Session = Depends(get_db)):
    rows = list(
        db.scalars(
            select(RegretEvent)
            .order_by(desc(RegretEvent.created_at))
            .limit(100)
        ).all()
    )
    return [_regret_event_payload(row) for row in rows]


@router.get("/regret-events/{event_id}")
def get_regret_event(
    event_id: int,
    db: Session = Depends(get_db),
):
    event = db.get(RegretEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="RegretEvent not found")
    return _regret_event_payload(event)


@router.get("/regret/metrics")
def get_regret_metrics(db: Session = Depends(get_db)):
    return regret_metrics_service.calculate(db=db)
