"""
test_order.py
Quick test — buys 1 share of AAPL, waits 5 seconds, sells it.
Run with: python test_order.py
"""
from dotenv import load_dotenv
load_dotenv()

from scanner.executor import get_trading_client
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
import time

TICKER = "AAPL"

client = get_trading_client()

# Buy 1 share
print(f"Buying 1 share of {TICKER}...")
buy = client.submit_order(MarketOrderRequest(
    symbol=TICKER,
    qty=1,
    side=OrderSide.BUY,
    time_in_force=TimeInForce.DAY,
))
print(f"BUY order submitted: {buy.id}")

print("Waiting 30 seconds...")
time.sleep(30)

# Sell 1 share
print(f"Selling 1 share of {TICKER}...")
sell = client.submit_order(MarketOrderRequest(
    symbol=TICKER,
    qty=1,
    side=OrderSide.SELL,
    time_in_force=TimeInForce.DAY,
))
print(f"SELL order submitted: {sell.id}")

print("Done. Check your Alpaca paper account for the orders.")
