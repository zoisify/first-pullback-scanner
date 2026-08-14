"""Pre-market scan using current-day session boundaries."""

from dotenv import load_dotenv
from pathlib import Path
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

import csv
import json
import os
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo

from scanner.auto_screener import screen_market
from scanner.pillars import _get_alpaca_client, evaluate_ticker, get_float
from scanner.notify import send_all_pillar_report, send_scan_summary, send_no_candidates

ET = ZoneInfo("America/New_York")
LOG_DIR = "logs"

class _Encoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer): return int(obj)
        if isinstance(obj, np.floating): return float(obj)
        if isinstance(obj, np.ndarray): return obj.tolist()
        return super().default(obj)

def _clean(result):
    return {key: value for key, value in result.items() if key != "bars"}

def save_scan_log(candidates, all_results):
    os.makedirs(LOG_DIR, exist_ok=True)
    date_str = datetime.now(ET).strftime("%Y%m%d")
    path = os.path.join(LOG_DIR, f"scan_{date_str}.csv")
    fields = ["ticker", "score", "price", "gap_pct", "rel_vol", "total_vol", "float", "gap", "price_pillar", "rel_vol_pillar", "volume_pillar", "float_pillar", "latest_trade_at", "premarket_start", "reference_session"]
    with open(path, "w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for item in all_results:
            writer.writerow({
                "ticker": item.get("ticker", ""), "score": item.get("score", 0), "price": item.get("price", ""), "gap_pct": item.get("gap_pct", ""), "rel_vol": item.get("rel_vol", ""), "total_vol": item.get("total_vol", ""), "float": item.get("float", ""), "gap": item.get("pillars", {}).get("gap", ""), "price_pillar": item.get("pillars", {}).get("price", ""), "rel_vol_pillar": item.get("pillars", {}).get("rel_vol", ""), "volume_pillar": item.get("pillars", {}).get("volume", ""), "float_pillar": item.get("pillars", {}).get("float", ""), "latest_trade_at": item.get("session", {}).get("latest_trade_at", ""), "premarket_start": item.get("session", {}).get("premarket_start", ""), "reference_session": item.get("session", {}).get("reference_session", ""),
            })
    json_path = os.path.join(LOG_DIR, f"candidates_{date_str}.json")
    with open(json_path, "w") as file: json.dump([_clean(item) for item in candidates], file, indent=2, cls=_Encoder)
    print(f" Scan log: {path}\n Candidates: {json_path}")

def write_watchlist_csv(candidates):
    os.makedirs("data", exist_ok=True)
    with open("data/watchlist.csv", "w", newline="") as file:
        writer = csv.writer(file); writer.writerow(["TICKER"])
        for candidate in candidates: writer.writerow([candidate["ticker"]])
    print(f" Watchlist updated: data/watchlist.csv ({len(candidates)} tickers)")

def main():
    print(f"\n{'=' * 55}\n Pre-Market Auto-Scan - #1 Gapper Focus\n {datetime.now(ET).strftime('%Y-%m-%d %H:%M %Z')}\n{'=' * 55}\n")
    raw_hits = screen_market(min_price=2.0, max_price=20.0, min_gap_pct=0.10, min_volume=100_000, max_results=25)
    if not raw_hits:
        send_all_pillar_report([]); send_no_candidates("No stocks found gapping up >=10% today. Sit on hands."); return
    api = _get_alpaca_client(); results = []
    for hit in raw_hits:
        ticker = hit["ticker"]
        print(f" {ticker} ...", end=" ", flush=True)
        float_shares = get_float(ticker)
        result = evaluate_ticker(api, ticker, raw_hit=hit, float_shares=float_shares)
        results.append(result)
        print(f"{result['score']}/5 gap={result.get('gap_pct')}% rvol={result.get('rel_vol')}x vol={result.get('total_vol')} float={result.get('float')}")
    results.sort(key=lambda item: (item.get("score", 0), item.get("gap_pct") or 0), reverse=True)
    send_all_pillar_report(results)
    passing = [item for item in results if item.get("score", 0) >= 4 or (item.get("score", 0) == 3 and "UNKNOWN" in item.get("pillars", {}).values())]
    top_candidate = passing[:1]
    if not top_candidate:
        save_scan_log([], results); write_watchlist_csv([]); send_no_candidates(f"Found {len(raw_hits)} gapping stocks. Full five-pillar diagnostics sent, but none passed >=4/5 pillars. No trades today."); print("\n Done."); return
    save_scan_log(top_candidate, results); write_watchlist_csv(top_candidate); send_scan_summary(top_candidate)
    print(f"\n #1 Gapper: {top_candidate[0]['ticker']} - {top_candidate[0].get('gap_pct')}% gap, {top_candidate[0]['score']}/5 pillars\n\n Done.")

if __name__ == "__main__": main()
