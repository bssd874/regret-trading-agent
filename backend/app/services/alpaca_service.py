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
