"""Current-day pre-market gap scanner.

Gap = today's 04:00 ET pre-market price versus the previous regular-session close.
Only today's pre-market volume is included.
"""

import os
import time
import requests
from datetime import datetime, time as dt_time, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
BASE_URL = "https://data.alpaca.markets/v2"
TRADE_URL = "https://paper-api.alpaca.markets/v2"


def _headers() -> dict:
    return {
        "APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
        "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"],
    }


def get_all_symbols(min_price: float = 2.0, max_price: float = 20.0) -> list[str]:
    print(" Fetching full symbol universe from Alpaca ...")
    symbols = []
    params = {"status": "active", "asset_class": "us_equity", "exchange": "NASDAQ,NYSE,ARCA,BATS"}
    try:
        response = requests.get(f"{TRADE_URL}/assets", headers=_headers(), params=params, timeout=30)
        response.raise_for_status()
        for asset in response.json():
            if not asset.get("tradable"):
                continue
            symbol = asset.get("symbol", "")
            name = (asset.get("name") or "").upper()
            skip = ["WARRANT", " WT", " WS", " RIGHT", " UNIT", "PREFERRED", " PFD", "ETF", "FUND", "TRUST", "NOTE", "DEBENTURE"]
            if any(word in name for word in skip) or not symbol.isalpha() or len(symbol) > 5:
                continue
            symbols.append(symbol)
    except Exception as error:
        print(f" ERROR fetching assets: {error}")
    print(f" Universe: {len(symbols)} symbols")
    return symbols


def get_snapshots_batch(symbols: list[str]) -> dict:
    try:
        response = requests.get(
            f"{BASE_URL}/stocks/snapshots",
            headers=_headers(),
            params={"symbols": ",".join(symbols), "feed": "iex"},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    except Exception as error:
        print(f" Snapshot batch error: {error}")
        return {}


def _session_date(now: datetime | None = None):
    now = now or datetime.now(ET)
    if now.weekday() == 5:
        return now.date() - timedelta(days=1)
    if now.weekday() == 6:
        return now.date() - timedelta(days=2)
    return now.date()


def screen_market(min_price=2.0, max_price=20.0, min_gap_pct=0.10, min_volume=100_000, max_results=20) -> list[dict]:
    symbols = get_all_symbols(min_price, max_price)
    if not symbols:
        return []
    session_date = _session_date()
    candidates = []
    batch_size = 500
    total_batches = (len(symbols) + batch_size - 1) // batch_size
    print(f" Scanning {len(symbols)} symbols in {total_batches} batches ...")
    for index in range(0, len(symbols), batch_size):
        batch = symbols[index:index + batch_size]
        batch_number = index // batch_size + 1
        print(f" Batch {batch_number}/{total_batches} ...", end=" ", flush=True)
        snapshots = get_snapshots_batch(batch)
        hits = 0
        for symbol, snapshot in snapshots.items():
            try:
                daily = snapshot.get("dailyBar") or {}
                previous = snapshot.get("prevDailyBar") or {}
                latest = snapshot.get("latestTrade") or {}
                price = latest.get("p") or daily.get("c") or 0
                previous_close = previous.get("c") or 0
                today_volume = daily.get("v") or 0
                latest_timestamp = latest.get("t")
                if not price or not previous_close or not latest_timestamp:
                    continue
                latest_dt = datetime.fromisoformat(str(latest_timestamp).replace("Z", "+00:00")).astimezone(ET)
                if latest_dt.date() != session_date:
                    continue
                gap_pct = (price - previous_close) / previous_close
                if not (min_price <= price <= max_price and gap_pct >= min_gap_pct and today_volume >= min_volume):
                    continue
                candidates.append({
                    "ticker": symbol,
                    "price": round(float(price), 2),
                    "gap_pct": round(gap_pct * 100, 1),
                    "today_vol": int(today_volume),
                    "prev_close": round(float(previous_close), 2),
                    "latest_trade_at": latest_dt.isoformat(),
                    "premarket_start": f"{session_date.isoformat()}T04:00:00-04:00",
                    "reference_session": f"{session_date - timedelta(days=1)} regular session",
                    "gap_method": "snapshot latest trade versus previous regular-session close",
                })
                hits += 1
            except Exception:
                continue
        print(f"{hits} hits")
        time.sleep(0.2)
    candidates.sort(key=lambda item: item["gap_pct"], reverse=True)
    print(f"\n Auto-screen complete: {len(candidates)} raw hits -> returning top {min(len(candidates), max_results)}")
    return candidates[:max_results]
