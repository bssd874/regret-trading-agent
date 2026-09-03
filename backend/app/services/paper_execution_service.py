from math import isfinite

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import (
    OrderSide,
    TimeInForce,
)
from alpaca.trading.requests import (
    MarketOrderRequest,
)

from backend.app.core.config import settings


class PaperExecutionService:

    def __init__(self):
        self.client = TradingClient(
            settings.alpaca_api_key,
            settings.alpaca_secret_key,

            # HARD LOCK
            paper=True,
        )

    @staticmethod
    def _enforce_paper_execution() -> None:
        if settings.alpaca_paper is not True:
            raise RuntimeError("REGRET is PAPER ONLY")
        if not settings.paper_execution_enabled:
            raise RuntimeError(
                "Paper execution kill switch is disabled"
            )

    def submit_long_market_order(
        self,
        *,
        symbol: str,
        notional: float,
    ):
        self._enforce_paper_execution()

        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol must not be empty")

        if not isfinite(notional) or notional <= 0:
            raise ValueError(
                "notional must be greater than zero"
            )

        asset = self.client.get_asset(normalized_symbol)
        if getattr(asset, "tradable", False) is not True:
            raise ValueError(
                f"{normalized_symbol} is not tradable on Alpaca paper"
            )
        if getattr(asset, "fractionable", False) is not True:
            raise ValueError(
                f"{normalized_symbol} does not support fractional notional orders"
            )

        request = MarketOrderRequest(
            symbol=normalized_symbol,
            notional=round(notional, 2),
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )

        return self.client.submit_order(
            order_data=request
        )

    def sell_long_market_position(
        self,
        *,
        symbol: str,
        quantity: float,
    ):
        """Submit an explicit PAPER-only SELL for a filled LONG quantity."""
        self._enforce_paper_execution()

        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol must not be empty")

        safe_quantity = float(quantity)
        if not isfinite(safe_quantity) or safe_quantity <= 0:
            raise ValueError(
                "quantity must be greater than zero"
            )

        asset = self.client.get_asset(normalized_symbol)
        if getattr(asset, "tradable", False) is not True:
            raise ValueError(
                f"{normalized_symbol} is not tradable on Alpaca paper"
            )
        if getattr(asset, "fractionable", False) is not True:
            raise ValueError(
                f"{normalized_symbol} does not support fractional orders"
            )

        request = MarketOrderRequest(
            symbol=normalized_symbol,
            qty=safe_quantity,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )

        return self.client.submit_order(
            order_data=request
        )

    def get_order(self, order_id: str):
        if not str(order_id).strip():
            raise ValueError("order_id must not be empty")

        return self.client.get_order_by_id(
            str(order_id)
        )


paper_execution_service = (
    PaperExecutionService()
)
