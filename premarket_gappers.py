import requests
import csv
import os

print(f"\n{'='*60}")
print(" Pre-Market Gappers Scanner")
print(f"{'='*60}\n")

# Use a free API - Alpha Vantage (free, no rate limit issues)
# Or scrape from reliable sources

# Alternative: Use Barchart's premarket gappers
url = "https://www.barchart.com/json/premarket_gainers"

headers = {
    'User-Agent': 'Mozilla/5.0',
    'Accept': 'application/json'
}

print(f"Fetching premarket gappers...\n")

try:
    response = requests.get(url, headers=headers, timeout=10)
    data = response.json()
    
    tickers = []
    
    # Parse the JSON response
    if 'results' in data:
        for stock in data['results'][:50]:  # Top 50
            ticker = stock.get('symbol', '')
            gap_pct = stock.get('percentChange', 0)
            
            if gap_pct >= 5:  # 5%+ gap
                tickers.append(ticker)
                print(f"  {ticker}: +{gap_pct:.2f}%")
    
    print(f"\nFound {len(tickers)} stocks gapping 5%+\n")
    
    # Save to watchlist
    watchlist_path = 'data/watchlist.csv'
    os.makedirs('data', exist_ok=True)
    
    with open(watchlist_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['TICKER'])
        for ticker in tickers:
            writer.writerow([ticker])
    
    print(f"✓ Saved {len(tickers)} tickers to {watchlist_path}")
    
except Exception as e:
    print(f"Error: {e}")
    print("\nTrying alternative method...")
    
    # Fallback: Manual list of volatile stocks
    fallback = [
        'TSLA', 'NVDA', 'AMD', 'COIN', 'PLTR', 'SOFI', 'RIVN', 'LCID',
        'NIO', 'BABA', 'MARA', 'RIOT', 'CLSK', 'HIVE', 'BITF', 'IREN'
    ]
    
    print(f"\nUsing fallback list of {len(fallback)} volatile stocks")
    
    watchlist_path = 'data/watchlist.csv'
    with open(watchlist_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['TICKER'])
        for ticker in fallback:
            writer.writerow([ticker])
    
    print(f"✓ Saved {len(fallback)} tickers to {watchlist_path}")

print(f"\n{'='*60}\n")