from finviz.screener import Screener
import csv
import os

print(f"\n{'='*60}")
print(" Auto-Generating Watchlist - Gap Up Stocks (v2)")
print(f"{'='*60}\n")

# Simpler filters - more reliable
filters = [
    'exch_nyse',     # NYSE stocks only (more reliable)
    'price_o5',      # Price over $5
    'vol_o500',      # Volume over 500K
    'gap_u10',       # Gap up 10%+ (lower threshold)
]

print(f"Filters:")
print(f"  - NYSE stocks")
print(f"  - Price over $5")
print(f"  - Volume over 500K")
print(f"  - Gap up 10%+")
print(f"\nScanning...\n")

try:
    # Get screener results
    stocks = Screener(filters=filters, table="Performance", order="-gap")
    
    # Show first stock to debug
    if stocks:
        print(f"Sample stock data: {stocks[0]}")
        print()
    
    # Extract tickers - filter out single chars
    tickers = [stock['Ticker'] for stock in stocks if len(stock['Ticker']) >= 2]
    
    print(f"Found {len(tickers)} valid gap-up stocks:\n")
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
    import traceback
    traceback.print_exc()

print(f"\n{'='*60}\n")