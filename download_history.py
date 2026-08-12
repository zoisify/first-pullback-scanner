from dotenv import load_dotenv
load_dotenv()

import os
import alpaca_trade_api as tradeapi
import pandas as pd
from datetime import datetime

api = tradeapi.REST(
    key_id=os.environ['ALPACA_API_KEY'],
    secret_key=os.environ['ALPACA_SECRET_KEY'],
    base_url='https://paper-api.alpaca.markets'
)

# Stocks to download
tickers = ['NVDA', 'TSLA', 'AMD', 'AAPL', 'MSFT', 'META', 'GOOGL', 'AMZN']

print(f"\n{'='*60}")
print(" Downloading Historical Data from Alpaca")
print(f"{'='*60}\n")

for ticker in tickers:
    try:
        print(f"Downloading {ticker}...")
        bars = api.get_bars(ticker, '1Min', limit=5000, adjustment='raw').df
        
        if not bars.empty:
            bars.to_csv(f'data/{ticker}_historical.csv')
            print(f"  ✓ Saved {len(bars)} bars to data/{ticker}_historical.csv")
        else:
            print(f"  ✗ No data for {ticker}")
    except Exception as e:
        print(f"  ✗ Error: {e}")

print(f"\n{'='*60}")
print("Done!")
print(f"{'='*60}\n")