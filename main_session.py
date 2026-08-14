"""Session monitor with strict candidate freshness validation."""

import csv
import json
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from scanner.pillars import _get_alpaca_client, get_bars, score_ticker
from scanner.signals import detect_entry, detect_exit, detect_scalein, detect_reentry, calc_trailing_stop, Signal
from scanner.notify import send_entry_signal, send_exit_signal, send_daily_cutoff, send_no_candidates, send_pnl_update
from scanner.executor import submit_entry_order, submit_exit_order, submit_scalein_order, update_trailing_stop, get_trading_client

ET = ZoneInfo("America/New_York")
LOG_DIR = "logs"
POLL_SEC = 60
CUTOFF_H = 10


def load_candidates() -> list[dict]:
    date_str = datetime.now(ET).strftime("%Y%m%d")
    path = os.path.join(LOG_DIR, f"candidates_{date_str}.json")
    if not os.path.exists(path):
        print(f" No candidates file found at {path}")
        return []
    try:
        with open(path, encoding="utf-8") as file:
            payload = json.load(file)
        if isinstance(payload, list):
            print(" Rejecting legacy candidate format without scan date")
            return []
        if not isinstance(payload, dict) or payload.get("scan_date") != date_str:
            print(" Rejecting stale or malformed candidate file")
            return []
        candidates = payload.get("candidates")
        if not isinstance(candidates, list):
            print(" Rejecting candidate file with invalid candidates field")
            return []
        valid = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            ticker = str(candidate.get("ticker", "")).strip().upper()
            if ticker and ticker.isalpha() and len(ticker) <= 5:
                candidate["ticker"] = ticker
                valid.append(candidate)
        return valid
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        print(f" Rejecting unreadable candidate file: {error}")
        return []


def load_watchlist() -> list[str]:
    path = "data/watchlist.csv"
    if not os.path.exists(path): return []
    with open(path, encoding="utf-8-sig") as file:
        return [r[0].strip().upper() for r in csv.reader(file) if r and r[0].strip() and not r[0].startswith("#") and r[0].strip().upper() != "TICKER"]

# Existing session trading logic remains below this function in the local file.
# The safety PR changes candidate loading only; no order behavior is changed.
