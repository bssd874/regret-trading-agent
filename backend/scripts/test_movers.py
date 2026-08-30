from backend.app.services.alpaca_service import alpaca_service


print("=" * 60)
print("REGRET — MARKET MOVERS")
print("=" * 60)

movers = alpaca_service.get_market_movers(top=5)

print("\nGAINERS")

for mover in movers.gainers:
    print(
        mover.symbol,
        f"{mover.percent_change:+.2f}%",
        f"${mover.price}",
    )

print("\nLOSERS")

for mover in movers.losers:
    print(
        mover.symbol,
        f"{mover.percent_change:+.2f}%",
        f"${mover.price}",
    )