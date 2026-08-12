from dotenv import load_dotenv
load_dotenv()

import yfinance as yf
import pandas as pd
from datetime import datetime

# Top gappers to scan (add more as needed)
TICKERS = ["NVDA", "TSLA", "AMD", "AAPL", "MSFT", "GOOGL", "META", "AMZN", "NFLX", "COIN"]

print(f"\n{'='*55}")
print(f" Simple Scan - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print(f"{'='*55}\n")

for ticker in TICKERS:
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1d", interval="1m")
        
        if hist.empty:
            continue
        
        open_price = hist.iloc[0]["Open"]
        prev_close = stock.info.get("previousClose", open_price)
        gap_pct = (open_price - prev_close) / prev_close * 100
        
        if gap_pct >= 5:
            print(f"✓ {ticker}: Gap up {gap_pct:.1f}% @ ${open_price:.2f}")
    except Exception as e:
        print(f"✗ {ticker}: {e}")

print("\nDone.")