from backend.app.services.risk_engine import (
    risk_engine,
)


def test_accept_good_trade():
    result = risk_engine.evaluate(
        adjusted_confidence=0.82,
        entry_price=100,
        stop_loss=98,
        target_price=104,
        equity=100000,
        last_equity=100000,
        proposed_position_pct=0.02,
    )

    assert result.decision == "ACCEPT"


def test_reject_low_confidence():
    result = risk_engine.evaluate(
        adjusted_confidence=0.65,
        entry_price=100,
        stop_loss=98,
        target_price=104,
        equity=100000,
        last_equity=100000,
    )

    assert result.decision == "REJECT"

    assert (
        "confidence below minimum threshold"
        in result.reasons
    )


def test_reject_bad_reward_risk():
    result = risk_engine.evaluate(
        adjusted_confidence=0.85,
        entry_price=100,
        stop_loss=98,
        target_price=101,
        equity=100000,
        last_equity=100000,
    )

    assert result.decision == "REJECT"


def test_reject_wide_stop():
    result = risk_engine.evaluate(
        adjusted_confidence=0.85,
        entry_price=100,
        stop_loss=90,
        target_price=120,
        equity=100000,
        last_equity=100000,
    )

    assert result.decision == "REJECT"

    assert (
        "stop distance exceeds maximum"
        in result.reasons
    )


def test_reject_large_position():
    result = risk_engine.evaluate(
        adjusted_confidence=0.85,
        entry_price=100,
        stop_loss=98,
        target_price=104,
        equity=100000,
        last_equity=100000,
        proposed_position_pct=0.10,
    )

    assert result.decision == "REJECT"


def test_reject_daily_loss_limit():
    result = risk_engine.evaluate(
        adjusted_confidence=0.85,
        entry_price=100,
        stop_loss=98,
        target_price=104,
        equity=97000,
        last_equity=100000,
    )

    assert result.decision == "REJECT"

    assert (
        "daily loss limit reached"
        in result.reasons
    )


def test_critic_can_push_trade_below_threshold():
    #
    # Azure originally says 0.80.
    # Kimi challenges by -0.15.
    #
    final_confidence = 0.80 - 0.15

    result = risk_engine.evaluate(
        adjusted_confidence=final_confidence,
        entry_price=100,
        stop_loss=98,
        target_price=104,
        equity=100000,
        last_equity=100000,
    )

    assert final_confidence == 0.65
    assert result.decision == "REJECT"


def test_accepts_exact_safety_boundaries():
    result = risk_engine.evaluate(
        adjusted_confidence=0.70,
        entry_price=100,
        stop_loss=95,
        target_price=107.5,
        equity=98001,
        last_equity=100000,
        proposed_position_pct=0.05,
    )

    assert result.decision == "ACCEPT"


def test_rejects_non_finite_input():
    result = risk_engine.evaluate(
        adjusted_confidence=float("nan"),
        entry_price=100,
        stop_loss=98,
        target_price=104,
        equity=100000,
        last_equity=100000,
    )

    assert result.decision == "REJECT"
    assert "invalid confidence" in result.reasons


def test_rejects_invalid_account_baseline():
    result = risk_engine.evaluate(
        adjusted_confidence=0.85,
        entry_price=100,
        stop_loss=98,
        target_price=104,
        equity=100000,
        last_equity=0,
    )

    assert result.decision == "REJECT"
    assert "invalid last equity" in result.reasons


def test_rejects_non_positive_stop():
    result = risk_engine.evaluate(
        adjusted_confidence=0.85,
        entry_price=100,
        stop_loss=0,
        target_price=104,
        equity=100000,
        last_equity=100000,
    )

    assert result.decision == "REJECT"
    assert "invalid stop loss" in result.reasons
