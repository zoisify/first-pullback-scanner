from pathlib import Path
import pandas as pd

data_dir = Path('data')

for csv_file in data_dir.glob('*_historical.csv'):
    ticker = csv_file.stem.replace('_historical', '')
    bars = pd.read_csv(csv_file, index_col=0, parse_dates=True)[:10]
    
    print(f"\n{ticker} (first 10 bars):")
    print(bars[['open', 'high', 'low', 'close', 'volume']].head())
    
    # Check gap
    if len(bars) > 1:
        prev_close = bars.iloc[0]['close']
        first_open = bars.iloc[1]['open']
        gap = (first_open - prev_close) / prev_close * 100
        print(f"Gap from bar 0→1: {gap:+.2f}%")