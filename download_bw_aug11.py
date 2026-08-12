from dotenv import load_dotenv
load_dotenv()

import os
import requests
import pandas as pd
import time

API_KEY = os.environ.get('POLYGON_API_KEY')

print(f"\n{'='*60}")
print(" Downloading BW - Aug 11 (Gap Day)")
print(f"{'='*60}\n")

ticker = 'BW'

# Get Aug 11 specifically
url = f'https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/minute/2026-08-11/2026-08-12'
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
df.to_csv('data/bw_gapday.csv', index=False)
print(f"✓ Saved {len(df)} bars")

# Show first/last bars
print(f"\nFirst 20 bars:")
print(df[['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume']].head(20))

print(f"\nLast 10 bars:")
print(df[['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume']].tail(10))

# Check gap from Aug 10 close
print(f"\n{'='*60}")
print(" Checking Gap from Aug 10 Close")
print(f"{'='*60}\n")

# Get Aug 10 last bar
url_prev = f'https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/minute/2026-08-08/2026-08-10'
params_prev = {
    'adjusted': 'true',
    'sort': 'asc',
    'limit': 50000,
    'apiKey': API_KEY
}

print("Waiting 15 seconds...")
time.sleep(15)

print("Getting Aug 10 data...")
prev_response = requests.get(url_prev, params=params_prev, timeout=30)
prev_data = prev_response.json()

if 'results' in prev_data:
    prev_df = pd.DataFrame(prev_data['results'])
    prev_close = prev_df['c'].iloc[-1]
    first_open = df['Open'].iloc[0]
    gap = (first_open - prev_close) / prev_close * 100
    
    print(f"\nAug 10 Close: ${prev_close:.2f}")
    print(f"Aug 11 Open:  ${first_open:.2f}")
    print(f"GAP: {gap:+.1f}%")
else:
    print(f"Could not get Aug 10 data: {prev_data}")

print(f"\n{'='*60}\n")