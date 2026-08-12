"""
main_session.py

Session monitor — called by session_monitor.yml.
Runs from 7:05 AM ET until 10:00 AM ET hard cutoff.
Polls every 60 seconds for first-pullback entry/exit signals.
Sends Discord notifications on signal fire.
Logs every signal and skip to logs/session_YYYYMMDD.csv.

Ross-style R:R + runners + daily walk-away:
- Risk per trade: 1% of account (RISK_PCT).
- Stop: pullback low (with tiny buffer).
- Target_2r: tracked but NOT used as a hard exit.
- Exit only when an exit indicator fires (stop, topping tail, below EMA/VWAP, vol spike)
  or at the 10:00 AM hard cutoff.
- Partial sells:
    * First exit indicator → sell 60% of shares (core).
    * Second exit indicator → sell remaining 40% (runner).
- Daily walk-away rules (from transcript):
    * Stop taking new entries if:
        - we've given back ≥ 50% of the day's peak P&L, or
        - we hit MAX_DAILY_LOSS.
    * Still manage existing positions to exit, but no new trades.
"""

import os
import csv
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from scanner.pillars import _get_alpaca_client, get_bars, score_ticker
from scanner.signals import detect_entry, detect_exit, Signal
from scanner.notify import (
    send_entry_signal, send_exit_signal,
    send_daily_cutoff, send_no_candidates,
)

ET = ZoneInfo("America/New_York")
LOG_DIR = "logs"
POLL_SEC = 60  # poll every 60 seconds
CUTOFF_H = 10  # Ross's hard 10:00 AM cutoff

# Risk & money management
RISK_PCT = 0.01  # 1% of account per trade
ACCOUNT_EQUITY = 65_000.0  # set this to your current sim account size
MAX_DAILY_LOSS = 2_000.0   # e.g. ~1–2% of account; adjust to your comfort

# Runner / partials
FIRST_EXIT_SELL_FRAC = 0.6  # sell 60% on first exit indicator (core)
# remaining 40% is the runner, sold on next indicator or cutoff

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
        return [
            r[0].strip().upper()
            for r in csv.reader(f)
            if r and r[0].strip() and not r[0].startswith("#") and r[0].strip() != "TICKER"
        ]

