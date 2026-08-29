import os
import time

from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce


load_dotenv()

api_key = os.getenv("ALPACA_API_KEY")
secret_key = os.getenv("ALPACA_SECRET_KEY")

if not api_key or not secret_key:
    raise RuntimeError("Missing Alpaca credentials.")

client = TradingClient(
    api_key,
    secret_key,
    paper=True,
)

print("=" * 60)
print("REGRET — PAPER ORDER SMOKE TEST")
print("THIS USES PAPER MONEY ONLY")
print("=" * 60)

order_request = MarketOrderRequest(
    symbol="BTC/USD",
    notional=15,
    side=OrderSide.BUY,
    time_in_force=TimeInForce.GTC,
)

order = client.submit_order(
    order_data=order_request
)

print("\nORDER SUBMITTED")
print(f"Order ID : {order.id}")
print(f"Symbol   : {order.symbol}")
print(f"Side     : {order.side}")
print(f"Status   : {order.status}")

print("\nWaiting for paper execution...")

for attempt in range(10):
    time.sleep(1)

    current = client.get_order_by_id(order.id)

    status = getattr(
        current.status,
        "value",
        str(current.status),
    )

    print(
        f"[{attempt + 1}/10] "
        f"status={status}, "
        f"filled_qty={current.filled_qty}, "
        f"avg_price={current.filled_avg_price}"
    )

    if status == "filled":
        print("\n" + "=" * 60)
        print("PAPER ORDER FILLED SUCCESSFULLY")
        print(f"Order ID : {current.id}")
        print(f"Quantity : {current.filled_qty}")
        print(f"Price    : ${current.filled_avg_price}")
        print("=" * 60)
        break

else:
    print("\nOrder was submitted but has not filled yet.")
    print("Check Alpaca Paper Trading dashboard.")