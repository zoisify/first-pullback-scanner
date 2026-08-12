"""
main_session.py

Session monitor — called by session_monitor.yml.
Runs from 7:05 AM ET until 10:00 AM ET hard cutoff.
Polls every 60 seconds for first-pullback entry/exit signals.
Sends Discord notifications on signal fire.
Logs every signal and skip to logs/session_YYYYMMDD.csv.
Automatically submits paper orders on Alpaca for entries and exits.
"""

import os
import csv
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from scanner.pillars import _get_alpaca_client, get_bars, score_ticker
from scanner.signals import detect_entry, detect_exit
from scanner.notify import (
    send_entry_signal, send_exit_signal,
    send_daily_cutoff, send_no_candidates,
)
from scanner.executor import submit_entry_order, submit_exit_order, get_current_position_qty

ET = ZoneInfo("America/New_York")
LOG_DIR = "logs"
POLL_SEC = 60  # poll every 60 seconds
CUTOFF_H = 10  # Ross's hard 10:00 AM cutoff
RISK_PCT = 0.01  # 1% of account per trade — set to what you actually want


# ── Helpers ────────────────────────────────────────────────────────────────────

def load_candidates() -> list[dict]:
    """Load candidates saved by main_scan.py this morning."""
    date_str = datetime.now(ET).strftime("%Y%m%d")
    path = os.path.join(LOG_DIR, f"candidates_{date_str}.json")
    if not os.path.exists(path):
        print(f" No candidates file found at {path}")
        print(" Run main_scan.py first, or trigger the pre-market scan workflow.")
        return []
    with open(path) as f:
        return json.load(f)


def load_watchlist() -> list[str]:
    path = "data/watchlist.csv"
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [r[0].strip().upper() for r in csv.reader(f)
                if r and r[0].strip() and not r[0].startswith("#") and r[0].strip() != "TICKER"]


def log_signal(row: dict):
    os.makedirs(LOG_DIR, exist_ok=True)
    date_str = datetime.now(ET).strftime("%Y%m%d")
    path = os.path.join(LOG_DIR, f"session_{date_str}.csv")
    fields = ["timestamp", "ticker", "action", "price", "stop", "target_2r",
              "risk_per_share", "reason", "score", "gap_pct", "rel_vol", "total_vol"]
    write_header = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if write_header:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in fields})


