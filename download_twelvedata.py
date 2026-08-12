from dotenv import load_dotenv
load_dotenv()

import os
import requests
import pandas as pd

API_KEY = os.environ.get('TWELVEDATA_API_KEY', 'demo')
tickers = ['NVDA', 'TSLA', 'AMD', 'AAPL', 'MSFT', 'META', 'GOOGL', 'AMZN']

print(f"\n{'='*60}")
print(" Downloading from Twelve Data (Free)")
print(f"{'='*60}\n")

for ticker in tickers:
    try:
        url = f'https://api.twelvedata.com/time_series'
        params = {
            'symbol': ticker,
            'interval': '1min',
            'outputsize': 5000,
            'apikey': API_KEY,
            'format': 'JSON'
        }
        
        response = requests.get(url, params=params)
        data = response.json()
        
        if 'values' in data:
            df = pd.DataFrame(data['values'])
            df = df.rename(columns={
                'datetime': 'timestamp',
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume'
            })
            df.to_csv(f'data/{ticker}_twelvedata.csv', index=False)
            print(f'{ticker}: Saved {len(df)} bars')
        else:
            print(f'{ticker}: {data.get("message", "No data")}')
    except Exception as e:
        print(f'{ticker}: Error - {e}')

print(f"\n{'='*60}\n")