"""
main_session.py

Session monitor called by session_monitor.yml.

Runs from 7:05 AM ET until 10:00 AM ET hard cutoff.
Polls every 60 seconds for first-pullback entry/exit signals.
"""

import os
import csv
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from scanner.pillars import get_alpaca_client, get_bars, score_ticker
from scanner.signals import detect_entry, detect_exit
from scanner.notify import (
    send_entry_signal,
    send_exit_signal,
    send_daily_cutoff,
    send_no_candidates,
)

ET = ZoneInfo("America/New_York")

LOGDIR = "logs"
POLLSEC = 60
CUTOFFH = 10  # 10:00 AM ET cutoff
RISKPCT = 0.01  # 1% of account per trade


def load_candidates() -> list[dict]:
    """Load candidates saved by main_scan.py this morning."""
    datestr = datetime.now(ET).strftime("%Y%m%d")
    path = os.path.join(LOGDIR, f"candidates_{datestr}.json")
    if not os.path.exists(path):
        print(f" No candidates file found at {path}")
        print(" Run main_scan.py first, or trigger the pre-market scan workflow.")
        return []
    with open(path) as f:
        return json.load(f)


def load_watchlist() -> list[str]:
    """Load watchlist from data/watchlist.csv."""
    path = "data/watchlist.csv"
    if not os.path.exists(path):
        print(" [DEBUG] Watchlist file data/watchlist.csv does not exist.")
        return []
    with open(path) as f:
        rows = [
            r[0].strip().upper()
            for r in csv.reader(f)
            if r and r[0].strip() and not r[0].startswith("#") and r[0].strip() != "TICKER"
        ]
    print(f"[DEBUG] Loaded watchlist with {len(rows)} tickers: {rows}")
    return rows


def log_signal(row: dict) -> None:
    os.makedirs(LOGDIR, exist_ok=True)
    datestr = datetime.now(ET).strftime("%Y%m%d")
    path = os.path.join(LOGDIR, f"session_{datestr}.csv")
    fields = [
        "timestamp",
        "ticker",
        "action",
        "price",
        "stop",
        "target2r",
        "riskpershare",
        "reason",
        "score",
        "gappct",
        "relvol",
        "totalvol",
    ]
    write_header = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if write_header:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in fields})


def main() -> None:
    print("=======================================================")
    print(f" Session Monitor — {datetime.now(ET).strftime('%Y-%m-%d %H:%M')} EDT")
    print()
    print(f" Hard cutoff: {CUTOFFH:02d}:00 AM ET")
    print("=======================================================")
    print()

    api = get_alpaca_client()

    candidates = load_candidates()
    watchlist = load_watchlist()

    if not candidates and not watchlist:
        print("[REASON] No candidates file and watchlist is empty at startup.")
        send_no_candidates("No candidates and watchlist empty. Nothing to monitor")
        return

    if not candidates and watchlist:
        print(
            f"[REASON] No pre-market candidates; will run live scan of "
            f"{len(watchlist)} watchlist tickers via Alpaca."
        )
        for ticker in watchlist:
            try:
                r = score_ticker(api, ticker)
                if r:
                    candidates.append({k: v for k, v in r.items() if k != "bars"})
                else:
                    print(f"[{ticker}] did not pass pillar filters.")
            except Exception as e:
                print(f"[ERROR] Failed to score {ticker}: {repr(e)}")

        if not candidates:
            print("[REASON] Scanned watchlist, but no tickers passed pillars.")
            send_no_candidates("No candidates passed pillars from watchlist.")
            return

    candidate_map = {c["ticker"]: c for c in candidates}
    watchlist = [c["ticker"] for c in candidates]

    print(f" Monitoring {len(watchlist)} candidates: {', '.join(watchlist)}")

    open_positions: dict[str, dict] = {}
    fired_entries: set[str] = set()
    total_entries: int = 0
    notified_cutoff: bool = False

    while True:
        now_et = datetime.now(ET)

        if now_et.hour >= CUTOFFH:
            if not notified_cutoff:
                print(" 10:00 AM cutoff reached; no new entries.")
                print(f" Total entry signals today: {total_entries}")
                send_daily_cutoff(total_entries)
                # exit any open positions at market
                for ticker, pos in list(open_positions.items()):
                    bars = get_bars(api, ticker, limit=5)
                    exit_price = bars["Close"].iloc[-1] if not bars.empty else pos["entry_price"]
                    pnl = exit_price - pos["entry_price"]
                    from scanner.signals import Signal

                    exitsig = Signal(
                        type="EXIT",
                        ticker=ticker,
                        price=exit_price,
                        reason="hardcutoff",
                    )
                    send_exit_signal(exitsig, pos["entry_price"], pnl)
                    log_signal(
                        {
                            "timestamp": now_et.isoformat(),
                            "ticker": ticker,
                            "action": "EXIT",
                            "price": exit_price,
                            "reason": "hardcutoff",
                            "riskpershare": pnl,
                        }
                    )
                    del open_positions[ticker]
                notified_cutoff = True
            break

        for ticker in watchlist:
            bars = get_bars(api, ticker, limit=60)
            if bars.empty:
                continue

            meta = candidate_map.get(ticker, {})

            if ticker in open_positions:
                pos = open_positions[ticker]
                exitsig = detect_exit(bars, pos["entry_price"], pos["stop"], ticker)
                if exitsig:
                    pnl = exitsig.price - pos["entry_price"]
                    print(
                        now_et.strftime("%H:%M"),
                        "EXIT",
                        ticker,
                        exitsig.price,
                        exitsig.reason,
                        f"PL/share {pnl:.2f}",
                    )
                    send_exit_signal(exitsig, pos["entry_price"], pnl)
                    log_signal(
                        {
                            "timestamp": now_et.isoformat(),
                            "ticker": ticker,
                            "action": "EXIT",
                            "price": exitsig.price,
                            "reason": exitsig.reason,
                            "riskpershare": pnl,
                        }
                    )
                    del open_positions[ticker]
                continue

            if ticker in fired_entries:
                continue

            live_candidate = dict(meta)
            live_candidate["bars"] = bars

            entrysig = detect_entry(live_candidate)
            if entrysig:
                total_entries += 1
                fired_entries.add(ticker)
                open_positions[ticker] = {
                    "entry_price": entrysig.price,
                    "stop": entrysig.stop,
                    "target2r": entrysig.target2r,
                }
                print(
                    now_et.strftime("%H:%M"),
                    "ENTRY",
                    ticker,
                    entrysig.price,
                    f"stop={entrysig.stop}",
                    f"2R={entrysig.target2r}",
                )
                send_entry_signal(entrysig)
                log_signal(
                    {
                        "timestamp": now_et.isoformat(),
                        "ticker": ticker,
                        "action": "ENTRY",
                        "price": entrysig.price,
                        "stop": entrysig.stop,
                        "target2r": entrysig.target2r,
                        "riskpershare": entrysig.riskpershare,
                        "reason": entrysig.reason,
                        "score": entrysig.score,
                        "gappct": entrysig.gappct,
                        "relvol": entrysig.relvol,
                        "totalvol": entrysig.totalvol,
                    }
                )

        print(f" sleeping {POLLSEC}s ...", flush=True)
        time.sleep(POLLSEC)

    print(" Session monitor complete.")


if __name__ == "__main__":
    main()