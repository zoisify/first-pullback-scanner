import requests
from bs4 import BeautifulSoup
import csv
import os

print(f"\n{'='*60}")
print(" Finviz Direct Scraper - Gap Up Stocks")
print(f"{'='*60}\n")

# Finviz screener URL for gap up stocks
# gap_u10 = gap up 10%+
# vol_o500 = volume over 500K
# price_o5 = price over $5
url = "https://finviz.com/screener.ashx?v=111&f=gap_u10,price_o5,vol_o500&o=-gap"

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

print(f"Fetching: {url}\n")

try:
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Find the table
    table = soup.find('table', {'class': 'screener-table'})
    
    if not table:
        print("No table found - Finviz may be blocking requests")
        print("Try using a proxy or wait a few minutes")
        exit()
    
    # Extract tickers from rows
    tickers = []
    rows = table.find_all('tr')[1:]  # Skip header
    
    for row in rows:
        cells = row.find_all('td')
        if cells:
            # Ticker is in the second cell (index 1)
            ticker_cell = cells[1].find('a')
            if ticker_cell:
                ticker = ticker_cell.text.strip()
                if len(ticker) >= 2:  # Filter out single chars
                    tickers.append(ticker)
    
    print(f"Found {len(tickers)} gap-up stocks:\n")
    for i, ticker in enumerate(tickers[:30], 1):
        print(f"  {i:2}. {ticker}")
    
    if len(tickers) > 30:
        print(f"  ... and {len(tickers) - 30} more")
    
    # Save to watchlist
    watchlist_path = 'data/watchlist.csv'
    os.makedirs('data', exist_ok=True)
    
    with open(watchlist_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['TICKER'])
        for ticker in tickers:
            writer.writerow([ticker])
    
    print(f"\n✓ Saved {len(tickers)} tickers to {watchlist_path}")
    
except Exception as e:
    print(f"Error: {e}")
    print("\nFinviz may be rate-limiting. Try again later.")

print(f"\n{'='*60}\n")