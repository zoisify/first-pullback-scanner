"""Pre-market-only gap scanner with explicit ET session boundaries."""

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


def _parse_timestamp(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed.astimezone(ET)


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
    value -= timedelta(days=1)
    while value.weekday() >= 5:
        value -= timedelta(days=1)
    return value


def _get_dated_bars(symbols, start, end):
    try:
        params = {"symbols": ",".join(symbols), "timeframe": "1Min", "start": start.astimezone(ZoneInfo("UTC")).isoformat(), "end": end.astimezone(ZoneInfo("UTC")).isoformat(), "feed": "iex", "limit": 10000}
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
    premarket_start = datetime.combine(today, clock_time(4), ET)
    premarket_end = min(now, datetime.combine(today, clock_time(9, 30), ET))
    previous_close_start = datetime.combine(previous_day, clock_time(15, 59), ET)
    previous_close_end = datetime.combine(previous_day, clock_time(16, 1), ET)
    print(f" Current pre-market window: {premarket_start:%Y-%m-%d %H:%M} to {premarket_end:%H:%M} ET")
    print(f" Reference regular close window: {previous_close_start:%Y-%m-%d %H:%M} to {previous_close_end:%H:%M} ET")

    current_bars = _get_dated_bars(symbols, premarket_start, premarket_end)
    close_bars = _get_dated_bars(symbols, previous_close_start, previous_close_end)
    candidates = []
    diagnostics = {"bars": 0, "volume": 0, "stale": 0, "missing_close": 0, "failed_filters": 0}

    for symbol in symbols:
        bars = current_bars.get(symbol, [])
        closes = close_bars.get(symbol, [])
        if not bars:
            continue
        et_bars = []
        for bar in bars:
            timestamp = _parse_timestamp(bar.get("t"))
            if timestamp and timestamp.date() == today and clock_time(4) <= timestamp.time() < clock_time(9, 30):
                et_bars.append((timestamp, bar))
        diagnostics["bars"] += len(et_bars)
        if not et_bars:
            diagnostics["stale"] += 1
            continue

        if not closes:
            diagnostics["missing_close"] += 1
            continue
        et_closes = [(ts, bar) for bar in closes if (ts := _parse_timestamp(bar.get("t"))) and ts.date() == previous_day and clock_time(15, 59) <= ts.time() <= clock_time(16, 1)]
        if not et_closes:
            diagnostics["missing_close"] += 1
            continue

        try:
            latest_timestamp, latest = max(et_bars, key=lambda item: item[0])
            close_timestamp, previous = max(et_closes, key=lambda item: item[0])
            price = float(latest["c"])
            previous_close = float(previous["c"])
            volume = sum(int(bar.get("v", 0)) for _, bar in et_bars)
            diagnostics["volume"] += volume
            gap = (price - previous_close) / previous_close if previous_close else 0
            if not (min_price <= price <= max_price and gap >= min_gap_pct and volume >= min_volume):
                diagnostics["failed_filters"] += 1
                continue
            candidates.append({
                "ticker": symbol, "price": round(price, 2), "gap_pct": round(gap * 100, 1), "today_vol": volume,
                "prev_close": round(previous_close, 4), "latest_trade_at": latest_timestamp.isoformat(),
                "premarket_start": premarket_start.isoformat(), "premarket_end": premarket_end.isoformat(),
                "reference_close_at": close_timestamp.isoformat(), "reference_session": f"{previous_day} regular session close",
                "gap_method": "today 04:00-09:30 ET pre-market bars versus previous 16:00 ET regular close",
            })
        except Exception:
            diagnostics["failed_filters"] += 1

    print(f" Session diagnostics: {diagnostics}")
    candidates.sort(key=lambda item: item["gap_pct"], reverse=True)
    print(f"\n Auto-screen complete: {len(candidates)} raw hits -> returning top {min(len(candidates), max_results)}")
    return candidates[:max_results]

