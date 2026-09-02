import pytest

from backend.app.services.outcome_engine import outcome_engine


def test_shadow_profit_pnl_math():
    result = outcome_engine.calculate_long(
        entry_price=100.0,
        evaluation_price=110.0,
        notional=1000.0,
    )
    assert result.quantity == 10.0
    assert result.pnl_pct == pytest.approx(0.10)
    assert result.pnl_amount == pytest.approx(100.0)


def test_shadow_loss_pnl_math():
    result = outcome_engine.calculate_long(
        entry_price=100.0,
        evaluation_price=90.0,
        notional=1000.0,
    )
    assert result.pnl_pct == pytest.approx(-0.10)
    assert result.pnl_amount == pytest.approx(-100.0)


def test_executed_profit_pnl_math():
    result = outcome_engine.calculate_long(
        entry_price=50.0,
        evaluation_price=55.0,
        notional=1000.0,
    )
    assert result.quantity == 20.0
    assert result.pnl_amount == pytest.approx(100.0)


def test_executed_loss_pnl_math():
    result = outcome_engine.calculate_long(
        entry_price=50.0,
        evaluation_price=45.0,
        notional=1000.0,
    )
    assert result.quantity == 20.0
    assert result.pnl_amount == pytest.approx(-100.0)


@pytest.mark.parametrize(
    "field,value",
    [
        ("entry_price", 0.0),
        ("evaluation_price", float("nan")),
        ("notional", -1.0),
    ],
)
def test_outcome_math_rejects_invalid_values(field, value):
    values = {
        "entry_price": 100.0,
        "evaluation_price": 101.0,
        "notional": 1000.0,
    }
    values[field] = value
    with pytest.raises(ValueError, match="positive finite"):
        outcome_engine.calculate_long(**values)
