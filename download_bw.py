from dotenv import load_dotenv
load_dotenv()

import os
import requests
import pandas as pd
import time

API_KEY = os.environ.get('POLYGON_API_KEY')

print(f"\n{'='*60}")
print(" Downloading BW (34.5% Gap on Aug 11)")
print(f"{'='*60}\n")

ticker = 'BW'
start = '2026-08-08'
end = '2026-08-12'

url = f'https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/minute/{start}/{end}'
params = {
    'adjusted': 'true',
    'sort': 'asc',
    'limit': 50000,
    'apiKey': API_KEY
}

print(f"Downloading {ticker}...")
response = requests.get(url, params=params, timeout=30)
data = response.json()

if 'results' not in data:
    print(f"Error: {data}")
    exit()

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

# Save
df.to_csv('data/bw_34gap.csv', index=False)
print(f"✓ Saved {len(df)} bars")

# Check the gap
df['date'] = df['timestamp'].dt.date
daily = df.groupby('date').agg({'Open': 'first', 'Close': 'last'}).reset_index()

print(f"\n{'Date':<12} {'Open':<10} {'Prev Close':<12} {'Gap %':<10}")
print(f"{'-'*45}")

for i in range(1, len(daily)):
    curr_open = daily['Open'].iloc[i]
    prev_close = daily['Close'].iloc[i-1]
    gap = (curr_open - prev_close) / prev_close * 100
    
    date_str = str(daily['date'].iloc[i])
    print(f"{date_str:<12} ${curr_open:<9.2f} ${prev_close:<11.2f} {gap:>+9.1f}%")

print(f"\n{'='*60}\n")