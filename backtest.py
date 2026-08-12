"""
backtest.py

Backtest the first-pullback strategy on historical data.
Tests Ross-style entry/exit logic without 2R cap.

Usage:
    python backtest.py --ticker YXT --date 2026-08-11
    python backtest.py --tickers YXT,NVDA,TSLA --start 2026-08-01 --end 2026-08-11
"""

import argparse
import pandas as pd
import yfinance as yf
from datetime import datetime, time
from zoneinfo import ZoneInfo
from pathlib import Path

# Import your actual signal detection logic
from scanner.signals import detect_entry, detect_exit, Signal

ET = ZoneInfo("America/New_York")

def get_historical_bars(ticker: str, date: str) -> pd.DataFrame:
    """
    Fetch 1-minute bars for a ticker on a specific date.
    Returns DataFrame with columns: Open, High, Low, Close, Volume
    """
    stock = yf.Ticker(ticker)
    start = f"{date} 09:30"
    end = f"{date} 16:00"
    
    try:
        bars = stock.history(start=start, end=end, interval="1m")
        if bars.empty:
            print(f"  No data for {ticker} on {date}")
            return pd.DataFrame()
        
        bars.index = bars.index.tz_localize(ET)
        bars.columns = [c.capitalize() for c in bars.columns]
        return bars
    except Exception as e:
        print(f"  Error fetching {ticker}: {e}")
        return pd.DataFrame()

def run_backtest(ticker: str, date: str, initial_capital: float = 10000) -> dict:
    """
    Run backtest on a single ticker/date.
    Returns performance stats.
    """
    print(f"\n{'='*60}")
    print(f" Backtesting {ticker} on {date}")
    print(f"{'='*60}\n")
    
    bars = get_historical_bars(ticker, date)
    if bars.empty:
        return {"ticker": ticker, "date": date, "trades": 0, "pnl": 0, "trades_detail": []}
    
    # Simulate trading
    capital = initial_capital
    position = None  # {entry_price, stop, qty, entry_bar_idx}
    trades = []
    
    # Rolling window for signal detection
    window_size = 60  # last 60 bars
    bars_list = []
    
    for idx, (timestamp, row) in enumerate(bars.iterrows()):
        # Skip before 10 AM (Ross's hard cutoff)
        if timestamp.hour >= 10:
            if position:
                # Exit at 10 AM
                exit_price = row["Close"]
                pnl = (exit_price - position["entry_price"]) * position["qty"]
                capital += pnl
                trades.append({
                    "ticker": ticker,
                    "entry_time": bars.index[position["entry_bar_idx"]],
                    "exit_time": timestamp,
                    "entry_price": position["entry_price"],
                    "exit_price": exit_price,
                    "qty": position["qty"],
                    "pnl": pnl,
                    "reason": "10am_cutoff"
                })
                position = None
            break
        
        # Add current bar to window
        bars_list.append(row)
        if len(bars_list) > window_size:
            bars_list.pop(0)
        
        # Convert to DataFrame for signal detection
        window_df = pd.DataFrame(bars_list)
        
        # Exit check
        if position:
            # Check exit conditions
            exit_sig = detect_exit(window_df, position["entry_price"], position["stop"], ticker)
            if exit_sig:
                exit_price = row["Close"]
                pnl = (exit_price - position["entry_price"]) * position["qty"]
                capital += pnl
                trades.append({
                    "ticker": ticker,
                    "entry_time": bars.index[position["entry_bar_idx"]],
                    "exit_time": timestamp,
                    "entry_price": position["entry_price"],
                    "exit_price": exit_price,
                    "qty": position["qty"],
                    "pnl": pnl,
                    "reason": exit_sig.reason
                })
                position = None
            continue
        
        # Entry check (simplified - no 5-pillar filter in backtest)
        # In real backtest, you'd filter candidates first
        candidate = {
            "ticker": ticker,
            "bars": window_df,
            "pillars": {},
            "score": 5,
            "gap_pct": 15,
            "rel_vol": 10,
            "total_vol": int(window_df["Volume"].sum())
        }
        
        entry_sig = detect_entry(candidate)
        if entry_sig:
            # Enter trade
            qty = int(capital * 0.25 / entry_sig.price)  # 25% position size
            if qty > 0:
                position = {
                    "entry_price": entry_sig.price,
                    "stop": entry_sig.stop,
                    "qty": qty,
                    "entry_bar_idx": len(bars_list) - 1
                }
                print(f"  ENTRY {timestamp.strftime('%H:%M')} @ ${entry_sig.price:.2f} (stop: ${entry_sig.stop:.2f})")
    
    # Calculate stats
    total_pnl = sum(t["pnl"] for t in trades)
    win_trades = [t for t in trades if t["pnl"] > 0]
    loss_trades = [t for t in trades if t["pnl"] <= 0]
    
    stats = {
        "ticker": ticker,
        "date": date,
        "trades": len(trades),
        "wins": len(win_trades),
        "losses": len(loss_trades),
        "win_rate": len(win_trades) / len(trades) if trades else 0,
        "total_pnl": total_pnl,
        "avg_pnl": total_pnl / len(trades) if trades else 0,
        "final_capital": capital,
        "return_pct": (capital - initial_capital) / initial_capital * 100,
        "trades_detail": trades
    }
    
    # Print results
    print(f"\n  Trades: {len(trades)}")
    print(f"  Wins: {len(win_trades)}, Losses: {len(loss_trades)}")
    print(f"  Win Rate: {stats['win_rate']*100:.1f}%")
    print(f"  Total P&L: ${total_pnl:+,.2f}")
    print(f"  Return: {stats['return_pct']:+.2f}%")
    print(f"  Final Capital: ${capital:,.2f}")
    
    return stats