def log_signal(row: dict):
    os.makedirs(LOG_DIR, exist_ok=True)
    date_str = datetime.now(ET).strftime("%Y%m%d")
    path = os.path.join(LOG_DIR, f"session_{date_str}.csv")
    fields = [
        "timestamp", "ticker", "action", "price", "stop", "target_2r",
        "risk_per_share", "reason", "score", "gap_pct", "rel_vol", "total_vol",
        "shares", "partial", "daily_pnl", "peak_daily_pnl"
    ]
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
    print(f" Max daily loss: ${MAX_DAILY_LOSS:,.2f}")
    print(f"{'='*55}\n")

    # api is now a tuple: (data_client, trading_client)
    api = _get_alpaca_client()
    data_client, trading_client = api

    # Load pre-market candidates
    candidates = load_candidates()
    if not candidates:
        print(" No pre-market candidates found — running live scan of watchlist …")
        watchlist = load_watchlist()
        for ticker in watchlist:
            r = score_ticker(api, ticker)
            if r:
                candidates.append({k: v for k, v in r.items() if k != "bars"})

    if not candidates:
        send_no_candidates("No candidates and watchlist empty. Nothing to monitor.")
        return

    candidate_map = {c["ticker"]: c for c in candidates}
    watchlist = [c["ticker"] for c in candidates]

    print(f" Monitoring {len(watchlist)} candidates: {', '.join(watchlist)}\n")

    open_positions: dict[str, dict] = {}
    fired_entries: set[str] = set()
    total_entries: int = 0
    notified_cutoff: bool = False

    # Daily P&L tracking (walk-away logic)
    daily_pnl: float = 0.0
    peak_daily_pnl: float = 0.0
    stopped_for_day: bool = False

    while True:
        now_et = datetime.now(ET)

        # ── Hard 10:00 AM cutoff ──────────────────────────────────────────────
        if now_et.hour >= CUTOFF_H:
            if not notified_cutoff:
                print(
                    f"\n 10:00 AM cutoff reached — no new entries. "
                    f"Total signals: {total_entries}"
                )
                send_daily_cutoff(total_entries)

            for ticker, pos in list(open_positions.items()):
                bars = get_bars(data_client, ticker, limit=5)
                exit_price = (
                    bars["Close"].iloc[-1] if not bars.empty else pos["entry_price"]
                )
                pnl = (exit_price - pos["entry_price"]) * pos["shares_remaining"]
                daily_pnl += pnl

                exit_sig = Signal(
                    type="EXIT",
                    ticker=ticker,
                    price=exit_price,
                    reason="hard_cutoff",
                )
                send_exit_signal(exit_sig, pos["entry_price"], pnl)
                log_signal({
                    "timestamp": now_et.isoformat(),
                    "ticker": ticker,
                    "action": "EXIT",
                    "price": exit_price,
                    "reason": "hard_cutoff",
                    "risk_per_share": pnl / pos["shares_total"],
                    "shares": pos["shares_remaining"],
                    "partial": False,
                    "daily_pnl": daily_pnl,
                    "peak_daily_pnl": peak_daily_pnl,
                    "stop": pos["stop"],
                    "target_2r": pos["target_2r"],
                    "score": "",
                    "gap_pct": "",
                    "rel_vol": "",
                    "total_vol": "",
                })
                del open_positions[ticker]

            notified_cutoff = True
            break

        # ── Daily walk-away check ─────────────────────────────────────────────
        if not stopped_for_day:
            if peak_daily_pnl > 0 and daily_pnl <= 0.5 * peak_daily_pnl:
                print(
                    "\n Walk-away: given back >= 50% of peak daily P&L. "
                    "No new entries for the rest of the day."
                )
                stopped_for_day = True
            elif daily_pnl <= -MAX_DAILY_LOSS:
                print(
                    "\n Walk-away: max daily loss hit. "
                    "No new entries for the rest of the day."
                )
                stopped_for_day = True

        # ── Poll each candidate ───────────────────────────────────────────────
        for ticker in watchlist:
            bars = get_bars(data_client, ticker, limit=60)
            if bars.empty:
                continue

            meta = candidate_map.get(ticker, {})

            # ── Exit check ───────────────────────────────────────────────────
            if ticker in open_positions:
                pos = open_positions[ticker]
                exit_sig = detect_exit(bars, pos["entry_price"], pos["stop"], ticker)

                if exit_sig and pos["shares_remaining"] > 0:
                    pnl = (exit_sig.price - pos["entry_price"]) * pos["shares_remaining"]
                    daily_pnl += pnl
                    peak_daily_pnl = max(peak_daily_pnl, daily_pnl)

                    if pos["exits_fired"] == 0:
                        shares_to_sell = int(pos["shares_total"] * FIRST_EXIT_SELL_FRAC)
                        shares_remaining = pos["shares_total"] - shares_to_sell
                        partial = True
                        reason = f"{exit_sig.reason}_partial_core"
                        pos["exits_fired"] += 1
                        pos["shares_remaining"] = shares_remaining
                        pos["entry_pnl_at_first_exit"] = pnl

                        print(
                            f" {now_et.strftime('%H:%M')} EXIT (partial) {ticker} "
                            f"@${exit_sig.price} ({reason}) "
                            f"sold {shares_to_sell} shares, "
                            f"keeping {shares_remaining} runner. "
                            f"P&L on this chunk: ${pnl:,.2f}"
                        )
                    else:
                        shares_to_sell = pos["shares_remaining"]
                        shares_remaining = 0
                        partial = False
                        reason = f"{exit_sig.reason}_full_runner"
                        pos["shares_remaining"] = 0

                        print(
                            f" {now_et.strftime('%H:%M')} EXIT (runner) {ticker} "
                            f"@${exit_sig.price} ({reason}) "
                            f"sold {shares_to_sell} shares. "
                            f"Total trade P&L: ${pnl:,.2f}"
                        )

                    send_exit_signal(exit_sig, pos["entry_price"], pnl)
                    log_signal({
                        "timestamp": now_et.isoformat(),
                        "ticker": ticker,
                        "action": "EXIT",
                        "price": exit_sig.price,
                        "reason": reason,
                        "risk_per_share": pnl / pos["shares_total"],
                        "shares": shares_to_sell,
                        "partial": partial,
                        "daily_pnl": daily_pnl,
                        "peak_daily_pnl": peak_daily_pnl,
                        "stop": pos["stop"],
                        "target_2r": pos["target_2r"],
                        "score": "",
                        "gap_pct": "",
                        "rel_vol": "",
                        "total_vol": "",
                    })

                    if shares_remaining == 0:
                        del open_positions[ticker]

                continue

            # ── Entry check ──────────────────────────────────────────────────
            if ticker in fired_entries:
                continue

            if stopped_for_day:
                continue

            live_candidate = dict(meta)
            live_candidate["bars"] = bars

            entry_sig = detect_entry(live_candidate)
            if entry_sig:
                total_entries += 1
                fired_entries.add(ticker)

                risk_per_share = entry_sig.risk_per_share
                if risk_per_share <= 0:
                    continue
                dollar_risk = ACCOUNT_EQUITY * RISK_PCT
                shares_total = max(1, int(dollar_risk / risk_per_share))

                open_positions[ticker] = {
                    "entry_price": entry_sig.price,
                    "stop": entry_sig.stop,
                    "target_2r": entry_sig.target_2r,
                    "shares_total": shares_total,
                    "shares_remaining": shares_total,
                    "exits_fired": 0,
                    "entry_pnl_at_first_exit": 0.0,
                }

                print(
                    f" {now_et.strftime('%H:%M')} ENTRY {ticker} @${entry_sig.price}"
                    f" stop=${entry_sig.stop} 2R=${entry_sig.target_2r}"
                    f" shares={shares_total} risk=${dollar_risk:,.2f}"
                )
                send_entry_signal(entry_sig)
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
                    "shares": shares_total,
                    "partial": False,
                    "daily_pnl": daily_pnl,
                    "peak_daily_pnl": peak_daily_pnl,
                })
            else:
                print(f" {now_et.strftime('%H:%M')} {ticker} no signal", flush=True)

        # ── Wait before next poll ─────────────────────────────────────────────
        print(f" — sleeping {POLL_SEC}s …", flush=True)
        time.sleep(POLL_SEC)

    print(" Session monitor complete.")

if __name__ == "__main__":
    main()
