import os

from dotenv import load_dotenv
from alpaca.trading.client import TradingClient


load_dotenv()

api_key = os.getenv("ALPACA_API_KEY")
secret_key = os.getenv("ALPACA_SECRET_KEY")

if not api_key or not secret_key:
    raise RuntimeError("Missing Alpaca credentials in .env")

client = TradingClient(
    api_key,
    secret_key,
    paper=True,
)

account = client.get_account()

print("=" * 50)
print("REGRET — ALPACA CONNECTION TEST")
print("=" * 50)
print(f"Account ID     : {account.id}")
print(f"Status         : {account.status}")
print(f"Equity         : ${account.equity}")
print(f"Cash           : ${account.cash}")
print(f"Buying Power   : ${account.buying_power}")
print(f"Trading Blocked: {account.trading_blocked}")
print("=" * 50)
print("ALPACA PAPER CONNECTION: OK")