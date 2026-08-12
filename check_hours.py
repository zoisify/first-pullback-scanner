from pathlib import Path
import pandas as pd

data_dir = Path('data')

print(f"\n{'='*60}")
print(" Checking Trading Hours in Twelve Data")
print(f"{'='*60}\n")

for csv_file in sorted(data_dir.glob('*_twelvedata.csv')):
    ticker = csv_file.stem.replace('_twelvedata', '')
    bars = pd.read_csv(csv_file)[:20]
    
    bars['timestamp'] = pd.to_datetime(bars['timestamp'])
    
    print(f"\n{ticker} (first 20 bars):")
    print(bars[['timestamp', 'Open', 'Close', 'Volume']].head(10))

print(f"\n{'='*60}\n")