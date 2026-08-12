from dotenv import load_dotenv
load_dotenv()

import pandas as pd
from pathlib import Path
from scanner.signals import detect_entry, detect_exit

data_dir = Path('data')

print(f"\n{'='*60}")
print(" Backtesting on Historical Data")
print(f"{'='*60}\n")

for csv_file in data_dir.glob('*_historical.csv'):
    ticker = csv_file.stem.replace('_historical', '')
    print(f"\n{ticker}:")
    
    bars = pd.read_csv(csv_file, index_col=0, parse_dates=True)
    
    # Fix timezone
    if bars.index.tz is None:
        bars.index = pd.to_datetime(bars.index).tz_localize('America/New_York')
    else:
        bars.index = pd.to_datetime(bars.index).tz_convert('America/New_York')
    
    bars.columns = [c.capitalize() for c in bars.columns]
    
    if len(bars) < 60:
        print(f"  Not enough data ({len(bars)} bars)")
        continue
    
    position = None
    trades = []
    bars_list = []
    
    for idx, (timestamp, row) in enumerate(bars.iterrows()):
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
            print(f"  ENTRY @ ${entry_sig.price:.2f} (stop: ${entry_sig.stop:.2f})")
    
    total_pnl = sum(t['pnl'] for t in trades)
    print(f"  Trades: {len(trades)}, Total P&L: ${total_pnl:+,.2f}")