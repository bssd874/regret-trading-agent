from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from backend.app.models.critic_analysis import CriticAnalysis
from backend.app.models.decision_analysis import DecisionAnalysis
from backend.app.models.risk_decision import RiskDecision
from backend.app.schemas.decision import (
    CriticAnalysisOutput,
    DecisionAnalysisOutput,
)
from backend.app.services.decision_pipeline import DecisionPipeline


class StubAnalyst:
    def __init__(self, confidence=0.82):
        self.confidence = confidence

    def analyze(self, candidate):
        return DecisionAnalysisOutput(
            symbol=candidate.symbol,
            direction="LONG",
            thesis="Momentum and volume support a cautious long thesis.",
            confidence=self.confidence,
            entry_price=candidate.entry_price,
            stop_loss=candidate.entry_price * 0.98,
            target_price=candidate.entry_price * 1.04,
            horizon_minutes=60,
            invalidation="Price falls below the deterministic stop level.",
            evidence_summary=["Price and volume came from the candidate."],
        )


class BrokenAnalyst:
    def analyze(self, candidate):
        raise ValueError("malformed analyst output")


class StubCritic:
    def __init__(self, adjustment=-0.05):
        self.adjustment = adjustment

    def critique(self, *, candidate, analysis):
        return CriticAnalysisOutput(
            verdict="CHALLENGE" if self.adjustment else "PASS",
            confidence_adjustment=self.adjustment,
            thesis_consistency=0.8,
            concerns=["Evidence remains limited."] if self.adjustment else [],
        )


class BrokenCritic:
    def critique(self, *, candidate, analysis):
        raise ValueError("malformed critic output")


class StubAccountProvider:
    def get_account(self):
        return SimpleNamespace(equity="100000", last_equity="100000")


class BrokenAccountProvider:
    def get_account(self):
        raise ConnectionError("paper account unavailable")


def build_pipeline(*, analyst=None, critic=None, account_provider=None):
    return DecisionPipeline(
        analyst=analyst or StubAnalyst(),
        critic=critic or StubCritic(),
        account_provider=account_provider or StubAccountProvider(),
    )


def _count(db_session, model):
    return db_session.scalar(select(func.count()).select_from(model))


def test_accept_scenario_persists_full_chain(db_session, candidate_factory):
    candidate = candidate_factory()
    result = build_pipeline().run(db=db_session, candidate_id=candidate.id)

    assert result["risk"]["decision"] == "ACCEPT"
    assert result["candidate_status"] == "ACCEPTED"
    assert result["order_submitted"] is False
    assert candidate.status == "ACCEPTED"
    assert _count(db_session, DecisionAnalysis) == 1
    assert _count(db_session, CriticAnalysis) == 1
    assert _count(db_session, RiskDecision) == 1


def test_reject_scenario_remains_persisted(db_session, candidate_factory):
    candidate = candidate_factory()
    pipeline = build_pipeline(
        analyst=StubAnalyst(confidence=0.75),
        critic=StubCritic(adjustment=-0.10),
    )
    result = pipeline.run(db=db_session, candidate_id=candidate.id)

    assert result["risk"]["decision"] == "REJECT"
    assert result["candidate_status"] == "REJECTED"
    assert candidate.status == "REJECTED"
    assert _count(db_session, DecisionAnalysis) == 1
    assert _count(db_session, CriticAnalysis) == 1
    assert _count(db_session, RiskDecision) == 1


def test_analysis_failure_is_not_reject(db_session, candidate_factory):
    candidate = candidate_factory()

    with pytest.raises(RuntimeError, match="Azure analyst failed"):
        build_pipeline(analyst=BrokenAnalyst()).run(
            db=db_session,
            candidate_id=candidate.id,
        )

    assert candidate.status == "ANALYSIS_FAILED"
    assert _count(db_session, DecisionAnalysis) == 0
    assert _count(db_session, RiskDecision) == 0


def test_critic_failure_is_not_pass(db_session, candidate_factory):
    candidate = candidate_factory()

    with pytest.raises(RuntimeError, match="Kimi critic failed"):
        build_pipeline(critic=BrokenCritic()).run(
            db=db_session,
            candidate_id=candidate.id,
        )

    assert candidate.status == "CRITIC_FAILED"
    assert _count(db_session, DecisionAnalysis) == 1
    assert _count(db_session, CriticAnalysis) == 0
    assert _count(db_session, RiskDecision) == 0


def test_risk_data_failure_never_accepts(db_session, candidate_factory):
    candidate = candidate_factory()

    with pytest.raises(RuntimeError, match="Risk review failed"):
        build_pipeline(account_provider=BrokenAccountProvider()).run(
            db=db_session,
            candidate_id=candidate.id,
        )

    assert candidate.status == "RISK_FAILED"
    assert _count(db_session, DecisionAnalysis) == 1
    assert _count(db_session, CriticAnalysis) == 1
    assert _count(db_session, RiskDecision) == 0


def test_candidate_cannot_be_analyzed_twice(db_session, candidate_factory):
    candidate = candidate_factory()
    pipeline = build_pipeline()
    pipeline.run(db=db_session, candidate_id=candidate.id)

    with pytest.raises(ValueError, match="status NEW"):
        pipeline.run(db=db_session, candidate_id=candidate.id)

    assert _count(db_session, RiskDecision) == 1
