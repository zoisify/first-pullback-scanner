import yfinance as yf
import pandas as pd

tickers = ['NVDA', 'TSLA', 'AMD', 'AAPL', 'MSFT', 'META', 'GOOGL', 'AMZN']

print(f"\n{'='*60}")
print(" Yahoo Finance - Checking for Gaps")
print(f"{'='*60}\n")

for ticker_sym in tickers:
    ticker = yf.Ticker(ticker_sym)
    data = ticker.history(period="5d", interval="1m")
    
    if len(data) < 10:
        print(f"{ticker_sym}: Not enough data ({len(data)} bars)")
        continue
    
    # Find overnight gaps
    gaps = []
    for i in range(1, len(data)):
        prev_close = data['Close'].iloc[i-1]
        curr_open = data['Open'].iloc[i]
        gap = (curr_open - prev_close) / prev_close * 100
        
        if abs(gap) > 1:  # 1%+ gap
            gaps.append({
                'time': data.index[i],
                'gap': gap,
                'price': curr_open
            })
    
    if gaps:
        biggest = max(gaps, key=lambda x: abs(x['gap']))
        print(f"{ticker_sym}: Biggest gap {biggest['gap']:+.2f}% @ ${biggest['price']:.2f} ({biggest['time']})")
    else:
        print(f"{ticker_sym}: No significant gaps (>1%)")

print(f"\n{'='*60}\n")