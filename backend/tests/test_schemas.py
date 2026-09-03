import pytest
from pydantic import ValidationError

from backend.app.schemas.decision import (
    CriticAnalysisOutput,
    DecisionAnalysisOutput,
)


def _analysis_payload():
    return {
        "symbol": "TEST",
        "direction": "LONG",
        "thesis": "Momentum and volume support a cautious long thesis.",
        "confidence": 0.8,
        "entry_price": 100.0,
        "stop_loss": 98.0,
        "target_price": 104.0,
        "horizon_minutes": 60,
        "invalidation": "Price falls below the supplied stop level.",
        "evidence_summary": ["Price rose 3% with 2x relative volume."],
    }


def test_analyst_schema_accepts_valid_structured_output():
    result = DecisionAnalysisOutput.model_validate(_analysis_payload())
    assert result.direction == "LONG"


def test_analyst_schema_accepts_confidence_above_point_seven():
    payload = _analysis_payload()
    payload["confidence"] = 0.91

    result = DecisionAnalysisOutput.model_validate(payload)

    assert result.confidence == 0.91


def test_analyst_schema_rejects_invalid_levels():
    payload = _analysis_payload()
    payload["stop_loss"] = 101.0

    with pytest.raises(ValidationError):
        DecisionAnalysisOutput.model_validate(payload)


def test_critic_schema_rejects_positive_adjustment():
    with pytest.raises(ValidationError):
        CriticAnalysisOutput.model_validate(
            {
                "verdict": "CHALLENGE",
                "confidence_adjustment": 0.01,
                "thesis_consistency": 0.8,
                "concerns": [],
            }
        )


def test_critic_schema_rejects_trade_generation_fields():
    with pytest.raises(ValidationError):
        CriticAnalysisOutput.model_validate(
            {
                "verdict": "CHALLENGE",
                "confidence_adjustment": -0.1,
                "thesis_consistency": 0.6,
                "concerns": ["Evidence is limited."],
                "entry_price": 99.0,
            }
        )


def test_critic_pass_cannot_reduce_confidence():
    with pytest.raises(ValidationError):
        CriticAnalysisOutput.model_validate(
            {
                "verdict": "PASS",
                "confidence_adjustment": -0.01,
                "thesis_consistency": 0.9,
                "concerns": [],
            }
        )


def test_critic_pass_preserves_confidence_without_concerns():
    result = CriticAnalysisOutput.model_validate(
        {
            "verdict": "PASS",
            "confidence_adjustment": 0.0,
            "thesis_consistency": 0.9,
            "concerns": [],
        }
    )

    assert result.verdict == "PASS"
    assert result.confidence_adjustment == 0.0


@pytest.mark.parametrize(
    "payload",
    [
        {
            "verdict": "CHALLENGE",
            "confidence_adjustment": 0.0,
            "thesis_consistency": 0.8,
            "concerns": ["Concrete supplied-evidence concern."],
        },
        {
            "verdict": "CHALLENGE",
            "confidence_adjustment": -0.15,
            "thesis_consistency": 0.8,
            "concerns": [],
        },
        {
            "verdict": "PASS",
            "confidence_adjustment": 0.0,
            "thesis_consistency": 0.8,
            "concerns": ["A material concern contradicts PASS."],
        },
    ],
)
def test_critic_verdict_requires_consistent_adjustment_and_concerns(payload):
    with pytest.raises(ValidationError):
        CriticAnalysisOutput.model_validate(payload)
