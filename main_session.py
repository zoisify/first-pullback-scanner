"""
Main session monitor - checks for entry signals and manages positions
Ross-style: Scale-out at 1.5R/3R/5R, hold 25% core with trailing stop
"""

import yfinance as yf
import csv
import os
from datetime import datetime, time, timedelta
from pathlib import Path
from scanner.signals import detect_first_pullback, submit_entry_order, manage_position, Signal, SignalType
from scanner.notify import send_discord_message
from scanner.executor import get_trading_client

def load_watchlist() -> list:
    """Load watchlist from CSV file"""
    watchlist_path = Path('data/watchlist.csv')
    if not watchlist_path.exists():
        return []
    
    tickers = []
    with open(watchlist_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            tickers.append(row['ticker'])
    return tickers

def check_entry_signals(tickers: list) -> list:
    """Check for entry signals on watchlist tickers"""
    signals = []
    
    for ticker in tickers:
        print(f"Checking {ticker}...")
        signal = detect_first_pullback(ticker)
        
        if signal:
            print(f"  Signal detected: {signal.reason}")
            signals.append(signal)
            
            # Send Discord alert
            message = f"🚀 ENTRY SIGNAL\n\nTicker: {signal.ticker}\nPrice: ${signal.price:.2f}\nReason: {signal.reason}\nTime: {signal.timestamp.strftime('%H:%M:%S')}"
            send_discord_message(message)
            
            # Submit entry order
            entry_result = submit_entry_order(signal, qty=33)
            
            if entry_result:
                # Send confirmation
                confirm_msg = f"✅ ORDER FILLED\n\n{signal.ticker} x 33 shares\nEntry: ${signal.price:.2f}\nOrder ID: {entry_result['order_id']}"
                send_discord_message(confirm_msg)
                
                # Save position tracking info
                save_position_entry(signal.ticker, signal.price, entry_result['order_id'])
        else:
            print(f"  No signal")
    
    return signals

def save_position_entry(ticker: str, entry_price: float, order_id: str):
    """Save position entry info for tracking"""
    positions_file = Path('data/positions.csv')
    
    # Create file if doesn't exist
    if not positions_file.exists():
        positions_file.parent.mkdir(exist_ok=True)
        with open(positions_file, 'w') as f:
            writer = csv.writer(f)
            writer.writerow(['ticker', 'entry_price', 'order_id', 'entry_time', 'qty'])
    
    # Append new position
    with open(positions_file, 'a') as f:
        writer = csv.writer(f)
        writer.writerow([ticker, entry_price, order_id, datetime.now().isoformat(), 33])
    
    print(f"Position saved: {ticker} @ ${entry_price:.2f}")

def manage_open_positions():
    """Manage all open positions - Ross-style scale-out"""
    positions_file = Path('data/positions.csv')
    
    if not positions_file.exists():
        print("No positions to manage")
        return
    
    # Read positions
    positions = []
    with open(positions_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            positions.append(row)
    
    if not positions:
        print("No open positions")
        return
    
    print(f"Managing {len(positions)} position(s)...")
    
    # Manage each position
    for pos in positions:
        ticker = pos['ticker']
        entry_price = float(pos['entry_price'])
        entry_time = datetime.fromisoformat(pos['entry_time'])
        
        print(f"\nManaging {ticker} (entry: ${entry_price:.2f} @ {entry_time.strftime('%H:%M')})...")
        
        # Use Ross-style position management
        result = manage_position(ticker, entry_price, entry_time)
        
        if result['action'] == 'SCALE_OUT':
            # Send Discord alert for scale-out
            for order in result['orders']:
                msg = f"📊 SCALE-OUT\n\n{ticker}\n{order['level']}\nQty: {order['qty']} @ ${order['price']:.2f}\nOrder: {order['order_id']}"
                send_discord_message(msg)
        
        elif result['action'] == 'EXIT':
            # Send Discord alert for full exit
            for order in result['orders']:
                msg = f"❌ EXIT\n\n{ticker}\nQty: {order['qty']} @ ${order.get('exit_price', 'MARKET')}\nReason: {order.get('reason', 'Manual')}"
                send_discord_message(msg)
    
    print("\nPosition management complete")

def main():
    """Main session loop - runs every 5 minutes"""
    print(f"\n=== Session Monitor Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    
    # Check time (only run during market hours: 7 AM - 10 AM ET)
    now_et = datetime.now().time()
    start_time = time(7, 0)
    end_time = time(10, 0)
    
    if now_et < start_time or now_et > end_time:
        print(f"Outside market hours ({start_time} - {end_time}), skipping...")
        return
    
    # Load watchlist
    watchlist = load_watchlist()
    
    if not watchlist:
        print("Watchlist is empty, running pre-market scan first...")
        # Could trigger main_scan.py here
        return
    
    print(f"Loaded {len(watchlist)} tickers from watchlist")
    
    # Check for new entry signals
    print("\n--- Checking Entry Signals ---")
    signals = check_entry_signals(watchlist)
    
    if signals:
        print(f"Found {len(signals)} signal(s)")
    else:
        print("No new signals")
    
    # Manage existing positions
    print("\n--- Managing Open Positions ---")
    manage_open_positions()
    
    print(f"\n=== Session Monitor Complete: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")

if __name__ == "__main__":
    main()