def main():
    parser = argparse.ArgumentParser(description="Backtest first-pullback strategy")
    parser.add_argument("--ticker", type=str, help="Single ticker to test")
    parser.add_argument("--tickers", type=str, help="Comma-separated tickers")
    parser.add_argument("--date", type=str, help="Single date (YYYY-MM-DD)")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    args = parser.parse_args()
    
    # Determine tickers and dates to test
    if args.ticker:
        tickers = [args.ticker]
    elif args.tickers:
        tickers = args.tickers.split(",")
    else:
        print("Error: Specify --ticker or --tickers")
        return
    
    dates = []
    if args.date:
        dates = [args.date]
    elif args.start and args.end:
        start = datetime.strptime(args.start, "%Y-%m-%d")
        end = datetime.strptime(args.end, "%Y-%m-%d")
        current = start
        while current <= end:
            if current.weekday() < 5:  # Mon-Fri only
                dates.append(current.strftime("%Y-%m-%d"))
            current = current + pd.Timedelta(days=1)
    else:
        # Default: last 5 trading days
        print("No dates specified, using last 5 trading days...")
        # You'd implement date logic here
    
    # Run backtests
    all_stats = []
    for ticker in tickers:
        for date in dates:
            stats = run_backtest(ticker, date)
            all_stats.append(stats)
    
    # Summary
    if len(all_stats) > 1:
        print(f"\n{'='*60}")
        print(" SUMMARY")
        print(f"{'='*60}")
        total_trades = sum(s["trades"] for s in all_stats)
        total_pnl = sum(s["total_pnl"] for s in all_stats)
        total_wins = sum(s["wins"] for s in all_stats)
        print(f"  Total Trades: {total_trades}")
        print(f"  Total Wins: {total_wins}")
        print(f"  Total Losses: {total_trades - total_wins}")
        print(f"  Win Rate: {total_wins/total_trades*100:.1f}%" if total_trades else "  Win Rate: N/A")
        print(f"  Total P&L: ${total_pnl:+,.2f}")
        print(f"{'='*60}\n")
    
    # Save results
    output_path = Path("logs/backtest_results.csv")
    output_path.parent.mkdir(exist_ok=True)
    
    all_trades = []
    for stats in all_stats:
        if "trades_detail" in stats:
            all_trades.extend(stats["trades_detail"])
    
    if all_trades:
        df = pd.DataFrame(all_trades)
        df.to_csv(output_path, index=False)
        print(f"Results saved to {output_path}")

if __name__ == "__main__":
    main()