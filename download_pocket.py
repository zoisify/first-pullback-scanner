import requests
import pandas as pd
from pathlib import Path

# No API key needed!
base_url = 'https://www.pocketportfolio.app/api/tickers'
tickers = ['NVDA', 'TSLA', 'AMD', 'AAPL', 'MSFT', 'META', 'GOOGL', 'AMZN']

data_dir = Path('data/pocket')
data_dir.mkdir(exist_ok=True)

print(f"\n{'='*60}")
print(" Downloading from Pocket Portfolio (Free, No API Key)")
print(f"{'='*60}\n")

for ticker in tickers:
    try:
        url = f'{base_url}/{ticker}/csv?range=1mo'
        print(f"Downloading {ticker}...")
        
        response = requests.get(url, timeout=30)
        
        if response.status_code == 200:
            # Save raw CSV
            csv_path = data_dir / f'{ticker}_pocket.csv'
            with open(csv_path, 'wb') as f:
                f.write(response.content)
            
            # Read and show info
            df = pd.read_csv(csv_path)
            print(f"  ✓ {ticker}: Saved {len(df)} rows")
            print(f"    Columns: {list(df.columns)}")
        else:
            print(f"  ✗ {ticker}: HTTP {response.status_code}")
    except Exception as e:
        print(f"  ✗ {ticker}: Error - {e}")

print(f"\n{'='*60}\n")