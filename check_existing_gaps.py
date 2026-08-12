from pathlib import Path
import pandas as pd

# Check the Polygon data we already downloaded
data_dir = Path('data')

print(f"\n{'='*60}")
print(" Checking Existing Polygon Data for Gaps")
print(f"{'='*60}\n")

for csv_file in sorted(data_dir.glob('*_polygon.csv')):
    ticker = csv_file.stem.replace('_polygon', '')
    bars = pd.read_csv(csv_file)
    
    if len(bars) < 200:
        continue
    
    bars['timestamp'] = pd.to_datetime(bars['timestamp'])
    bars['date'] = bars['timestamp'].dt.date
    
    # Group by day
    daily = bars.groupby('date').agg({
        'Open': 'first',
        'Close': 'last',
        'High': 'max',
        'Low': 'min'
    }).reset_index()
    
    # Find overnight gaps
    gaps = []
    for i in range(1, len(daily)):
        prev_close = daily['Close'].iloc[i-1]
        curr_open = daily['Open'].iloc[i]
        gap = (curr_open - prev_close) / prev_close * 100
        
        if abs(gap) > 3:  # 3%+ gap
            gaps.append({
                'date': daily['date'].iloc[i],
                'gap': gap,
                'open': curr_open,
                'prev_close': prev_close
            })
    
    if gaps:
        print(f"\n{ticker}: Found {len(gaps)} gaps >3%")
        for g in sorted(gaps, key=lambda x: abs(x['gap']), reverse=True)[:3]:
            print(f"  {g['date']}: {g['gap']:+.1f}% (open: ${g['open']:.2f}, prev close: ${g['prev_close']:.2f})")
    else:
        print(f"{ticker}: No gaps >3%")

print(f"\n{'='*60}\n")