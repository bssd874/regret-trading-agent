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


router = APIRouter()


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
            "provider": "nvidia",
            "model": critic.model_name,
            "verdict": critic.verdict,
            "confidence_adjustment": critic.confidence_adjustment,
            "thesis_consistency": critic.thesis_consistency,
            "concerns": _load_json_list(critic.concerns),
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
