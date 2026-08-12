import requests
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

# Get free API key at: https://hfdatalibrary.com/pages/api
API_KEY = ''  # Leave empty for now, will use direct download

base_url = 'https://api.hfdatalibrary.com/v1'
tickers = ['NVDA', 'TSLA', 'AMD', 'AAPL', 'MSFT', 'META', 'GOOGL', 'AMZN']

data_dir = Path('data/hfdata')
data_dir.mkdir(exist_ok=True)

print(f"\n{'='*60}")
print(" Downloading from HF Data Library")
print(f"{'='*60}\n")
print("Get free API key: https://hfdatalibrary.com/pages/api")
print("(Free, 300 req/min, expires every 30 days)\n")

if not API_KEY:
    print("No API key provided. Using direct download method...")
    print("\nManual download: https://hfdatalibrary.com/pages/download")
    print("Select tickers, choose date range, download as CSV/Parquet\n")
    
    # Try without key (may work for some endpoints)
    for ticker in tickers:
        try:
            url = f'{base_url}/bars/{ticker}'
            params = {
                'start': '2026-07-01',
                'end': '2026-08-12',
                'format': 'json'
            }
            headers = {'X-API-Key': API_KEY} if API_KEY else {}
            
            print(f"Downloading {ticker}...")
            response = requests.get(url, params=params, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                if 'bars' in data and len(data['bars']) > 0:
                    df = pd.DataFrame(data['bars'])
                    df.to_csv(data_dir / f'{ticker}_hfdata.csv', index=False)
                    print(f"  ✓ {ticker}: Saved {len(df)} bars")
                else:
                    print(f"  ✗ {ticker}: No bars in response")
            else:
                print(f"  ✗ {ticker}: HTTP {response.status_code} - {response.text[:100]}")
        except Exception as e:
            print(f"  ✗ {ticker}: Error - {e}")
else:
    print(f"Using API key: {API_KEY[:8]}...")

print(f"\n{'='*60}\n")