import json

import pytest
from pydantic import ValidationError

from backend.app.core.config import settings
from backend.app.models.critic_analysis import CriticAnalysis
from backend.app.schemas.decision import CriticAnalysisOutput, DecisionAnalysisOutput
from backend.app.services.critic_agent import CriticAgent
from backend.tests.test_decision_pipeline import (
    StubAccountProvider,
    StubAnalyst,
    build_pipeline,
)


class FakeProvider:
    def __init__(self, *, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = 0
        self.response_model = None
        self.prompts = []

    def generate(self, prompt, *, response_model):
        self.calls += 1
        self.prompts.append(prompt)
        self.response_model = response_model
        if self.error is not None:
            raise self.error
        return json.dumps(self.payload)


class StatusFailure(Exception):
    def __init__(self, status_code):
        self.status_code = status_code


def _analysis():
    return DecisionAnalysisOutput(
        symbol="TEST",
        direction="LONG",
        thesis="Momentum and volume support a cautious long thesis.",
        confidence=0.8,
        entry_price=100.0,
        stop_loss=98.0,
        target_price=104.0,
        horizon_minutes=60,
        invalidation="Price falls below the supplied stop level.",
        evidence_summary=["Only supplied price and volume evidence was used."],
    )


def _valid_critic(adjustment=-0.05):
    return {
        "verdict": "CHALLENGE" if adjustment else "PASS",
        "confidence_adjustment": adjustment,
        "thesis_consistency": 0.8,
        "concerns": ["The evidence is limited."] if adjustment else [],
    }


def test_kimi_success_uses_nvidia_provider(candidate_factory):
    primary = FakeProvider(payload=_valid_critic())
    fallback = FakeProvider(payload=_valid_critic())

    review = CriticAgent(primary, fallback).critique_with_metadata(
        candidate=candidate_factory(),
        analysis=_analysis(),
    )

    assert review.provider == "nvidia"
    assert review.model_name == settings.nvidia_model
    assert review.degraded_mode is False
    assert fallback.calls == 0


def test_kimi_timeout_invokes_strict_azure_fallback(candidate_factory):
    primary = FakeProvider(error=TimeoutError("provider timed out"))
    fallback = FakeProvider(payload=_valid_critic())

    review = CriticAgent(primary, fallback).critique_with_metadata(
        candidate=candidate_factory(),
        analysis=_analysis(),
    )

    assert review.provider == "azure-fallback"
    assert review.model_name == settings.azure_openai_deployment
    assert review.degraded_mode is True
    assert fallback.response_model is CriticAnalysisOutput
    assert primary.prompts == fallback.prompts
    assert "not defaulting to CHALLENGE" in fallback.prompts[0]


@pytest.mark.parametrize("status_code", [429, 500, 503])
def test_provider_http_availability_failure_invokes_fallback(
    candidate_factory,
    status_code,
):
    fallback = FakeProvider(payload=_valid_critic())
    review = CriticAgent(
        FakeProvider(error=StatusFailure(status_code)),
        fallback,
    ).critique_with_metadata(
        candidate=candidate_factory(),
        analysis=_analysis(),
    )

    assert review.provider == "azure-fallback"
    assert fallback.calls == 1


def test_non_availability_http_error_does_not_fallback(candidate_factory):
    fallback = FakeProvider(payload=_valid_critic())

    with pytest.raises(StatusFailure):
        CriticAgent(
            FakeProvider(error=StatusFailure(400)),
            fallback,
        ).critique_with_metadata(
            candidate=candidate_factory(),
            analysis=_analysis(),
        )

    assert fallback.calls == 0


def test_azure_fallback_cannot_increase_confidence(candidate_factory):
    primary = FakeProvider(error=ConnectionError("provider unavailable"))
    fallback = FakeProvider(payload=_valid_critic(adjustment=0.01))

    with pytest.raises(ValidationError):
        CriticAgent(primary, fallback).critique_with_metadata(
            candidate=candidate_factory(),
            analysis=_analysis(),
        )


def test_both_critic_providers_failing_stays_failed(candidate_factory):
    primary = FakeProvider(error=TimeoutError("primary timeout"))
    fallback = FakeProvider(error=ConnectionError("fallback unavailable"))

    with pytest.raises(ConnectionError, match="fallback unavailable"):
        CriticAgent(primary, fallback).critique_with_metadata(
            candidate=candidate_factory(),
            analysis=_analysis(),
        )


def test_schema_invalid_kimi_does_not_invoke_fallback(candidate_factory):
    invalid = _valid_critic()
    invalid["entry_price"] = 100.0
    primary = FakeProvider(payload=invalid)
    fallback = FakeProvider(payload=_valid_critic())

    with pytest.raises(ValidationError):
        CriticAgent(primary, fallback).critique_with_metadata(
            candidate=candidate_factory(),
            analysis=_analysis(),
        )

    assert fallback.calls == 0


def test_fallback_provenance_is_persisted(db_session, candidate_factory):
    primary = FakeProvider(error=TimeoutError("provider timed out"))
    fallback = FakeProvider(payload=_valid_critic())
    critic = CriticAgent(primary, fallback)
    candidate = candidate_factory()

    result = build_pipeline(
        analyst=StubAnalyst(),
        critic=critic,
        account_provider=StubAccountProvider(),
    ).run(db=db_session, candidate_id=candidate.id)

    persisted = db_session.get(CriticAnalysis, result["critic_id"])
    assert persisted.provider == "azure-fallback"
    assert persisted.model_name == settings.azure_openai_deployment
    assert result["critic"]["degraded_mode"] is True


def test_complete_critic_failure_produces_critic_failed(
    db_session,
    candidate_factory,
):
    critic = CriticAgent(
        FakeProvider(error=TimeoutError("primary timeout")),
        FakeProvider(error=ConnectionError("fallback unavailable")),
    )
    candidate = candidate_factory()

    with pytest.raises(RuntimeError, match="Kimi critic failed"):
        build_pipeline(critic=critic).run(
            db=db_session,
            candidate_id=candidate.id,
        )

    assert candidate.status == "CRITIC_FAILED"
