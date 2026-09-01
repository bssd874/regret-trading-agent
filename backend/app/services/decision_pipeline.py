import json
from typing import Protocol

from sqlalchemy import update
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.candidate_trade import CandidateTrade
from backend.app.models.critic_analysis import CriticAnalysis
from backend.app.models.decision_analysis import DecisionAnalysis
from backend.app.models.risk_decision import RiskDecision
from backend.app.services.alpaca_service import alpaca_service
from backend.app.services.consensus_engine import ConsensusEngine, consensus_engine
from backend.app.services.critic_agent import CriticAgent, critic_agent
from backend.app.services.decision_agent import DecisionAgent, decision_agent
from backend.app.services.risk_engine import RiskEngine, risk_engine


class AccountProvider(Protocol):
    def get_account(self):
        ...


class DecisionPipeline:
    def __init__(
        self,
        *,
        analyst: DecisionAgent = decision_agent,
        critic: CriticAgent = critic_agent,
        consensus: ConsensusEngine = consensus_engine,
        risk: RiskEngine = risk_engine,
        account_provider: AccountProvider = alpaca_service,
    ) -> None:
        self.analyst = analyst
        self.critic = critic
        self.consensus = consensus
        self.risk = risk
        self.account_provider = account_provider

    @staticmethod
    def _set_status(
        db: Session,
        candidate: CandidateTrade,
        status: str,
    ) -> None:
        candidate.status = status
        db.commit()

    def run(
        self,
        *,
        db: Session,
        candidate_id: int,
    ) -> dict:
        candidate = db.get(CandidateTrade, candidate_id)

        if candidate is None:
            raise LookupError(f"Candidate {candidate_id} not found")

        # Atomic NEW -> ANALYZING transition prevents two requests from
        # producing separate decision chains for the same candidate.
        claimed = db.execute(
            update(CandidateTrade)
            .where(
                CandidateTrade.id == candidate_id,
                CandidateTrade.status == "NEW",
            )
            .values(status="ANALYZING")
        )

        if claimed.rowcount != 1:
            db.rollback()
            db.refresh(candidate)
            raise ValueError(
                "Candidate must have status NEW. "
                f"Current status: {candidate.status}"
            )

        db.commit()
        db.refresh(candidate)

        # 1. Azure is the primary analyst.
        try:
            analysis_output = self.analyst.analyze(candidate)
        except Exception as exc:
            db.rollback()
            self._set_status(db, candidate, "ANALYSIS_FAILED")
            raise RuntimeError(f"Azure analyst failed: {exc}") from exc

        analysis = DecisionAnalysis(
            candidate_id=candidate.id,
            symbol=candidate.symbol,
            direction=analysis_output.direction,
            thesis=analysis_output.thesis,
            analyst_confidence=analysis_output.confidence,
            entry_price=analysis_output.entry_price,
            stop_loss=analysis_output.stop_loss,
            target_price=analysis_output.target_price,
            horizon_minutes=analysis_output.horizon_minutes,
            invalidation=analysis_output.invalidation,
            evidence_summary=json.dumps(analysis_output.evidence_summary),
            provider="azure",
            model_name=settings.azure_openai_deployment,
        )
        db.add(analysis)
        db.commit()
        db.refresh(analysis)

        # 2. Kimi can only criticize the primary analysis.
        self._set_status(db, candidate, "CRITIQUING")

        try:
            critic_output = self.critic.critique(
                candidate=candidate,
                analysis=analysis_output,
            )
        except Exception as exc:
            db.rollback()
            self._set_status(db, candidate, "CRITIC_FAILED")
            raise RuntimeError(f"Kimi critic failed: {exc}") from exc

        critic = CriticAnalysis(
            candidate_id=candidate.id,
            analysis_id=analysis.id,
            verdict=critic_output.verdict,
            confidence_adjustment=critic_output.confidence_adjustment,
            thesis_consistency=critic_output.thesis_consistency,
            concerns=json.dumps(critic_output.concerns),
            provider="nvidia",
            model_name=settings.nvidia_model,
        )
        db.add(critic)
        db.commit()
        db.refresh(critic)

        # 3. Consensus is deterministic Python. Kimi can only preserve or
        # reduce the analyst confidence by at most 0.20.
        consensus_output = self.consensus.combine(
            analyst_confidence=analysis_output.confidence,
            critic_adjustment=critic_output.confidence_adjustment,
        )

        # 4. The deterministic risk engine is final authority.
        self._set_status(db, candidate, "RISK_REVIEW")

        try:
            account = self.account_provider.get_account()
            risk_output = self.risk.evaluate(
                adjusted_confidence=consensus_output.adjusted_confidence,
                entry_price=analysis_output.entry_price,
                stop_loss=analysis_output.stop_loss,
                target_price=analysis_output.target_price,
                equity=float(account.equity),
                last_equity=float(account.last_equity),
                proposed_position_pct=0.02,
            )
        except Exception as exc:
            db.rollback()
            self._set_status(db, candidate, "RISK_FAILED")
            raise RuntimeError(f"Risk review failed: {exc}") from exc

        risk = RiskDecision(
            candidate_id=candidate.id,
            analysis_id=analysis.id,
            critic_id=critic.id,
            original_confidence=consensus_output.original_confidence,
            critic_adjustment=consensus_output.critic_adjustment,
            adjusted_confidence=consensus_output.adjusted_confidence,
            reward_risk_ratio=risk_output.reward_risk_ratio,
            proposed_position_pct=risk_output.proposed_position_pct,
            risk_score=risk_output.risk_score,
            decision=risk_output.decision,
            reasons=json.dumps(risk_output.reasons),
        )
        db.add(risk)
        candidate.status = (
            "ACCEPTED" if risk_output.decision == "ACCEPT" else "REJECTED"
        )
        db.commit()
        db.refresh(risk)
        db.refresh(candidate)

        return {
            "candidate_id": candidate.id,
            "analysis_id": analysis.id,
            "critic_id": critic.id,
            "decision_id": risk.id,
            "symbol": candidate.symbol,
            "analyst": {
                "provider": "azure",
                "model": settings.azure_openai_deployment,
                "symbol": analysis.symbol,
                "direction": analysis.direction,
                "thesis": analysis.thesis,
                "confidence": consensus_output.original_confidence,
                "entry_price": analysis.entry_price,
                "stop_loss": analysis.stop_loss,
                "target_price": analysis.target_price,
                "horizon_minutes": analysis.horizon_minutes,
                "invalidation": analysis.invalidation,
                "evidence": analysis_output.evidence_summary,
            },
            "critic": {
                "provider": "nvidia",
                "model": settings.nvidia_model,
                "verdict": critic.verdict,
                "confidence_adjustment": critic.confidence_adjustment,
                "thesis_consistency": critic.thesis_consistency,
                "concerns": critic_output.concerns,
            },
            "consensus": {
                "original_confidence": consensus_output.original_confidence,
                "critic_adjustment": consensus_output.critic_adjustment,
                "adjusted_confidence": consensus_output.adjusted_confidence,
            },
            "risk": {
                "decision": risk_output.decision,
                "risk_score": risk_output.risk_score,
                "reward_risk_ratio": risk_output.reward_risk_ratio,
                "proposed_position_pct": risk_output.proposed_position_pct,
                "reasons": risk_output.reasons,
            },
            "candidate_status": candidate.status,
            "order_submitted": False,
        }


decision_pipeline = DecisionPipeline()
