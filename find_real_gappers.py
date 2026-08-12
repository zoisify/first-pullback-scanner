from dotenv import load_dotenv
load_dotenv()

import os
import requests
import pandas as pd
from datetime import datetime, timedelta

API_KEY = os.environ.get('POLYGON_API_KEY')

print(f"\n{'='*60}")
print(" Finding Real Stocks with Large Gaps (Last 5 Days)")
print(f"{'='*60}\n")

# Get all tickers with gaps > 10%
end = datetime.now()
start = end - timedelta(days=5)

# Search for gappers
url = f'https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/gainers'
params = {'apiKey': API_KEY}

response = requests.get(url, params=params)
data = response.json()

if 'tickers' in data:
    gappers = []
    for ticker in data['tickers'][:50]:  # Top 50 gainers
        if 'today' in ticker and 'changePercent' in ticker['today']:
            gap = ticker['today']['changePercent']
            if gap > 10:  # 10%+ gainers
                gappers.append({
                    'ticker': ticker['ticker'],
                    'gap': gap,
                    'price': ticker.get('lastPrice', 0)
                })
    
    gappers.sort(key=lambda x: x['gap'], reverse=True)
    
    print(f"{'Ticker':<10} {'Gap %':<10} {'Price':<10}")
    print(f"{'-'*35}")
    for g in gappers[:20]:  # Show top 20
        print(f"{g['ticker']:<10} {g['gap']:>+9.1f}%  ${g['price']:.2f}")
else:
    print(f"Error: {data}")

print(f"\n{'='*60}\n")