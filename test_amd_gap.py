from dotenv import load_dotenv
load_dotenv()

import os
import requests
import pandas as pd
from scanner.signals import detect_entry, detect_exit

API_KEY = os.environ.get('POLYGON_API_KEY')

print(f"\n{'='*60}")
print(" Testing AMD Gap Day (July 21, 2026 - +3.2% Gap)")
print(f"{'='*60}\n")

# Get AMD data for July 21
ticker = 'AMD'
start = '2026-07-21'
end = '2026-07-22'

url = f'https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/minute/{start}/{end}'
params = {
    'adjusted': 'true',
    'sort': 'asc',
    'limit': 50000,
    'apiKey': API_KEY
}

response = requests.get(url, params=params)
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
df['timestamp'] = df['timestamp'].dt.tz_localize('America/New_York')

print(f"Got {len(df)} bars")
print(f"\nFirst 10 bars:")
print(df[['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume']].head(10))

# Check the gap
prev_day_url = f'https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/minute/2026-07-18/2026-07-20'
prev_response = requests.get(prev_day_url, params=params)
prev_data = prev_response.json()

if 'results' in prev_data:
    prev_df = pd.DataFrame(prev_data['results'])
    prev_close = prev_df['c'].iloc[-1]
    first_open = df['Open'].iloc[0]
    gap = (first_open - prev_close) / prev_close * 100
    print(f"\n{'='*60}")
    print(f"OVERNIGHT GAP: {gap:+.2f}%")
    print(f"  Previous close (Jul 18): ${prev_close:.2f}")
    print(f"  Open (Jul 21): ${first_open:.2f}")
    print(f"{'='*60}\n")

# Now test your scanner logic
print("Testing scanner logic...\n")

df = df.set_index('timestamp')
df.columns = [c.capitalize() for c in df.columns]

position = None
bars_list = []

for timestamp, row in df.iterrows():
    # Only 9:30-10am
    if timestamp.hour == 9 and timestamp.minute >= 30:
        pass
    elif timestamp.hour >= 10:
        if position:
            exit_price = row['Close']
            pnl = (exit_price - position['entry_price']) * position['qty']
            print(f"10am EXIT: ${pnl:+.2f}")
        break
    else:
        continue
    
    bars_list.append(row)
    if len(bars_list) > 60:
        bars_list.pop(0)
    
    window_df = pd.DataFrame(bars_list)
    
    if position:
        exit_sig = detect_exit(window_df, position['entry_price'], position['stop'], ticker)
        if exit_sig:
            exit_price = row['Close']
            pnl = (exit_price - position['entry_price']) * position['qty']
            print(f"EXIT @ ${exit_price:.2f}: ${pnl:+.2f} ({exit_sig.reason})")
            position = None
        continue
    
    candidate = {
        'ticker': ticker,
        'bars': window_df,
        'pillars': {},
        'score': 5,
        'gap_pct': 15,  # Your threshold
        'rel_vol': 10,
        'total_vol': int(window_df['Volume'].sum())
    }
    
    entry_sig = detect_entry(candidate)
    if entry_sig:
        qty = 33
        position = {
            'entry_price': entry_sig.price,
            'stop': entry_sig.stop,
            'qty': qty
        }
        print(f"ENTRY @ ${entry_sig.price:.2f} (stop: ${entry_sig.stop:.2f})")

if position:
    print(f"Still in position at 10am")

print(f"\n{'='*60}\n")