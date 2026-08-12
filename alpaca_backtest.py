from dotenv import load_dotenv
load_dotenv()

import os
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
import alpaca_trade_api as tradeapi

ET = ZoneInfo("America/New_York")

def get_historical_bars(ticker: str, limit: int = 390) -> pd.DataFrame:
    api = tradeapi.REST(
        key_id=os.environ["APCA_API_KEY_ID"],
        secret_key=os.environ["APCA_API_SECRET_KEY"],
        base_url="https://paper-api.alpaca.markets",
        api_version="v2"
    )
    
    bars = api.get_bars(
        ticker,
        "1Min",
        limit=limit,
        feed="iex",
        adjustment="raw"
    ).df
    
    if bars.empty:
        return pd.DataFrame()
    
    bars.index = bars.index.tz_convert(ET)
    bars.columns = [c.capitalize() for c in bars.columns]
    return bars

def run_backtest(ticker: str, date: str = None):
    if date is None:
        date = datetime.now(ET).strftime("%Y-%m-%d")
    
    print(f"\n{'='*60}")
    print(f" Backtesting {ticker} on {date}")
    print(f"{'='*60}\n")
    
    bars = get_historical_bars(ticker, limit=390)
    
    if bars.empty:
        print(f"  No data for {ticker}")
        return
    
    target_date = datetime.strptime(date, "%Y-%m-%d").date()
    bars = bars[bars.index.date == target_date]
    
    if bars.empty:
        print(f"  No data for {ticker} on {date}")
        return
    
    print(f"  Loaded {len(bars)} bars")
    
    from scanner.signals import detect_entry, detect_exit
    
    position = None
    trades = []
    bars_list = []
    
    for idx, (timestamp, row) in enumerate(bars.iterrows()):
        if timestamp.hour >= 10:
            if position:
                exit_price = row["Close"]
                pnl = (exit_price - position["entry_price"]) * position["qty"]
                trades.append({"entry": position["entry_price"], "exit": exit_price, "pnl": pnl, "reason": "10am_cutoff"})
            break
        
        bars_list.append(row)
        if len(bars_list) > 60:
            bars_list.pop(0)
        
        window_df = pd.DataFrame(bars_list)
        
        if position:
            exit_sig = detect_exit(window_df, position["entry_price"], position["stop"], ticker)
            if exit_sig:
                exit_price = row["Close"]
                pnl = (exit_price - position["entry_price"]) * position["qty"]
                trades.append({"entry": position["entry_price"], "exit": exit_price, "pnl": pnl, "reason": exit_sig.reason})
                position = None
            continue
        
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
            qty = 33
            position = {
                "entry_price": entry_sig.price,
                "stop": entry_sig.stop,
                "qty": qty
            }
            print(f"  ENTRY {timestamp.strftime('%H:%M')} @ ${entry_sig.price:.2f} (stop: ${entry_sig.stop:.2f})")
    
    total_pnl = sum(t["pnl"] for t in trades)
    print(f"\n  Trades: {len(trades)}")
    print(f"  Total P&L: ${total_pnl:+,.2f}")
    
    for i, trade in enumerate(trades, 1):
        print(f"  Trade {i}: ${trade['pnl']:+,.2f} ({trade['reason']})")

if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    run_backtest(ticker)