# ── Main session loop ──────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*55}")
    print(f" Session Monitor — {datetime.now(ET).strftime('%Y-%m-%d %H:%M %Z')}")
    print(f" Hard cutoff: {CUTOFF_H}:00 AM ET")
    print(f"{'='*55}\n")

    api = _get_alpaca_client()

    # Load pre-market candidates
    candidates = load_candidates()
    if not candidates:
        # Fall back to re-scanning the watchlist from scratch
        print(" No pre-market candidates found — running live scan of watchlist …")
        watchlist = load_watchlist()
        for ticker in watchlist:
            r = score_ticker(api, ticker)
            if r:
                candidates.append({k: v for k, v in r.items() if k != "bars"})

    if not candidates:
        send_no_candidates("No candidates and watchlist empty. Nothing to monitor.")
        return

    # Ticker → candidate metadata (for signal formatting)
    candidate_map = {c["ticker"]: c for c in candidates}
    watchlist = [c["ticker"] for c in candidates]

    print(f" Monitoring {len(watchlist)} candidates: {', '.join(watchlist)}\n")

    # State tracking across polls
    open_positions: dict[str, dict] = {}  # ticker → {entry_price, stop, target_2r, shares}
    fired_entries: set[str] = set()  # tickers we've already sent an entry for
    total_entries: int = 0
    notified_cutoff: bool = False

    while True:
        now_et = datetime.now(ET)

        # ── Hard 10:00 AM cutoff ──────────────────────────────────────────────
        if now_et.hour >= CUTOFF_H:
            if not notified_cutoff:
                print(f"\n 10:00 AM cutoff reached — no new entries. Total signals: {total_entries}")
                send_daily_cutoff(total_entries)

                # Force-exit any open positions
                for ticker, pos in list(open_positions.items()):
                    bars = get_bars(api, ticker, limit=5)
                    exit_price = bars["Close"].iloc[-1] if not bars.empty else pos["entry_price"]
                    pnl = exit_price - pos["entry_price"]
                    from scanner.signals import Signal
                    exit_sig = Signal(type="EXIT", ticker=ticker, price=exit_price, reason="hard_cutoff")
                    send_exit_signal(exit_sig, pos["entry_price"], pnl)
                    log_signal({"timestamp": now_et.isoformat(), "ticker": ticker,
                                "action": "EXIT", "price": exit_price,
                                "reason": "hard_cutoff", "risk_per_share": pnl})
                    
                    # Submit paper exit order for forced cutoff
                    qty_to_sell = pos.get("shares", 0)
                    if qty_to_sell <= 0:
                        qty_to_sell = get_current_position_qty(ticker)
                    submit_exit_order(exit_sig, current_qty=qty_to_sell)
                    
                    del open_positions[ticker]
                notified_cutoff = True
            break

        # ── Poll each candidate ───────────────────────────────────────────────
        for ticker in watchlist:
            bars = get_bars(api, ticker, limit=60)
            if bars.empty:
                continue

            meta = candidate_map.get(ticker, {})

            # ── Exit check (if in a paper position) ──────────────────────────
            if ticker in open_positions:
                pos = open_positions[ticker]
                exit_sig = detect_exit(bars, pos["entry_price"], pos["stop"], ticker)
                if exit_sig:
                    pnl = exit_sig.price - pos["entry_price"]
                    print(f" {now_et.strftime('%H:%M')} EXIT {ticker} @${exit_sig.price}"
                          f" ({exit_sig.reason}) P&L/share: ${pnl:+.2f}")
                    send_exit_signal(exit_sig, pos["entry_price"], pnl)
                    log_signal({"timestamp": now_et.isoformat(), "ticker": ticker,
                                "action": "EXIT", "price": exit_sig.price,
                                "reason": exit_sig.reason, "risk_per_share": pnl})
                    
                    # Submit paper exit order
                    qty_to_sell = pos.get("shares", 0)
                    if qty_to_sell <= 0:
                        qty_to_sell = get_current_position_qty(ticker)  # fallback
                    submit_exit_order(exit_sig, current_qty=qty_to_sell)
                    
                    del open_positions[ticker]

                # 2R target check
                elif bars["Close"].iloc[-1] >= pos["target_2r"]:
                    price = bars["Close"].iloc[-1]
                    pnl = price - pos["entry_price"]
                    print(f" {now_et.strftime('%H:%M')} EXIT {ticker} @${price} (2R target) P&L/share: ${pnl:+.2f}")
                    from scanner.signals import Signal
                    exit_sig = Signal(type="EXIT", ticker=ticker, price=round(price, 2), reason="2r_target")
                    send_exit_signal(exit_sig, pos["entry_price"], pnl)
                    log_signal({"timestamp": now_et.isoformat(), "ticker": ticker,
                                "action": "EXIT", "price": price,
                                "reason": "2r_target", "risk_per_share": pnl})
                    
                    # Submit paper exit order
                    qty_to_sell = pos.get("shares", 0)
                    if qty_to_sell <= 0:
                        qty_to_sell = get_current_position_qty(ticker)  # fallback
                    submit_exit_order(exit_sig, current_qty=qty_to_sell)
                    
                    del open_positions[ticker]
                    continue

            # ── Entry check ───────────────────────────────────────────────────
            if ticker in fired_entries:
                continue  # already sent an entry for this ticker today

            # Refresh candidate metadata with live bars for signal detection
            live_candidate = dict(meta)
            live_candidate["bars"] = bars

            entry_sig = detect_entry(live_candidate)
            if entry_sig:
                total_entries += 1
                fired_entries.add(ticker)
                open_positions[ticker] = {
                    "entry_price": entry_sig.price,
                    "stop": entry_sig.stop,
                    "target_2r": entry_sig.target_2r,
                }
                print(f" {now_et.strftime('%H:%M')} ENTRY {ticker} @${entry_sig.price}"
                      f" stop=${entry_sig.stop} 2R=${entry_sig.target_2r}")
                send_entry_signal(entry_sig)
                
                # Submit paper order
                order_result = submit_entry_order(entry_sig, account_size=10_000, risk_pct=RISK_PCT)
                if order_result:
                    open_positions[ticker]["shares"] = order_result["shares"]
                
                log_signal({
                    "timestamp": now_et.isoformat(),
                    "ticker": ticker,
                    "action": "ENTRY",
                    "price": entry_sig.price,
                    "stop": entry_sig.stop,
                    "target_2r": entry_sig.target_2r,
                    "risk_per_share": entry_sig.risk_per_share,
                    "reason": entry_sig.reason,
                    "score": entry_sig.score,
                    "gap_pct": entry_sig.gap_pct,
                    "rel_vol": entry_sig.rel_vol,
                    "total_vol": entry_sig.total_vol,
                })
            else:
                print(f" {now_et.strftime('%H:%M')} {ticker} no signal", flush=True)

        # ── Wait before next poll ─────────────────────────────────────────────
        print(f" — sleeping {POLL_SEC}s …", flush=True)
        time.sleep(POLL_SEC)

    print(" Session monitor complete.")


if __name__ == "__main__":
    main()
