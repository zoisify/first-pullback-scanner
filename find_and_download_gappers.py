from dotenv import load_dotenv
load_dotenv()

import os
import requests
import pandas as pd
from datetime import datetime, timedelta
import time

API_KEY = os.environ.get('POLYGON_API_KEY')

print(f"\n{'='*60}")
print(" Finding & Downloading Recent Gap-Up Stocks")
print(f"{'='*60}\n")

# Get recent gappers from news/snapshot
end = datetime.now()
start = end - timedelta(days=5)

# Try to get gainers
tickers_to_check = []

# Method 1: Use known recent gappers (from news, Reddit, etc.)
# Add tickers you've seen gap recently here:
known_gappers = [
    # Add your tickers here, e.g.:
    # 'SMCI', 'IONQ', 'RIVN', 'PLTR', etc.
]

if known_gappers:
    tickers_to_check = known_gappers
    print(f"Using {len(known_gappers)} known gappers\n")
else:
    # Method 2: Check popular volatile stocks
    print("No known gappers provided. Checking volatile stocks...\n")
    tickers_to_check = [
        'SMCI', 'IONQ', 'RIVN', 'PLTR', 'SOFI', 'LCID', 'NIO', 'RBLX',
        'COIN', 'MARA', 'RIOT', 'CLSK', 'HIMS', 'BBAI', 'BULL', 'BITX',
        'TSLA', 'NVDA', 'AMD', 'AAPL', 'META', 'GOOGL', 'AMZN', 'MSFT'
    ]

# Download data for each and check for gaps
data_dir = 'data/gappers'
import os
os.makedirs(data_dir, exist_ok=True)

print(f"{'Ticker':<10} {'Date':<12} {'Gap %':<10} {'Bars':<10}")
print(f"{'-'*45}")

for ticker in tickers_to_check:
    try:
        # Get last 5 days of 1-min data
        url = f'https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/minute/{start.strftime("%Y-%m-%d")}/{end.strftime("%Y-%m-%d")}'
        params = {
            'adjusted': 'true',
            'sort': 'asc',
            'limit': 50000,
            'apiKey': API_KEY
        }
        
        response = requests.get(url, params=params)
        data = response.json()
        
        if 'results' not in data:
            continue
        
        df = pd.DataFrame(data['results'])
        if len(df) < 100:
            continue
        
        df = df.rename(columns={
            't': 'timestamp',
            'o': 'Open',
            'h': 'High',
            'l': 'Low',
            'c': 'Close',
            'v': 'Volume'
        })
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        # Find gaps between days (overnight gaps)
        df['date'] = df['timestamp'].dt.date
        daily = df.groupby('date').agg({
            'Open': 'first',
            'Close': 'last'
        }).reset_index()
        
        # Calculate overnight gaps
        gaps = []
        for i in range(1, len(daily)):
            prev_close = daily['Close'].iloc[i-1]
            curr_open = daily['Open'].iloc[i]
            gap = (curr_open - prev_close) / prev_close * 100
            
            if gap > 5:  # 5%+ gap up
                gaps.append({
                    'date': daily['date'].iloc[i],
                    'gap': gap,
                    'open': curr_open,
                    'prev_close': prev_close
                })
        
        if gaps:
            biggest = max(gaps, key=lambda x: x['gap'])
            print(f"{ticker:<10} {str(biggest['date']):<12} {biggest['gap']:>+9.1f}%  {len(df):<10}")
            
            # Save the data
            df.to_csv(f'{data_dir}/{ticker}_gap.csv', index=False)
        else:
            print(f"{ticker:<10} {'No gap >5%':<12} {'-':<10} {len(df):<10}")
        
        time.sleep(1)  # Avoid rate limit
        
    except Exception as e:
        print(f"{ticker:<10} Error: {e}")

print(f"\n{'='*60}")
print(f"Data saved to: {data_dir}/")
print(f"{'='*60}\n")