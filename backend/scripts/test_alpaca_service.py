from backend.app.services.alpaca_service import alpaca_service


account = alpaca_service.get_account()

print("=" * 60)
print("REGRET — BACKEND ALPACA SERVICE")
print("=" * 60)

print(f"Status : {account.status}")
print(f"Equity : ${account.equity}")
print(f"Cash   : ${account.cash}")

print("\nFetching snapshots...")

snapshots = alpaca_service.get_snapshots(
    ["AAPL", "NVDA", "MSFT"]
)

for symbol, snapshot in snapshots.items():
    print(symbol)

    if snapshot.latest_trade:
        print(
            "Latest price:",
            snapshot.latest_trade.price,
        )

print("=" * 60)
print("ALPACA SERVICE OK")