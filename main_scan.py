"""
main_scan.py

Pre-market scan - finds the #1 leading gapper in the market.
Ross: "It has always made the most sense to focus on the number one
leading gainer stock in the market."

Flow:
1. screen_market() -> finds stocks gapping up 10%+, $2-$20
2. score_ticker() -> scores each against 5 pillars
3. Takes the single highest scoring stock (by score then gap%)
4. Sends Discord summary
5. Saves to logs/ for session monitor
"""

from dotenv import load_dotenv
load_dotenv()

import os
import csv
import json
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo

from scanner.auto_screener import screen_market
from scanner.pillars import _get_alpaca_client, score_ticker
from scanner.notify import send_scan_summary, send_no_candidates

ET = ZoneInfo("America/New_York")
LOG_DIR = "logs"


class _Encoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        return super().default(o)


def save_scan_log(candidates: list[dict], all_results: list[dict]):
    os.makedirs(LOG_DIR, exist_ok=True)
    date_str = datetime.now(ET).strftime("%Y%m%d")

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

    candidates_clean = [{k: v for k, v in c.items() if k != "bars"}
                        for c in candidates]
    json_path = os.path.join(LOG_DIR, f"candidates_{date_str}.json")
    with open(json_path, "w") as f:
        json.dump(candidates_clean, f, indent=2, cls=_Encoder)

    print(f" Scan log: {path}")
    print(f" Candidates: {json_path}")


def write_watchlist_csv(candidates: list[dict]):
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
    print(f" Pre-Market Auto-Scan - #1 Gapper Focus")
    print(f" {datetime.now(ET).strftime('%Y-%m-%d %H:%M %Z')}")
    print(f"{'='*55}\n")

    print("[ Step 1 ] Screening full market for gap/momentum ...\n")
    # Fetch top 25 raw hits, then pick the #1 after scoring
    raw_hits = screen_market(
        min_price=2.0,
        max_price=20.0,
        min_gap_pct=0.10,
        min_volume=100_000,
        max_results=25,
    )

    if not raw_hits:
        print(" No stocks gapping up 10%+ today.")
        send_no_candidates("No stocks found gapping up >=10% today. Sit on hands.")
        return

    print(f"\n[ Step 2 ] Scoring {len(raw_hits)} hits against 5 pillars ...\n")

    api = _get_alpaca_client()

    candidates = []
    all_results = []

    for hit in raw_hits:
        ticker = hit["ticker"]
        print(f" {ticker} ...", end=" ", flush=True)
        result = score_ticker(api, ticker)
        if result:
            loggable = {k: v for k, v in result.items() if k != "bars"}
            all_results.append(loggable)
            candidates.append(result)
            print(f"OK {result['score']}/5 "
                  f"gap={result['gap_pct']}% "
                  f"rvol={result['rel_vol']}x "
                  f"vol={result['total_vol']:,}")
        else:
            all_results.append({"ticker": ticker, "score": 0,
                                "gap_pct": hit["gap_pct"],
                                "price": hit["price"]})
            print(f"FAIL failed pillars")

    # Sort by score then gap% - pick the single #1 gapper
    candidates.sort(key=lambda x: (x["score"], x["gap_pct"]), reverse=True)
    top_candidate = candidates[:1]  # ONLY the #1 stock

    if top_candidate:
        c = top_candidate[0]
        print(f"\n #1 Gapper: {c['ticker']} - {c['gap_pct']}% gap, "
              f"{c['score']}/5 pillars, rvol={c['rel_vol']}x")
    else:
        print(f"\n No candidates passed >=4 pillars today.")

    save_scan_log(top_candidate, all_results)
    write_watchlist_csv(top_candidate)

    if top_candidate:
        send_scan_summary(top_candidate)
    else:
        send_no_candidates(
            f"Found {len(raw_hits)} gapping stocks but none passed >=4/5 pillars. "
            "No trades today."
        )

    print("\n Done.")


if __name__ == "__main__":
    main()
