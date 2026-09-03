from types import SimpleNamespace

from backend.app.services.market_scout import DEFAULT_UNIVERSE, MarketScout


QUALITY_CONFIG = SimpleNamespace(
    market_scout_min_price=5.0,
    market_scout_min_previous_daily_volume=500_000,
    market_scout_max_daily_change_pct=25.0,
)


def _asset(
    symbol,
    *,
    name="Example Common Stock",
    tradable=True,
    fractionable=True,
    asset_class="us_equity",
    status="active",
    exchange="NASDAQ",
):
    return SimpleNamespace(
        symbol=symbol,
        name=name,
        tradable=tradable,
        fractionable=fractionable,
        asset_class=asset_class,
        status=status,
        exchange=exchange,
    )


def _snapshot(
    *,
    current_price=10.5,
    previous_close=10.0,
    current_volume=1_000_000,
    previous_volume=800_000,
):
    return SimpleNamespace(
        daily_bar=SimpleNamespace(close=current_price, volume=current_volume),
        previous_daily_bar=SimpleNamespace(
            close=previous_close,
            volume=previous_volume,
        ),
    )


class FakeMarketData:
    def __init__(self, symbols, assets, snapshots, *, movers_error=None):
        self.symbols = symbols
        self.assets = assets
        self.snapshots = snapshots
        self.movers_error = movers_error
        self.asset_calls = []
        self.snapshot_calls = []

    def get_market_movers(self, top=10):
        if self.movers_error is not None:
            raise self.movers_error
        return SimpleNamespace(
            gainers=[SimpleNamespace(symbol=symbol) for symbol in self.symbols]
        )

    def get_asset(self, symbol):
        self.asset_calls.append(symbol)
        if symbol not in self.assets:
            raise LookupError("asset unavailable")
        return self.assets[symbol]

    def get_snapshots(self, symbols):
        self.snapshot_calls.append(symbols)
        return {
            symbol: self.snapshots[symbol]
            for symbol in symbols
            if symbol in self.snapshots
        }


def test_market_scout_applies_deterministic_quality_filters(db_session):
    symbols = [
        "GOOD",
        "PENNY",
        "THIN",
        "SPIKE",
        "WARRANT",
        "NOFRAC",
        "NOTRAD",
        "OTC",
        "CRYPTO",
    ]
    assets = {symbol: _asset(symbol) for symbol in symbols}
    assets["WARRANT"] = _asset("WARRANT", name="Example Corp Warrant")
    assets["NOFRAC"] = _asset("NOFRAC", fractionable=False)
    assets["NOTRAD"] = _asset("NOTRAD", tradable=False)
    assets["OTC"] = _asset("OTC", exchange="OTC")
    assets["CRYPTO"] = _asset("CRYPTO", asset_class="crypto")
    snapshots = {symbol: _snapshot() for symbol in symbols}
    snapshots["PENNY"] = _snapshot(current_price=4.5, previous_close=4.25)
    snapshots["THIN"] = _snapshot(previous_volume=100_000)
    snapshots["SPIKE"] = _snapshot(current_price=13.0, previous_close=10.0)
    market_data = FakeMarketData(symbols, assets, snapshots)

    candidates = MarketScout(market_data, QUALITY_CONFIG).run(db_session, limit=5)

    assert [candidate.symbol for candidate in candidates] == ["GOOD"]
    assert candidates[0].source == "alpaca_movers"
    assert candidates[0].price_change_pct == 5.0
    assert "WARRANT" not in market_data.snapshot_calls[0]
    assert "NOFRAC" not in market_data.snapshot_calls[0]
    assert "NOTRAD" not in market_data.snapshot_calls[0]
    assert "OTC" not in market_data.snapshot_calls[0]
    assert "CRYPTO" not in market_data.snapshot_calls[0]


def test_non_standard_asset_names_are_filtered_when_identifiable():
    for name in (
        "Example Corp Warrants",
        "Example Acquisition Units",
        "Example Subscription Rights",
    ):
        assert MarketScout._asset_is_eligible(
            "TEST",
            _asset("TEST", name=name),
        ) is False


def test_existing_liquid_watchlist_is_used_when_movers_fail_quality_gate(
    db_session,
):
    assets = {
        "BADW": _asset("BADW", name="Bad Acquisition Warrant"),
        "AAPL": _asset("AAPL", name="Apple Inc. Common Stock"),
    }
    snapshots = {"AAPL": _snapshot(current_price=205.0, previous_close=200.0)}
    market_data = FakeMarketData(["BADW"], assets, snapshots)

    candidates = MarketScout(market_data, QUALITY_CONFIG).run(db_session, limit=1)

    assert [candidate.symbol for candidate in candidates] == ["AAPL"]
    assert candidates[0].source == "watchlist"
    assert set(DEFAULT_UNIVERSE).issubset(set(market_data.asset_calls))


def test_existing_liquid_watchlist_is_preserved_when_movers_api_fails(db_session):
    market_data = FakeMarketData(
        [],
        {"SPY": _asset("SPY", name="SPDR S&P 500 ETF Trust", exchange="ARCA")},
        {"SPY": _snapshot(current_price=510.0, previous_close=500.0)},
        movers_error=ConnectionError("screener unavailable"),
    )

    candidates = MarketScout(market_data, QUALITY_CONFIG).run(db_session, limit=1)

    assert [candidate.symbol for candidate in candidates] == ["SPY"]
    assert candidates[0].source == "watchlist"
