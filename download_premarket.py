from dotenv import load_dotenv
load_dotenv()

import os
import alpaca_trade_api as tradeapi
import pandas as pd
from datetime import datetime, timedelta

api = tradeapi.REST(
    key_id=os.environ['ALPACA_API_KEY'],
    secret_key=os.environ['ALPACA_SECRET_KEY'],
    base_url='https://paper-api.alpaca.markets'
)

tickers = ['NVDA', 'TSLA', 'AMD', 'AAPL', 'MSFT', 'META', 'GOOGL', 'AMZN']

# Get yesterday's date
yesterday = datetime.now() - timedelta(days=1)
start = yesterday.strftime('%Y-%m-%d')
end = yesterday.strftime('%Y-%m-%d')

print(f"\n{'='*60}")
print(f" Downloading Premarket Data ({start})")
print(f"{'='*60}\n")

for ticker in tickers:
    try:
        print(f"Downloading {ticker}...")
        bars = api.get_bars(
            ticker, 
            '1Min', 
            start=start, 
            end=end,
            adjustment='raw'
        ).df
        
        if not bars.empty:
            bars.to_csv(f'data/{ticker}_premarket.csv')
            print(f"  ✓ Saved {len(bars)} bars")
        else:
            print(f"  ✗ No data")
    except Exception as e:
        print(f"  ✗ Error: {e}")

print(f"\n{'='*60}\n")