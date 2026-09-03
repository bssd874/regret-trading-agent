from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from alpaca.trading.enums import OrderSide

from backend.app.core.config import Settings, settings
from backend.app.services import paper_execution_service as service_module
from backend.app.services.paper_execution_service import PaperExecutionService


def _settings_values(**overrides):
    values = {
        "alpaca_api_key": "test-key",
        "alpaca_secret_key": "test-secret",
        "alpaca_paper": True,
        "azure_openai_api_key": "test-key",
        "azure_openai_endpoint": "https://example.invalid/openai/v1",
        "azure_openai_deployment": "test-deployment",
        "nvidia_api_key": "test-key",
    }
    values.update(overrides)
    return values


def test_configuration_rejects_live_alpaca_mode():
    with pytest.raises(ValueError, match="PAPER ONLY"):
        Settings(_env_file=None, **_settings_values(alpaca_paper=False))


def test_execution_kill_switch_defaults_false():
    configured = Settings(_env_file=None, **_settings_values())
    assert configured.paper_execution_enabled is False


def test_autonomous_defaults_are_safe():
    configured = Settings(_env_file=None, **_settings_values())
    assert configured.autonomous_agent_enabled is False
    assert configured.autonomous_cycle_seconds == 300
    assert configured.autonomous_max_candidates_per_cycle == 2
    assert configured.autonomous_stale_cycle_seconds == 900


def test_market_scout_quality_defaults_are_conservative():
    configured = Settings(_env_file=None, **_settings_values())
    assert configured.market_scout_min_price == 5.0
    assert configured.market_scout_min_previous_daily_volume == 500_000
    assert configured.market_scout_max_daily_change_pct == 25.0


@pytest.mark.parametrize(
    "overrides",
    [
        {"autonomous_cycle_seconds": 0},
        {"autonomous_max_candidates_per_cycle": 0},
        {"autonomous_max_candidates_per_cycle": 11},
        {"market_scout_min_price": 0},
        {"market_scout_min_previous_daily_volume": 0},
        {"market_scout_max_daily_change_pct": 0},
        {"market_scout_max_daily_change_pct": 101},
        {
            "autonomous_cycle_seconds": 300,
            "autonomous_stale_cycle_seconds": 300,
        },
    ],
)
def test_autonomous_config_rejects_unsafe_bounds(overrides):
    with pytest.raises(ValueError):
        Settings(_env_file=None, **_settings_values(**overrides))


def test_execution_client_is_hardcoded_to_paper(monkeypatch):
    constructor = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(service_module, "TradingClient", constructor)

    PaperExecutionService()

    assert constructor.call_args.kwargs["paper"] is True


def test_market_order_preflights_fractional_asset(monkeypatch):
    monkeypatch.setattr(settings, "paper_execution_enabled", True)
    service = PaperExecutionService()
    service.client = MagicMock()
    service.client.get_asset.return_value = SimpleNamespace(
        tradable=True,
        fractionable=True,
    )
    service.client.submit_order.return_value = SimpleNamespace(id="paper-1")

    service.submit_long_market_order(symbol="test", notional=125.25)

    service.client.get_asset.assert_called_once_with("TEST")
    request = service.client.submit_order.call_args.kwargs["order_data"]
    assert request.symbol == "TEST"
    assert request.notional == 125.25
    assert request.side == OrderSide.BUY


@pytest.mark.parametrize(
    "asset",
    [
        SimpleNamespace(tradable=False, fractionable=True),
        SimpleNamespace(tradable=True, fractionable=False),
    ],
)
def test_ineligible_asset_never_submits(monkeypatch, asset):
    monkeypatch.setattr(settings, "paper_execution_enabled", True)
    service = PaperExecutionService()
    service.client = MagicMock()
    service.client.get_asset.return_value = asset

    with pytest.raises(ValueError):
        service.submit_long_market_order(symbol="TEST", notional=100.0)

    service.client.submit_order.assert_not_called()
