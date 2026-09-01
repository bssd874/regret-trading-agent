import pytest

from backend.app.services.consensus_engine import (
    consensus_engine,
)


def test_consensus_reduces_confidence():
    result = consensus_engine.combine(
        analyst_confidence=0.82,
        critic_adjustment=-0.10,
    )

    assert result.adjusted_confidence == 0.72


def test_consensus_pass_keeps_confidence():
    result = consensus_engine.combine(
        analyst_confidence=0.84,
        critic_adjustment=0.0,
    )

    assert result.adjusted_confidence == 0.84


def test_consensus_clamps_to_zero():
    result = consensus_engine.combine(
        analyst_confidence=0.05,
        critic_adjustment=-0.20,
    )

    assert result.adjusted_confidence == 0.0


def test_consensus_rejects_positive_adjustment():
    with pytest.raises(ValueError):
        consensus_engine.combine(
            analyst_confidence=0.80,
            critic_adjustment=0.10,
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_consensus_rejects_non_finite_confidence(value):
    with pytest.raises(ValueError):
        consensus_engine.combine(
            analyst_confidence=value,
            critic_adjustment=0.0,
        )


def test_consensus_rejects_adjustment_below_limit():
    with pytest.raises(ValueError):
        consensus_engine.combine(
            analyst_confidence=0.80,
            critic_adjustment=-0.21,
        )
