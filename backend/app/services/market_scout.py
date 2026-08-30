from sqlalchemy.orm import Session

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


class MarketScout:

    def _get_universe(self) -> tuple[list[str], str]:

        try:
            movers = alpaca_service.get_market_movers(
                top=10
            )

            symbols = [
                mover.symbol
                for mover in movers.gainers
            ]

            if symbols:
                return symbols[:10], "alpaca_movers"

        except Exception as exc:
            print(
                "[MarketScout] Movers unavailable:",
                exc,
            )

        return DEFAULT_UNIVERSE, "watchlist"

    def _build_candidate(
        self,
        symbol: str,
        snapshot,
        source: str,
    ):

        daily = snapshot.daily_bar
        previous = snapshot.previous_daily_bar

        if not daily or not previous:
            return None

        current_price = float(daily.close)
        previous_close = float(previous.close)

        if previous_close <= 0:
            return None

        change_pct = (
            (current_price - previous_close)
            / previous_close
        ) * 100

        current_volume = float(
            daily.volume or 0
        )

        previous_volume = float(
            previous.volume or 0
        )

        volume_ratio = (
            current_volume / previous_volume
            if previous_volume > 0
            else 1.0
        )

        #
        # MVP deterministic scout score.
        #
        scout_score = (
            max(change_pct, 0)
            + min(volume_ratio, 3.0)
        )

        #
        # Day 30 only:
        # generate LONG candidates.
        #
        if change_pct <= 0:
            return None

        return {
            "symbol": symbol,
            "side": "BUY",
            "strategy": "momentum",

            "entry_price": current_price,

            "price_change_pct": round(
                change_pct,
                4,
            ),

            "volume_ratio": round(
                volume_ratio,
                4,
            ),

            "scout_score": round(
                scout_score,
                4,
            ),

            "source": source,
        }

    def run(
        self,
        db: Session,
        limit: int = 5,
    ):

        symbols, source = self._get_universe()

        snapshots = alpaca_service.get_snapshots(
            symbols
        )

        generated = []

        for symbol in symbols:

            snapshot = snapshots.get(symbol)

            if snapshot is None:
                continue

            candidate_data = self._build_candidate(
                symbol,
                snapshot,
                source,
            )

            if candidate_data is None:
                continue

            generated.append(candidate_data)

        generated.sort(
            key=lambda item: item["scout_score"],
            reverse=True,
        )

        generated = generated[:limit]

        candidates = []

        for data in generated:

            candidate = CandidateTrade(
                **data
            )

            db.add(candidate)
            candidates.append(candidate)

        db.commit()

        for candidate in candidates:
            db.refresh(candidate)

        return candidates


market_scout = MarketScout()