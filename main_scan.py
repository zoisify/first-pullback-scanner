
"""
main_scan.py

Pre-market scan entrypoint — called by premarket_scan.yml at 7:00 AM ET.
Now fully automated: screens the entire market via Alpaca snapshots,
no static watchlist needed.

Flow:
1. auto_screener.screen_market() → finds all stocks gapping up 10%+, $2–$20
2. score_ticker() → scores each hit against all 5 pillars
3. Sends Discord summary of candidates passing >= 4 pillars
4. Saves candidates to logs/ for session_monitor to pick up
5. Overwrites data/watchlist.csv so manual Finviz step is obsolete
"""

import os
import csv
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from scanner.auto_screener import screen_market
from scanner.pillars import _get_alpaca_client, score_ticker
from scanner.notify import send_scan_summary, send_no_candidates

ET = ZoneInfo("America/New_York")
LOG_DIR = "logs"


def save_scan_log(candidates: list[dict], all_results: list[dict]):
    os.makedirs(LOG_DIR, exist_ok=True)
    date_str = datetime.now(ET).strftime("%Y%m%d")

    # CSV of all scored tickers
    path = os.path.join(LOG_DIR, f"scan_{date_str}.csv")
    fields = ["ticker", "score", "price", "gap_pct", "rel_vol",
              "total_vol", "float", "gap", "price_pillar",
              "rel_vol_pillar", "volume_pillar", "float_pillar"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in all_results:
            row = {
                "ticker": r.get("ticker", ""),
                "score": r.get("score", 0),
                "price": r.get("price", ""),
                "gap_pct": r.get("gap_pct", ""),
                "rel_vol": r.get("rel_vol", ""),
                "total_vol": r.get("total_vol", ""),
                "float": r.get("float", ""),
                "gap": r.get("pillars", {}).get("gap", ""),
                "price_pillar": r.get("pillars", {}).get("price", ""),
                "rel_vol_pillar": r.get("pillars", {}).get("rel_vol", ""),
                "volume_pillar": r.get("pillars", {}).get("volume", ""),
                "float_pillar": r.get("pillars", {}).get("float", ""),
            }
            w.writerow(row)

    # JSON of passing candidates for session_monitor
    candidates_clean = [{k: v for k, v in c.items() if k != "bars"}
                        for c in candidates]
    json_path = os.path.join(LOG_DIR, f"candidates_{date_str}.json")
    with open(json_path, "w") as f:
        json.dump(candidates_clean, f, indent=2)

    print(f" Scan log: {path}")
    print(f" Candidates: {json_path}")


def write_watchlist_csv(candidates: list[dict]):
    """
    Overwrite data/watchlist.csv with today's auto-screened tickers.
    This makes the manual Finviz → CSV step completely obsolete.
    """
    os.makedirs("data", exist_ok=True)
    csv_path = "data/watchlist.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["TICKER"])
        for c in candidates:
            w.writerow([c["ticker"]])
    print(f" Watchlist updated: {csv_path} ({len(candidates)} tickers)")


def main():
    print(f"\n{'='*55}")
    print(f" Pre-Market Auto-Scan")
    print(f" {datetime.now(ET).strftime('%Y-%m-%d %H:%M %Z')}")
    print(f"{'='*55}\n")

    # Step 1: auto-screen the whole market
    print("[ Step 1 ] Screening full market for gap/momentum …\n")
    raw_hits = screen_market(
        min_price=2.0,
        max_price=20.0,
        min_gap_pct=0.10,
        min_volume=100_000,
        max_results=25,  # score the top 25 gap stocks
    )

    if not raw_hits:
        print(" No stocks gapping up 10%+ today.")
        send_no_candidates("No stocks found gapping up ≥10% today. Sit on hands.")
        return

    print(f"\n[ Step 2 ] Scoring {len(raw_hits)} hits against 5 pillars …\n")

    api = _get_alpaca_client()
    candidates = []
    all_results = []

    for hit in raw_hits:
        ticker = hit["ticker"]
        print(f" {ticker} …", end=" ", flush=True)
        result = score_ticker(api, ticker)
        if result:
            loggable = {k: v for k, v in result.items() if k != "bars"}
            all_results.append(loggable)
            candidates.append(result)
            print(f"✓ {result['score']}/5 "
                  f"gap={result['gap_pct']}% "
                  f"rvol={result['rel_vol']}×· "
                  f"vol={result['total_vol']:,}")
        else:
            all_results.append({"ticker": ticker, "score": 0,
                                "gap_pct": hit["gap_pct"],
                                "price": hit["price"]})
            print(f"✗ failed pillars")

    candidates.sort(key=lambda x: x["score"], reverse=True)

    print(f"\n {len(candidates)} candidate(s) passing ≥4 pillars.")
    save_scan_log(candidates, all_results)
    write_watchlist_csv(candidates)  # <-- new: auto-update watchlist

    if candidates:
        send_scan_summary(candidates)
    else:
        send_no_candidates(
            f"Found {len(raw_hits)} gapping stocks but none passed ≥4/5 pillars. "
            "No trades today."
        )

    print("\n Done.")


if __name__ == "__main__":
    main()
