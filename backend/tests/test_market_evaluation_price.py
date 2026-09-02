from types import SimpleNamespace

import pytest

from backend.app.services.alpaca_service import AlpacaService


def _service_with_snapshot(snapshot):
    service = AlpacaService()
    service.get_snapshots = lambda symbols: {symbols[0]: snapshot}
    return service


def test_evaluation_price_prefers_latest_trade():
    result = _service_with_snapshot(
        SimpleNamespace(
            latest_trade=SimpleNamespace(price=101.0),
            minute_bar=SimpleNamespace(close=100.0),
            daily_bar=SimpleNamespace(close=99.0),
        )
    ).get_evaluation_price("test")
    assert result.price == 101.0
    assert result.source == "latest_trade"


def test_evaluation_price_falls_back_to_minute_bar():
    result = _service_with_snapshot(
        SimpleNamespace(
            latest_trade=None,
            minute_bar=SimpleNamespace(close=100.0),
            daily_bar=SimpleNamespace(close=99.0),
        )
    ).get_evaluation_price("TEST")
    assert result.price == 100.0
    assert result.source == "minute_bar"


def test_evaluation_price_falls_back_to_daily_bar():
    result = _service_with_snapshot(
        SimpleNamespace(
            latest_trade=None,
            minute_bar=None,
            daily_bar=SimpleNamespace(close=99.0),
        )
    ).get_evaluation_price("TEST")
    assert result.price == 99.0
    assert result.source == "daily_bar"


def test_evaluation_price_failure_is_explicit():
    service = _service_with_snapshot(SimpleNamespace())
    with pytest.raises(ValueError, match="No positive finite"):
        service.get_evaluation_price("TEST")
