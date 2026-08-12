"""
main_scan.py

Pre-market scan entrypoint — called by premarket_scan.yml at 7:00 AM ET.
Scores every ticker in data/watchlist.csv against the 5 pillars.
Sends a Discord summary of all candidates passing >= 4 pillars.
Logs results to logs/scan_YYYYMMDD.csv.
"""

import os
import csv
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from scanner.pillars import _get_alpaca_client, score_ticker
from scanner.notify import send_scan_summary, send_no_candidates

ET = ZoneInfo("America/New_York")
WATCHLIST_PATH = "data/watchlist.csv"
LOG_DIR = "logs"


def load_watchlist() -> list[str]:
    """Load tickers from watchlist CSV. One ticker per line, header optional."""
    if not os.path.exists(WATCHLIST_PATH):
        print(f"Watchlist not found at {WATCHLIST_PATH}")
        return []
    with open(WATCHLIST_PATH) as f:
        reader = csv.reader(f)
        tickers = []
        for row in reader:
            if row and row[0].strip() and not row[0].startswith("#"):
                t = row[0].strip().upper()
                if t != "TICKER":   # skip header row if present
                    tickers.append(t)
    return list(dict.fromkeys(tickers))   # deduplicate, preserve order


def save_scan_log(candidates: list[dict], all_results: list[dict]):
    """Save full scan results (pass + fail) to a dated CSV in logs/."""
    os.makedirs(LOG_DIR, exist_ok=True)
    date_str = datetime.now(ET).strftime("%Y%m%d")
    path = os.path.join(LOG_DIR, f"scan_{date_str}.csv")

    fields = ["ticker","score","price","gap_pct","rel_vol","total_vol","float",
              "gap","price_pillar","rel_vol_pillar","volume_pillar","float_pillar"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in all_results:
            row = {
                "ticker":         r.get("ticker",""),
                "score":          r.get("score", 0),
                "price":          r.get("price",""),
                "gap_pct":        r.get("gap_pct",""),
                "rel_vol":        r.get("rel_vol",""),
                "total_vol":      r.get("total_vol",""),
                "float":          r.get("float",""),
                "gap":            r.get("pillars",{}).get("gap",""),
                "price_pillar":   r.get("pillars",{}).get("price",""),
                "rel_vol_pillar": r.get("pillars",{}).get("rel_vol",""),
                "volume_pillar":  r.get("pillars",{}).get("volume",""),
                "float_pillar":   r.get("pillars",{}).get("float",""),
            }
            w.writerow(row)

    # Also save candidates list as JSON for session monitor to pick up
    candidates_clean = [{k: v for k, v in c.items() if k != "bars"}
                        for c in candidates]
    json_path = os.path.join(LOG_DIR, f"candidates_{date_str}.json")
    with open(json_path, "w") as f:
        json.dump(candidates_clean, f, indent=2)

    print(f"  Scan log saved: {path}")
    print(f"  Candidates saved: {json_path}")


def main():
    print(f"\n{'='*55}")
    print(f"  Pre-Market Scan — {datetime.now(ET).strftime('%Y-%m-%d %H:%M %Z')}")
    print(f"{'='*55}")

    tickers = load_watchlist()
    if not tickers:
        send_no_candidates("Watchlist is empty — add tickers to data/watchlist.csv")
        return

    print(f"  Scanning {len(tickers)} tickers …\n")

    api = _get_alpaca_client()
    candidates = []
    all_results = []

    for ticker in tickers:
        print(f"  {ticker} …", end=" ", flush=True)
        result = score_ticker(api, ticker)
        if result:
            # Strip bars DataFrame for logging (not serializable)
            loggable = {k: v for k, v in result.items() if k != "bars"}
            all_results.append(loggable)
            candidates.append(result)
            print(f"✓ {result['score']}/5 pillars  gap={result['gap_pct']}%  rvol={result['rel_vol']}×")
        else:
            all_results.append({"ticker": ticker, "score": 0})
            print("✗ failed")

    candidates.sort(key=lambda x: x["score"], reverse=True)

    print(f"\n  {len(candidates)} candidate(s) passing ≥4 pillars.")
    save_scan_log(candidates, all_results)

    if candidates:
        send_scan_summary(candidates)
    else:
        send_no_candidates("No stocks passing ≥4/5 pillars pre-market today. Sit on hands.")

    print("  Done.")


if __name__ == "__main__":
    main()
