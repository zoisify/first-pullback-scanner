"""Pre-market scan and Discord diagnostics for all raw gappers."""

from dotenv import load_dotenv
load_dotenv()

import csv
import json
import os
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo

from scanner.auto_screener import screen_market
from scanner.pillars import _get_alpaca_client, evaluate_ticker, get_float_fmp
from scanner.notify import send_all_pillar_report, send_scan_summary, send_no_candidates

ET = ZoneInfo("America/New_York")
LOG_DIR = "logs"


class _Encoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def _clean(result: dict) -> dict:
    return {key: value for key, value in result.items() if key != "bars"}


def save_scan_log(candidates: list[dict], all_results: list[dict]):
    os.makedirs(LOG_DIR, exist_ok=True)
    date_str = datetime.now(ET).strftime("%Y%m%d")
    path = os.path.join(LOG_DIR, f"scan_{date_str}.csv")
    fields = [
        "ticker", "score", "price", "gap_pct", "rel_vol", "total_vol", "float",
        "gap", "price_pillar", "rel_vol_pillar", "volume_pillar", "float_pillar",
    ]
    with open(path, "w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for result in all_results:
            writer.writerow({
                "ticker": result.get("ticker", ""),
                "score": result.get("score", 0),
                "price": result.get("price", ""),
                "gap_pct": result.get("gap_pct", ""),
                "rel_vol": result.get("rel_vol", ""),
                "total_vol": result.get("total_vol", ""),
                "float": result.get("float", ""),
                "gap": result.get("pillars", {}).get("gap", ""),
                "price_pillar": result.get("pillars", {}).get("price", ""),
                "rel_vol_pillar": result.get("pillars", {}).get("rel_vol", ""),
                "volume_pillar": result.get("pillars", {}).get("volume", ""),
                "float_pillar": result.get("pillars", {}).get("float", ""),
            })

    json_path = os.path.join(LOG_DIR, f"candidates_{date_str}.json")
    with open(json_path, "w") as file:
        json.dump([_clean(item) for item in candidates], file, indent=2, cls=_Encoder)
    print(f" Scan log: {path}")
    print(f" Candidates: {json_path}")


def write_watchlist_csv(candidates: list[dict]):
    os.makedirs("data", exist_ok=True)
    csv_path = "data/watchlist.csv"
    with open(csv_path, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["TICKER"])
        for candidate in candidates:
            writer.writerow([candidate["ticker"]])
    print(f" Watchlist updated: {csv_path} ({len(candidates)} tickers)")


def main():
    print(f"\n{'=' * 55}")
    print(" Pre-Market Auto-Scan - #1 Gapper Focus")
    print(f" {datetime.now(ET).strftime('%Y-%m-%d %H:%M %Z')}")
    print(f"{'=' * 55}\n")

    print("[ Step 1 ] Screening full market for gap/momentum ...\n")
    raw_hits = screen_market(
        min_price=2.0,
        max_price=20.0,
        min_gap_pct=0.10,
        min_volume=100_000,
        max_results=25,
    )

    if not raw_hits:
        print(" No stocks gapping up 10%+ today.")
        send_all_pillar_report([])
        send_no_candidates("No stocks found gapping up >=10% today. Sit on hands.")
        return

    print(f"\n[ Step 2 ] Evaluating all {len(raw_hits)} raw gappers against 5 pillars ...\n")
    api = _get_alpaca_client()
    all_results = []
    for hit in raw_hits:
        ticker = hit["ticker"]
        print(f" {ticker} ...", end=" ", flush=True)
        result = evaluate_ticker(api, ticker)
        all_results.append(result)
        print(
            f"{result['score']}/5 "
            f"gap={result.get('gap_pct', 'n/a')}% "
            f"rvol={result.get('rel_vol', 'n/a')}x "
            f"vol={result.get('total_vol', 'n/a')}"
        )

    all_results.sort(key=lambda item: (item.get("score", 0), item.get("gap_pct") or 0), reverse=True)
    send_all_pillar_report(all_results)

    passing = [
        result for result in all_results
        if result.get("score", 0) >= 4
        or (result.get("score", 0) == 3 and "UNKNOWN" in result.get("pillars", {}).values())
    ]
    passing.sort(key=lambda item: (item.get("score", 0), item.get("gap_pct") or 0), reverse=True)
    top_candidate = passing[:1]

    if not top_candidate:
        print("\n No candidates passed >=4 pillars today.")
        save_scan_log([], all_results)
        write_watchlist_csv([])
        send_no_candidates(
            f"Found {len(raw_hits)} gapping stocks. Full five-pillar diagnostics sent, but none passed >=4/5 pillars. No trades today."
        )
        print("\n Done.")
        return

    winner = top_candidate[0]
    print(f"\n[ Step 3 ] Getting float for #1 qualifying gapper: {winner['ticker']} ...")
    float_shares = get_float_fmp(winner["ticker"])
    if float_shares is not None:
        winner["float"] = int(float_shares)
        winner["pillars"]["float"] = "PASS" if float_shares <= 20_000_000 else "FAIL"
        winner["score"] = sum(value == "PASS" for value in winner["pillars"].values())
        winner["pillar_details"]["float"] = f"{int(float_shares):,} <= 20,000,000"
    else:
        print(" Float unknown - proceeding according to existing policy")

    save_scan_log(top_candidate, all_results)
    write_watchlist_csv(top_candidate)
    send_scan_summary(top_candidate)
    print(f"\n #1 Gapper: {winner['ticker']} - {winner.get('gap_pct')}% gap, {winner['score']}/5 pillars")
    print("\n Done.")


if __name__ == "__main__":
    main()
