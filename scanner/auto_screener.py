"""Pre-market-only gap scanner with explicit session boundaries."""

import os
import time
import requests
from datetime import datetime, timedelta, time as clock_time
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
BASE_URL = "https://data.alpaca.markets/v2"
TRADE_URL = "https://paper-api.alpaca.markets/v2"


def _headers():
    return {"APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"], "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"]}


def get_all_symbols(min_price=2.0, max_price=20.0):
    print(" Fetching full symbol universe from Alpaca ...")
    params = {"status": "active", "asset_class": "us_equity", "exchange": "NASDAQ,NYSE,ARCA,BATS"}
    symbols = []
    try:
        response = requests.get(f"{TRADE_URL}/assets", headers=_headers(), params=params, timeout=30)
        response.raise_for_status()
        for asset in response.json():
            symbol = asset.get("symbol", "")
            name = (asset.get("name") or "").upper()
            skip = ["WARRANT", " WT", " WS", " RIGHT", " UNIT", "PREFERRED", " PFD", "ETF", "FUND", "TRUST", "NOTE", "DEBENTURE"]
            if asset.get("tradable") and symbol.isalpha() and len(symbol) <= 5 and not any(word in name for word in skip):
                symbols.append(symbol)
    except Exception as error:
        print(f" ERROR fetching assets: {error}")
    print(f" Universe: {len(symbols)} symbols")
    return symbols


def get_snapshots_batch(symbols):
    try:
        response = requests.get(f"{BASE_URL}/stocks/snapshots", headers=_headers(), params={"symbols": ",".join(symbols), "feed": "iex"}, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as error:
        print(f" Snapshot batch error: {error}")
        return {}


def _previous_trading_day(value):
    value = value - timedelta(days=1)
    while value.weekday() >= 5:
        value -= timedelta(days=1)
    return value


def _session_date(now=None):
    now = now or datetime.now(ET)
    return now.date()


def _parse_timestamp(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(ET)


def _get_dated_bars(symbols, start, end, timeframe="1Min"):
    params = {"symbols": ",".join(symbols), "timeframe": timeframe, "start": start.isoformat(), "end": end.isoformat(), "feed": "iex", "limit": 10000}
    try:
        response = requests.get(f"{BASE_URL}/stocks/bars", headers=_headers(), params=params, timeout=30)
        response.raise_for_status()
        return response.json().get("bars", {})
    except Exception as error:
        print(f" Historical bars error: {error}")
        return {}


def screen_market(min_price=2.0, max_price=20.0, min_gap_pct=0.10, min_volume=100_000, max_results=20):
    symbols = get_all_symbols(min_price, max_price)
    if not symbols:
        return []
    now = datetime.now(ET)
    today = now.date()
    previous_day = _previous_trading_day(today)
    premarket_start = datetime.combine(today, clock_time(4, 0), ET)
    premarket_end = min(now, datetime.combine(today, clock_time(9, 30), ET))
    previous_close_start = datetime.combine(previous_day, clock_time(15, 59), ET)
    previous_close_end = datetime.combine(previous_day, clock_time(16, 1), ET)
    print(f" Current pre-market window: {premarket_start:%Y-%m-%d %H:%M} to {premarket_end:%H:%M} ET")
    print(f" Reference regular close window: {previous_close_start:%Y-%m-%d %H:%M} to {previous_close_end:%H:%M} ET")

    current_bars = _get_dated_bars(symbols, premarket_start, premarket_end)
    close_bars = _get_dated_bars(symbols, previous_close_start, previous_close_end)
    candidates = []
    for symbol in symbols:
        bars = current_bars.get(symbol, [])
        closes = close_bars.get(symbol, [])
        if not bars or not closes:
            continue
        try:
            latest = max(bars, key=lambda row: row.get("t", ""))
            previous = max(closes, key=lambda row: row.get("t", ""))
            price = float(latest["c"])
            previous_close = float(previous["c"])
            volume = sum(int(row.get("v", 0)) for row in bars)
            latest_at = _parse_timestamp(latest.get("t"))
            if not latest_at or latest_at.date() != today or not previous_close:
                continue
            gap = (price - previous_close) / previous_close
            if not (min_price <= price <= max_price and gap >= min_gap_pct and volume >= min_volume):
                continue
            candidates.append({
                "ticker": symbol,
                "price": round(price, 2),
                "gap_pct": round(gap * 100, 1),
                "today_vol": volume,
                "prev_close": round(previous_close, 4),
                "latest_trade_at": latest_at.isoformat(),
                "premarket_start": premarket_start.isoformat(),
                "premarket_end": premarket_end.isoformat(),
                "reference_close_at": _parse_timestamp(previous.get("t")).isoformat(),
                "reference_session": f"{previous_day} regular session close",
                "gap_method": "today 04:00-09:30 ET pre-market close versus previous 16:00 ET regular close",
            })
        except Exception:
            continue
    candidates.sort(key=lambda item: item["gap_pct"], reverse=True)
    print(f"\n Auto-screen complete: {len(candidates)} raw hits -> returning top {min(len(candidates), max_results)}")
    return candidates[:max_results]
