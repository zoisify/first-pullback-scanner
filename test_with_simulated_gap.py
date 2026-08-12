from scanner.signals import detect_entry, detect_exit
import pandas as pd

print(f"\n{'='*60}")
print(" Testing Scanner with Simulated 15% Gap")
print(f"{'='*60}\n")

# Load existing data (use any stock you have)
df = pd.read_csv('data/NVDA_polygon.csv')
df = df.rename(columns={
    'timestamp': 'timestamp',
    'Open': 'Open',
    'High': 'High',
    'Low': 'Low',
    'Close': 'Close',
    'Volume': 'Volume'
})
df['timestamp'] = pd.to_datetime(df['timestamp'])

# Take first 200 bars and simulate a 15% gap up
test_df = df.head(200).copy()

# Simulate gap: multiply first bar's open/high/low by 1.15
test_df.loc[0, 'Open'] *= 1.15
test_df.loc[0, 'High'] *= 1.15
test_df.loc[0, 'Low'] *= 1.15

print(f"Simulated 15% gap up at open")
print(f"\nFirst 10 bars:")
print(test_df[['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume']].head(10))

# Test scanner
print(f"\n{'='*60}")
print(" Running Scanner (9:30-10am)")
print(f"{'='*60}\n")

test_df = test_df.set_index('timestamp')
test_df.columns = [c.capitalize() for c in test_df.columns]
test_df.index = test_df.index.tz_localize('America/New_York')

position = None
bars_list = []
entries = []

for timestamp, row in test_df.iterrows():
    # Only scan 9:30-10am
    if timestamp.hour == 9 and timestamp.minute >= 30:
        pass
    elif timestamp.hour >= 10:
        if position:
            exit_price = row['Close']
            pnl = (exit_price - position['entry_price']) * position['qty']
            entries.append({'type': 'EXIT', 'time': timestamp, 'price': exit_price, 'pnl': pnl})
            print(f"10am EXIT @ ${exit_price:.2f}: ${pnl:+.2f}")
        break
    else:
        continue
    
    bars_list.append(row)
    if len(bars_list) > 60:
        bars_list.pop(0)
    
    window_df = pd.DataFrame(bars_list)
    
    if position:
        exit_sig = detect_exit(window_df, position['entry_price'], position['stop'], 'NVDA')
        if exit_sig:
            exit_price = row['Close']
            pnl = (exit_price - position['entry_price']) * position['qty']
            entries.append({'type': 'EXIT', 'time': timestamp, 'price': exit_price, 'pnl': pnl})
            print(f"EXIT @ ${exit_price:.2f}: ${pnl:+.2f} ({exit_sig.reason})")
            position = None
        continue
    
    candidate = {
        'ticker': 'NVDA',
        'bars': window_df,
        'pillars': {},
        'score': 5,
        'gap_pct': 15,  # Your threshold
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
        entries.append({'type': 'ENTRY', 'time': timestamp, 'price': entry_sig.price})
        print(f"✓ ENTRY @ ${entry_sig.price:.2f} (stop: ${entry_sig.stop:.2f})")

print(f"\nTotal trades: {len(entries)}")
if entries:
    total_pnl = sum(e.get('pnl', 0) for e in entries if e['type'] == 'EXIT')
    print(f"Total P&L: ${total_pnl:+.2f}")
print(f"{'='*60}\n")