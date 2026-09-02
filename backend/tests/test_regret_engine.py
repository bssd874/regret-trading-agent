import pytest

from backend.app.services.regret_engine import regret_engine


@pytest.mark.parametrize(
    "decision,pnl,classification",
    [
        ("REJECT", 100.0, "MISSED_ALPHA"),
        ("REJECT", -100.0, "AVOIDED_LOSS"),
        ("ACCEPT", 100.0, "CORRECT_EXECUTION"),
        ("ACCEPT", -100.0, "BAD_EXECUTION"),
    ],
)
def test_regret_classification(decision, pnl, classification):
    result = regret_engine.classify(decision=decision, pnl_amount=pnl)
    assert result.classification == classification


@pytest.mark.parametrize(
    "decision,pnl,expected",
    [
        ("ACCEPT", 100.0, 100.0),
        ("ACCEPT", -100.0, -100.0),
        ("REJECT", 100.0, -100.0),
        ("REJECT", -100.0, 100.0),
    ],
)
def test_decision_value_signs(decision, pnl, expected):
    result = regret_engine.classify(decision=decision, pnl_amount=pnl)
    assert result.decision_value == expected


def test_zero_pnl_boundary_classification():
    assert regret_engine.classify(
        decision="REJECT", pnl_amount=0.0
    ).classification == "AVOIDED_LOSS"
    assert regret_engine.classify(
        decision="ACCEPT", pnl_amount=0.0
    ).classification == "CORRECT_EXECUTION"
