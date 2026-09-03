import json

import pytest
from pydantic import ValidationError

from backend.app.schemas.decision import (
    CriticAnalysisOutput,
    DecisionAnalysisOutput,
)
from backend.app.services.critic_agent import CriticAgent
from backend.app.services.decision_agent import DecisionAgent


class FakeProvider:
    def __init__(self, payload):
        self.payload = payload
        self.response_model = None
        self.prompt = None

    def generate(self, prompt, *, response_model):
        self.prompt = prompt
        self.response_model = response_model
        return json.dumps(self.payload)


def _analysis_payload():
    return {
        "symbol": "TEST",
        "direction": "LONG",
        "thesis": "Supplied momentum and volume support a cautious thesis.",
        "confidence": 0.8,
        "entry_price": 100.0,
        "stop_loss": 98.0,
        "target_price": 104.0,
        "horizon_minutes": 60,
        "invalidation": "The thesis fails below the supplied stop level.",
        "evidence_summary": ["Price rose 3% with 2x relative volume."],
    }


def test_decision_agent_requests_and_validates_schema(candidate_factory):
    provider = FakeProvider(_analysis_payload())
    result = DecisionAgent(provider).analyze(candidate_factory())

    assert provider.response_model is DecisionAnalysisOutput
    assert result.symbol == "TEST"


def test_decision_agent_preserves_evidence_driven_confidence_above_point_seven(
    candidate_factory,
):
    payload = _analysis_payload()
    payload["confidence"] = 0.8375
    provider = FakeProvider(payload)

    result = DecisionAgent(provider).analyze(candidate_factory())

    assert result.confidence == 0.8375
    assert "full continuous 0-to-1 confidence range" in provider.prompt
    assert "Do not round confidence into fixed buckets" in provider.prompt
    assert "must not be increased" in provider.prompt


def test_decision_agent_rejects_large_entry_deviation(candidate_factory):
    payload = _analysis_payload()
    payload["entry_price"] = 103.0
    provider = FakeProvider(payload)

    with pytest.raises(ValueError, match="deviates"):
        DecisionAgent(provider).analyze(candidate_factory())


def test_critic_agent_rejects_new_trade_fields(candidate_factory):
    payload = {
        "verdict": "CHALLENGE",
        "confidence_adjustment": -0.1,
        "thesis_consistency": 0.6,
        "concerns": ["Evidence is limited."],
        "target_price": 110.0,
    }
    provider = FakeProvider(payload)
    analysis = DecisionAnalysisOutput.model_validate(_analysis_payload())

    with pytest.raises(ValidationError):
        CriticAgent(provider).critique(
            candidate=candidate_factory(),
            analysis=analysis,
        )

    assert provider.response_model is CriticAnalysisOutput


def test_consistent_synthetic_evidence_can_legitimately_receive_pass(
    candidate_factory,
):
    provider = FakeProvider(
        {
            "verdict": "PASS",
            "confidence_adjustment": 0.0,
            "thesis_consistency": 0.93,
            "concerns": [],
        }
    )
    analysis = DecisionAnalysisOutput.model_validate(_analysis_payload())

    result = CriticAgent(provider).critique(
        candidate=candidate_factory(price_change_pct=4.0, volume_ratio=2.2),
        analysis=analysis,
    )

    assert result.verdict == "PASS"
    assert result.confidence_adjustment == 0.0
    assert result.concerns == []
    assert "not defaulting to CHALLENGE" in provider.prompt
    assert "Do not invent or manufacture a concern" in provider.prompt


@pytest.mark.parametrize(
    "missing_field",
    ["verdict", "confidence_adjustment"],
)
def test_critic_missing_required_values_fail_instead_of_defaulting(
    candidate_factory,
    missing_field,
):
    payload = {
        "verdict": "CHALLENGE",
        "confidence_adjustment": -0.15,
        "thesis_consistency": 0.6,
        "concerns": ["Supplied volume does not support the thesis."],
    }
    payload.pop(missing_field)
    provider = FakeProvider(payload)

    with pytest.raises(ValidationError):
        CriticAgent(provider).critique(
            candidate=candidate_factory(),
            analysis=DecisionAnalysisOutput.model_validate(_analysis_payload()),
        )
