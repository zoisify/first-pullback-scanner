from pathlib import Path
import pandas as pd

data_dir = Path('data/real_gappers')

print(f"\n{'='*60}")
print(" Checking Real Gap-Up Stocks for 10%+ Overnight Gaps")
print(f"{'='*60}\n")

found_gaps = []

for csv_file in sorted(data_dir.glob('*_realgap.csv')):
    ticker = csv_file.stem.replace('_realgap', '')
    bars = pd.read_csv(csv_file)
    
    if len(bars) < 100:
        continue
    
    bars['timestamp'] = pd.to_datetime(bars['timestamp'])
    bars['date'] = bars['timestamp'].dt.date
    
    daily = bars.groupby('date').agg({
        'Open': 'first',
        'Close': 'last'
    }).reset_index()
    
    gaps = []
    for i in range(1, len(daily)):
        prev_close = daily['Close'].iloc[i-1]
        curr_open = daily['Open'].iloc[i]
        gap = (curr_open - prev_close) / prev_close * 100
        
        if gap > 10:  # 10%+ overnight gap
            gaps.append({
                'date': str(daily['date'].iloc[i]),
                'gap': gap,
                'open': curr_open,
                'prev_close': prev_close
            })
    
    if gaps:
        print(f"\n{ticker}: Found {len(gaps)} gaps >10%")
        for g in sorted(gaps, key=lambda x: x['gap'], reverse=True)[:3]:
            print(f"  {g['date']}: {g['gap']:+.1f}% (open: ${g['open']:.2f}, prev: ${g['prev_close']:.2f})")
            found_gaps.append({
                'ticker': ticker,
                'date': g['date'],
                'gap': g['gap'],
                'open': g['open']
            })
    else:
        print(f"{ticker}: No gaps >10%")

print(f"\n{'='*60}")
if found_gaps:
    print(f"Found {len(found_gaps)} total 10%+ gaps!")
    print("\nTop gaps:")
    for g in sorted(found_gaps, key=lambda x: x['gap'], reverse=True)[:10]:
        print(f"  {g['ticker']} on {g['date']}: {g['gap']:+.1f}%")
print(f"{'='*60}\n")