import os

from dotenv import load_dotenv
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest


load_dotenv()

api_key = os.getenv("ALPACA_API_KEY")
secret_key = os.getenv("ALPACA_SECRET_KEY")

client = StockHistoricalDataClient(
    api_key,
    secret_key,
)

request = StockLatestQuoteRequest(
    symbol_or_symbols=["SPY", "AAPL", "NVDA"]
)

quotes = client.get_stock_latest_quote(request)

print("=" * 50)
print("REGRET — MARKET DATA TEST")
print("=" * 50)

for symbol, quote in quotes.items():
    print(symbol)
    print(f"Bid: {quote.bid_price}")
    print(f"Ask: {quote.ask_price}")
    print("-" * 30)

print("MARKET DATA CONNECTION: OK")