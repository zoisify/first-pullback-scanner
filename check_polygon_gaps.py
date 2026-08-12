from pathlib import Path
import pandas as pd

data_dir = Path('data')

print(f"\n{'='*60}")
print(" Checking Polygon Data for Premarket Gaps")
print(f"{'='*60}\n")

for csv_file in sorted(data_dir.glob('*_polygon.csv')):
    ticker = csv_file.stem.replace('_polygon', '')
    bars = pd.read_csv(csv_file)
    
    if len(bars) < 100:
        continue
    
    bars['timestamp'] = pd.to_datetime(bars['timestamp'])
    
    # Find gaps > 5%
    gaps = []
    for i in range(1, min(500, len(bars))):
        prev_close = bars['Close'].iloc[i-1]
        curr_open = bars['Open'].iloc[i]
        gap = (curr_open - prev_close) / prev_close * 100
        
        if abs(gap) > 5:
            gaps.append({
                'idx': i,
                'time': bars['timestamp'].iloc[i],
                'gap': gap,
                'open': curr_open,
                'prev_close': prev_close
            })
    
    if gaps:
        biggest = max(gaps, key=lambda x: abs(x['gap']))
        print(f"{ticker}: Found {len(gaps)} gaps >5%")
        print(f"  Biggest: {biggest['gap']:+.2f}% @ ${biggest['open']:.2f} ({biggest['time']})")
    else:
        print(f"{ticker}: No gaps >5% in first 500 bars")

print(f"\n{'='*60}\n")