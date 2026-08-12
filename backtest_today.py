from dotenv import load_dotenv
load_dotenv()

import os
import alpaca_trade_api as tradeapi
import pandas as pd
from scanner.signals import detect_entry, detect_exit

api = tradeapi.REST(
    key_id=os.environ['ALPACA_API_KEY'],
    secret_key=os.environ['ALPACA_SECRET_KEY'],
    base_url='https://paper-api.alpaca.markets'
)

tickers = ['NVDA', 'TSLA', 'AMD', 'AAPL', 'MSFT', 'META', 'GOOGL', 'AMZN']

print(f"\n{'='*60}")
print(" Backtesting on Today's Live Data")
print(f"{'='*60}\n")

for ticker in tickers:
    try:
        bars = api.get_bars(ticker, '1Min', limit=1000, adjustment='raw').df
        if len(bars) < 60:
            print(f"{ticker}: Not enough data ({len(bars)} bars)")
            continue
        
        bars.index = pd.to_datetime(bars.index).tz_convert('America/New_York')
        bars.columns = [c.capitalize() for c in bars.columns]
        
        position = None
        trades = []
        bars_list = []
        
        for timestamp, row in bars.iterrows():
            if timestamp.hour >= 10:
                if position:
                    exit_price = row['Close']
                    pnl = (exit_price - position['entry_price']) * position['qty']
                    trades.append({'pnl': pnl, 'reason': '10am_cutoff'})
                break
            
            bars_list.append(row)
            if len(bars_list) > 60:
                bars_list.pop(0)
            
            window_df = pd.DataFrame(bars_list)
            
            if position:
                exit_sig = detect_exit(window_df, position['entry_price'], position['stop'], ticker)
                if exit_sig:
                    exit_price = row['Close']
                    pnl = (exit_price - position['entry_price']) * position['qty']
                    trades.append({'pnl': pnl, 'reason': exit_sig.reason})
                    position = None
                continue
            
            candidate = {
                'ticker': ticker,
                'bars': window_df,
                'pillars': {},
                'score': 5,
                'gap_pct': 15,
                'rel_vol': 10,
                'total_vol': int(window_df['Volume'].sum())
            }
            
            entry_sig = detect_entry(candidate)
            if entry_sig:
                qty = 33
                position = {
                    'entry_price': entry_sig.price,
                    'stop': entry_sig.stop,
                    'qty': qty
                }
                print(f"{ticker}: ENTRY @ ${entry_sig.price:.2f} (stop: ${entry_sig.stop:.2f})")
        
        total_pnl = sum(t['pnl'] for t in trades)
        print(f"{ticker}: {len(trades)} trades, P&L: ${total_pnl:+,.2f}")
    except Exception as e:
        print(f"{ticker}: Error - {e}")

print(f"\n{'='*60}\n")