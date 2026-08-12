from dotenv import load_dotenv
load_dotenv()

import os
import requests
import pandas as pd
from datetime import datetime, timedelta
import time

API_KEY = os.environ.get('POLYGON_API_KEY')
# Only download remaining tickers
tickers = ['META', 'GOOGL', 'AMZN']

print(f"\n{'='*60}")
print(" Downloading Remaining from Polygon.io")
print(f"{'='*60}\n")

for i, ticker in enumerate(tickers):
    try:
        # Wait between requests to avoid rate limit
        if i > 0:
            print(f"Waiting 15 seconds...")
            time.sleep(15)
        
        end = datetime.now()
        start = end - timedelta(days=30)
        
        url = f'https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/minute/{start.strftime("%Y-%m-%d")}/{end.strftime("%Y-%m-%d")}'
        params = {
            'adjusted': 'true',
            'sort': 'asc',
            'limit': 50000,
            'apiKey': API_KEY
        }
        
        response = requests.get(url, params=params)
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
            df.to_csv(f'data/{ticker}_polygon.csv', index=False)
            print(f'{ticker}: Saved {len(df)} bars (includes premarket)')
        else:
            print(f'{ticker}: {data}')
    except Exception as e:
        print(f'{ticker}: Error - {e}')

print(f"\n{'='*60}\n")