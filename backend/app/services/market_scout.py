import re
from math import isfinite
from typing import Protocol

from sqlalchemy.orm import Session

from backend.app.core.config import Settings, settings
from backend.app.models.candidate_trade import CandidateTrade
from backend.app.services.alpaca_service import alpaca_service


DEFAULT_UNIVERSE = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMD",
    "AMZN",
    "META",
    "GOOGL",
    "TSLA",
    "SPY",
    "QQQ",
]

ALLOWED_US_EXCHANGES = frozenset(
    {"NASDAQ", "NYSE", "AMEX", "ARCA", "NYSEARCA", "BATS"}
)
NON_STANDARD_SECURITY_NAME = re.compile(
    r"\b(warrant|warrants|unit|units|right|rights)\b",
    re.IGNORECASE,
)


class MarketDataService(Protocol):
    def get_market_movers(self, top: int = 10):
        ...

    def get_asset(self, symbol: str):
        ...

    def get_snapshots(self, symbols: list[str]):
        ...


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value) or "").strip()


class MarketScout:
    """Build momentum candidates after deterministic execution-quality gates."""

    def __init__(
        self,
        market_data: MarketDataService = alpaca_service,
        config: Settings = settings,
    ) -> None:
        self.market_data = market_data
        self.config = config

    def _get_universe(self) -> tuple[list[str], str]:
        try:
            movers = self.market_data.get_market_movers(top=10)
            symbols = [
                str(mover.symbol).strip().upper()
                for mover in movers.gainers
                if str(getattr(mover, "symbol", "")).strip()
            ]
            symbols = list(dict.fromkeys(symbols))
            if symbols:
                return symbols[:10], "alpaca_movers"
        except Exception as exc:
            print("[MarketScout] Movers unavailable:", exc)

        return DEFAULT_UNIVERSE, "watchlist"

    @staticmethod
    def _asset_is_eligible(symbol: str, asset: object) -> bool:
        asset_symbol = _enum_value(getattr(asset, "symbol", "")).upper()
        if asset_symbol and asset_symbol != symbol:
            return False
        if _enum_value(getattr(asset, "asset_class", "")).lower() != "us_equity":
            return False
        if _enum_value(getattr(asset, "status", "")).lower() != "active":
            return False
        if _enum_value(getattr(asset, "exchange", "")).upper() not in (
            ALLOWED_US_EXCHANGES
        ):
            return False
        if getattr(asset, "tradable", False) is not True:
            return False
        if getattr(asset, "fractionable", False) is not True:
            return False

        name = str(getattr(asset, "name", "") or "")
        return NON_STANDARD_SECURITY_NAME.search(name) is None

    def _eligible_symbols(self, symbols: list[str]) -> list[str]:
        eligible: list[str] = []
        for symbol in symbols:
            normalized = str(symbol).strip().upper()
            if not normalized:
                continue
            try:
                asset = self.market_data.get_asset(normalized)
            except Exception as exc:
                print(f"[MarketScout] Asset metadata unavailable for {normalized}:", exc)
                continue
            if self._asset_is_eligible(normalized, asset):
                eligible.append(normalized)
        return eligible

    def _build_candidate(
        self,
        symbol: str,
        snapshot,
        source: str,
    ) -> dict | None:
        daily = getattr(snapshot, "daily_bar", None)
        previous = getattr(snapshot, "previous_daily_bar", None)
        if daily is None or previous is None:
            return None

        try:
            current_price = float(daily.close)
            previous_close = float(previous.close)
            current_volume = float(daily.volume or 0)
            previous_volume = float(previous.volume or 0)
        except (TypeError, ValueError, AttributeError):
            return None

        values = (
            current_price,
            previous_close,
            current_volume,
            previous_volume,
        )
        if not all(isfinite(value) for value in values):
            return None
        if current_price < self.config.market_scout_min_price:
            return None
        if previous_close <= 0 or current_volume <= 0:
            return None
        if previous_volume < self.config.market_scout_min_previous_daily_volume:
            return None

        change_pct = ((current_price - previous_close) / previous_close) * 100
        if not 0 < change_pct <= self.config.market_scout_max_daily_change_pct:
            return None

        volume_ratio = current_volume / previous_volume
        scout_score = max(change_pct, 0) + min(volume_ratio, 3.0)

        return {
            "symbol": symbol,
            "side": "BUY",
            "strategy": "momentum",
            "entry_price": current_price,
            "price_change_pct": round(change_pct, 4),
            "volume_ratio": round(volume_ratio, 4),
            "scout_score": round(scout_score, 4),
            "source": source,
        }

    def _screen_universe(self, symbols: list[str], source: str) -> list[dict]:
        eligible_symbols = self._eligible_symbols(symbols)
        if not eligible_symbols:
            return []

        snapshots = self.market_data.get_snapshots(eligible_symbols)
        generated = []
        for symbol in eligible_symbols:
            snapshot = snapshots.get(symbol)
            if snapshot is None:
                continue
            candidate = self._build_candidate(symbol, snapshot, source)
            if candidate is not None:
                generated.append(candidate)
        return generated

    def run(self, db: Session, limit: int = 5):
        symbols, source = self._get_universe()
        try:
            generated = self._screen_universe(symbols, source)
        except Exception as exc:
            if source != "alpaca_movers":
                raise
            print("[MarketScout] Mover screening unavailable:", exc)
            generated = []

        # If every mover fails deterministic quality checks, use the existing
        # liquid fallback universe rather than sending low-quality movers to LLMs.
        if source == "alpaca_movers" and not generated:
            source = "watchlist"
            generated = self._screen_universe(DEFAULT_UNIVERSE, source)

        generated.sort(key=lambda item: item["scout_score"], reverse=True)
        candidates = []
        for data in generated[:limit]:
            candidate = CandidateTrade(**data)
            db.add(candidate)
            candidates.append(candidate)

        db.commit()
        for candidate in candidates:
            db.refresh(candidate)
        return candidates


market_scout = MarketScout()
