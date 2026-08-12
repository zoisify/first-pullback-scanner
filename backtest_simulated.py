from dotenv import load_dotenv
load_dotenv()

import pandas as pd
from pathlib import Path
from scanner.signals import detect_entry, detect_exit

data_dir = Path('data')

print(f"\n{'='*60}")
print(" Backtesting with Simulated Gaps")
print(f"{'='*60}\n")

total_trades = 0
total_pnl = 0

for csv_file in sorted(data_dir.glob('*_historical.csv')):
    ticker = csv_file.stem.replace('_historical', '')
    
    bars = pd.read_csv(csv_file, index_col=0, parse_dates=True)
    
    if bars.index.tz is None:
        bars.index = pd.to_datetime(bars.index).tz_localize('UTC')
    bars.index = bars.index.tz_convert('America/New_York')
    bars.columns = [c.capitalize() for c in bars.columns]
    
    if len(bars) < 60:
        continue
    
    # Simulate a gap: first bar open vs previous close
    first_open = bars.iloc[0]['Open']
    prev_close = bars.iloc[0]['Close'] * 0.95  # Simulate 5% gap up
    bars.iloc[0, bars.columns.get_loc('Open')] = prev_close * 1.05
    
    position = None
    trades = []
    bars_list = []
    
    for timestamp, row in bars.iterrows():
        if timestamp.hour == 9 and timestamp.minute >= 30:
            pass
        elif timestamp.hour >= 10:
            if position:
                exit_price = row['Close']
                pnl = (exit_price - position['entry_price']) * position['qty']
                trades.append({'pnl': pnl})
            break
        else:
            continue
        
        bars_list.append(row)
        if len(bars_list) > 60:
            bars_list.pop(0)
        
        window_df = pd.DataFrame(bars_list)
        
        if position:
            exit_sig = detect_exit(window_df, position['entry_price'], position['stop'], ticker)
            if exit_sig:
                exit_price = row['Close']
                pnl = (exit_price - position['entry_price']) * position['qty']
                trades.append({'pnl': pnl})
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
        
        if timestamp.hour == 10 and timestamp.minute == 0 and position:
            exit_price = row['Close']
            pnl = (exit_price - position['entry_price']) * position['qty']
            trades.append({'pnl': pnl})
            position = None
    
    day_pnl = sum(t['pnl'] for t in trades)
    if trades:
        print(f"{ticker}: {len(trades)} trades, P&L: ${day_pnl:+,.2f}")
        total_trades += len(trades)
        total_pnl += day_pnl

print(f"\n{'='*60}")
print(f"TOTAL: {total_trades} trades, P&L: ${total_pnl:+,.2f}")
print(f"{'='*60}\n")