from dotenv import load_dotenv
load_dotenv()

import os
import requests
import pandas as pd
from datetime import datetime, timedelta
import time

API_KEY = os.environ.get('POLYGON_API_KEY')

# Recent huge gainers
tickers = ['PLTR', 'TEAM', 'RCEL', 'QMCO', 'COHR', 'PAYC', 'SHOP']

data_dir = 'data/gappers'
os.makedirs(data_dir, exist_ok=True)

print(f"\n{'='*60}")
print(" Downloading Recent Big Gappers")
print(f"{'='*60}\n")

end = datetime.now()
start = end - timedelta(days=14)

for i, ticker in enumerate(tickers):
    try:
        # Wait between requests
        if i > 0:
            print(f"Waiting 15 seconds...")
            time.sleep(15)
        
        url = f'https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/minute/{start.strftime("%Y-%m-%d")}/{end.strftime("%Y-%m-%d")}'
        params = {
            'adjusted': 'true',
            'sort': 'asc',
            'limit': 50000,
            'apiKey': API_KEY
        }
        
        print(f"Downloading {ticker}...")
        response = requests.get(url, params=params, timeout=30)
        data = response.json()
        
        if 'results' in data:
            df = pd.DataFrame(data['results'])
            df = df.rename(columns={
                't': 'timestamp',
                'o': 'Open',
                'h': 'High',
                'l': 'Low',
                'c': 'Close',
                'v': 'Volume'
            })
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.to_csv(f'{data_dir}/{ticker}_gapper.csv', index=False)
            print(f"  ✓ {ticker}: Saved {len(df)} bars")
            
            # Check for gaps
            df['date'] = df['timestamp'].dt.date
            daily = df.groupby('date').agg({'Open': 'first', 'Close': 'last'}).reset_index()
            
            for j in range(1, len(daily)):
                prev_close = daily['Close'].iloc[j-1]
                curr_open = daily['Open'].iloc[j]
                gap = (curr_open - prev_close) / prev_close * 100
                
                if gap > 10:
                    print(f"    🚀 GAP on {daily['date'].iloc[j]}: {gap:+.1f}%")
        else:
            print(f"  ✗ {ticker}: {data}")
            
    except Exception as e:
        print(f"  ✗ {ticker}: Error - {e}")

print(f"\n{'='*60}")
print(f"Data saved to: {data_dir}/")
print(f"{'='*60}\n")