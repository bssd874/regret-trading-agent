from dataclasses import dataclass
from math import isfinite

from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.historical.screener import ScreenerClient

from alpaca.data.requests import (
    MarketMoversRequest,
    MostActivesRequest,
    StockSnapshotRequest,
)

from alpaca.data.enums import (
    MarketType,
    MostActivesBy,
)

from alpaca.trading.client import TradingClient

from backend.app.core.config import settings


@dataclass(frozen=True)
class EvaluationPrice:
    price: float
    source: str


class AlpacaService:

    def __init__(self):
        self.trading_client = TradingClient(
            settings.alpaca_api_key,
            settings.alpaca_secret_key,
            # REGRET is paper-only. Do not make this configurable.
            paper=True,
        )

        self.stock_client = StockHistoricalDataClient(
            settings.alpaca_api_key,
            settings.alpaca_secret_key,
        )

        self.screener_client = ScreenerClient(
            settings.alpaca_api_key,
            settings.alpaca_secret_key,
        )

    def get_account(self):
        return self.trading_client.get_account()

    def get_snapshots(self, symbols: list[str]):
        request = StockSnapshotRequest(
            symbol_or_symbols=symbols,
        )

        return self.stock_client.get_stock_snapshot(request)

    def get_evaluation_price(self, symbol: str) -> EvaluationPrice:
        """Return the best available read-only Alpaca reference price."""
        normalized = symbol.strip().upper()
        if not normalized:
            raise ValueError("symbol must not be empty")

        snapshot = self.get_snapshots([normalized]).get(normalized)
        if snapshot is None:
            raise LookupError(f"No Alpaca snapshot available for {normalized}")

        candidates = (
            (getattr(snapshot, "latest_trade", None), "price", "latest_trade"),
            (getattr(snapshot, "minute_bar", None), "close", "minute_bar"),
            (getattr(snapshot, "daily_bar", None), "close", "daily_bar"),
        )
        for item, attribute, source in candidates:
            value = getattr(item, attribute, None) if item is not None else None
            if value is None:
                continue
            price = float(value)
            if isfinite(price) and price > 0:
                return EvaluationPrice(price=price, source=source)

        raise ValueError(f"No positive finite Alpaca price available for {normalized}")

    def get_market_movers(self, top: int = 10):
        request = MarketMoversRequest(
            market_type=MarketType.STOCKS,
            top=top,
        )

        return self.screener_client.get_market_movers(
            request
        )

    def get_most_actives(self, top: int = 10):
        request = MostActivesRequest(
            by=MostActivesBy.VOLUME,
            top=top,
        )

        return self.screener_client.get_most_actives(
            request
        )


alpaca_service = AlpacaService()
