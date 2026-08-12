from pathlib import Path
import pandas as pd

data_dir = Path('data')

print(f"\n{'='*60}")
print(" Checking Polygon Data - Times and Gaps")
print(f"{'='*60}\n")

for csv_file in sorted(data_dir.glob('*_polygon.csv')):
    ticker = csv_file.stem.replace('_polygon', '')
    bars = pd.read_csv(csv_file)[:50]
    
    bars['timestamp'] = pd.to_datetime(bars['timestamp'])
    
    print(f"\n{ticker} (first 50 bars):")
    print(f"Time range: {bars['timestamp'].min()} to {bars['timestamp'].max()}")
    print(bars[['timestamp', 'Open', 'Close', 'Volume']].head(20))
    
    # Check for any gaps > 1%
    gaps = []
    for i in range(1, len(bars)):
        prev_close = bars['Close'].iloc[i-1]
        curr_open = bars['Open'].iloc[i]
        gap = (curr_open - prev_close) / prev_close * 100
        
        if abs(gap) > 1:
            gaps.append({'time': bars['timestamp'].iloc[i], 'gap': gap})
    
    if gaps:
        print(f"  Found {len(gaps)} gaps >1%")
    else:
        print(f"  No gaps >1%")

print(f"\n{'='*60}\n")