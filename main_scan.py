"""Pre-market scan using only current pre-market bars and explicit regular close."""

from dotenv import load_dotenv
from pathlib import Path
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

import csv
import json
import os
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np

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

def _atomic_json_write(path, payload):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".candidates-", suffix=".tmp", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2, cls=_Encoder)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, path)
    except Exception:
        try: os.unlink(temp_path)
        except FileNotFoundError: pass
        raise

def save_scan_log(candidates, all_results):
    os.makedirs(LOG_DIR, exist_ok=True)
    now = datetime.now(ET)
    date_str = now.strftime("%Y%m%d")
    path = os.path.join(LOG_DIR, f"scan_{date_str}.csv")
    fields = ["ticker", "score", "price", "gap_pct", "rel_vol", "total_vol", "float", "gap", "price_pillar", "rel_vol_pillar", "volume_pillar", "float_pillar", "latest_trade_at", "premarket_start", "premarket_end", "reference_close_at", "reference_session"]
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields); writer.writeheader()
        for item in all_results:
            writer.writerow({"ticker": item.get("ticker", ""), "score": item.get("score", 0), "price": item.get("price", ""), "gap_pct": item.get("gap_pct", ""), "rel_vol": item.get("rel_vol", ""), "total_vol": item.get("total_vol", ""), "float": item.get("float", ""), "gap": item.get("pillars", {}).get("gap", ""), "price_pillar": item.get("pillars", {}).get("price", ""), "rel_vol_pillar": item.get("pillars", {}).get("rel_vol", ""), "volume_pillar": item.get("pillars", {}).get("volume", ""), "float_pillar": item.get("pillars", {}).get("float", ""), **item.get("session", {})})
    json_path = os.path.join(LOG_DIR, f"candidates_{date_str}.json")
    payload = {"scan_date": date_str, "generated_at": now.isoformat(), "candidates": [_clean(item) for item in candidates]}
    _atomic_json_write(json_path, payload)
    print(f" Scan log: {path}\n Candidates: {json_path}")

def write_watchlist_csv(candidates):
    os.makedirs("data", exist_ok=True)
    with open("data/watchlist.csv", "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file); writer.writerow(["TICKER"])
        for candidate in candidates: writer.writerow([candidate["ticker"]])
    print(f" Watchlist updated: data/watchlist.csv ({len(candidates)} tickers)")

def main():
    print(f"\n{'=' * 55}\n Pre-Market Auto-Scan - #1 Gapper Focus\n {datetime.now(ET).strftime('%Y-%m-%d %H:%M %Z')}\n{'=' * 55}\n")
    raw_hits = screen_market(min_price=2, max_price=20, min_gap_pct=0.10, min_volume=100000, max_results=25)
    if not raw_hits:
        send_all_pillar_report([]); send_no_candidates("No current-day pre-market stocks found. Sit on hands."); return
    api = _get_alpaca_client(); results = []
    for hit in raw_hits:
        ticker = hit["ticker"]; print(f" {ticker} ...", end=" ", flush=True)
        float_shares = get_float(ticker)
        result = evaluate_ticker(api, ticker, raw_hit=hit, float_shares=float_shares); results.append(result)
        print(f"{result['score']}/5 gap={result.get('gap_pct')}% rvol={result.get('rel_vol')}x vol={result.get('total_vol')} float={result.get('float')}")
    results.sort(key=lambda item: (item.get("score", 0), item.get("gap_pct") or 0), reverse=True); send_all_pillar_report(results)
    passing = [item for item in results if item.get("score", 0) >= 4 or (item.get("score", 0) == 3 and "UNKNOWN" in item.get("pillars", {}).values())]
    top = passing[:1]
    if not top:
        save_scan_log([], results); write_watchlist_csv([]); send_no_candidates(f"Found {len(raw_hits)} current-day pre-market gapper(s), but none passed the existing provisional threshold."); return
    save_scan_log(top, results); write_watchlist_csv(top); send_scan_summary(top)
    print(f"\n #1 Gapper: {top[0]['ticker']} - {top[0].get('gap_pct')}% current-day pre-market gap, {top[0]['score']}/5 pillars\n\n Done.")

if __name__ == "__main__": main()
