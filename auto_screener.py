"""
scanner/auto_screener.py

Automatically scans the full US equity market every morning.
No static watchlist needed — pulls every active stock from Alpaca,
batches snapshot requests, and filters down to momentum candidates.

Filters applied (matching the 5 pillars):
  - Price $2–$20
  - Gap up >= 10% from prior close
  - Today's volume >= 100K (early morning proxy — grows through session)
  - Excludes ETFs, warrants, rights, preferred shares
"""

import os
import time
import requests

BASE_URL  = "https://data.alpaca.markets/v2"
TRADE_URL = "https://paper-api.alpaca.markets/v2"


def _headers() -> dict:
    return {
        "APCA-API-KEY-ID":     os.environ["ALPACA_API_KEY"],
        "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"],
    }


def get_all_symbols(min_price: float = 2.0, max_price: float = 20.0) -> list[str]:
    """
    Pull every active, tradable US equity from Alpaca.
    Filters out ETFs, warrants, rights, preferred shares by name pattern.
    Returns a list of ticker symbols.
    """
    print("  Fetching full symbol universe from Alpaca …")
    symbols = []
    url = f"{TRADE_URL}/assets"
    params = {
        "status":      "active",
        "asset_class": "us_equity",
        "exchange":    "NASDAQ,NYSE,ARCA,BATS",  # excludes OTC
    }
    try:
        r = requests.get(url, headers=_headers(), params=params, timeout=30)
        r.raise_for_status()
        assets = r.json()
        for a in assets:
            # Skip non-tradable and leveraged/structured products
            if not a.get("tradable"):
                continue
            sym = a.get("symbol", "")
            name = (a.get("name") or "").upper()
            # Filter out warrants, rights, units, preferred, ETFs by name
            skip_keywords = ["WARRANT", " WT", " WS", " RIGHT", " UNIT",
                             "PREFERRED", " PFD", "ETF", "FUND", "TRUST",
                             "NOTE", "DEBENTURE"]
            if any(kw in name for kw in skip_keywords):
                continue
            # Skip symbols with special chars (warrants: AAPL+, AAPL.WS etc)
            if not sym.isalpha() or len(sym) > 5:
                continue
            symbols.append(sym)
    except Exception as e:
        print(f"  ERROR fetching assets: {e}")

    print(f"  Universe: {len(symbols)} symbols")
    return symbols


def get_snapshots_batch(symbols: list[str]) -> dict:
    """
    Fetch Alpaca snapshots for up to 1000 symbols at once.
    Returns dict of symbol → snapshot data.
    """
    url = f"{BASE_URL}/stocks/snapshots"
    params = {
        "symbols": ",".join(symbols),
        "feed":    "iex",   # free tier
    }
    try:
        r = requests.get(url, headers=_headers(), params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  Snapshot batch error: {e}")
        return {}


def screen_market(
    min_price:   float = 2.0,
    max_price:   float = 20.0,
    min_gap_pct: float = 0.10,
    min_volume:  int   = 100_000,
    max_results: int   = 20,
) -> list[dict]:
    """
    Full market scan. Returns list of candidate dicts sorted by gap % desc.
    Each dict has: ticker, price, gap_pct, today_vol, prev_close.
    """
    symbols = get_all_symbols(min_price, max_price)
    if not symbols:
        return []

    candidates = []
    batch_size = 500   # Alpaca allows up to 1000 but 500 is safer
    total_batches = (len(symbols) + batch_size - 1) // batch_size

    print(f"  Scanning {len(symbols)} symbols in {total_batches} batches …")

    for i in range(0, len(symbols), batch_size):
        batch   = symbols[i:i + batch_size]
        batch_n = (i // batch_size) + 1
        print(f"  Batch {batch_n}/{total_batches} …", end=" ", flush=True)

        snaps = get_snapshots_batch(batch)
        hits  = 0

        for sym, snap in snaps.items():
            try:
                daily     = snap.get("dailyBar") or {}
                prev      = snap.get("prevDailyBar") or {}
                latest    = snap.get("latestTrade") or {}

                price      = latest.get("p") or daily.get("c") or 0
                prev_close = prev.get("c") or 0
                today_vol  = daily.get("v") or 0
                open_price = daily.get("o") or price

                if not price or not prev_close:
                    continue

                gap_pct = (open_price - prev_close) / prev_close

                # Apply filters
                if not (min_price <= price <= max_price):
                    continue
                if gap_pct < min_gap_pct:
                    continue
                if today_vol < min_volume:
                    continue

                candidates.append({
                    "ticker":     sym,
                    "price":      round(price, 2),
                    "gap_pct":    round(gap_pct * 100, 1),
                    "today_vol":  int(today_vol),
                    "prev_close": round(prev_close, 2),
                    "open_price": round(open_price, 2),
                })
                hits += 1

            except Exception:
                continue

        print(f"{hits} hits")
        time.sleep(0.2)   # be gentle with the API

    # Sort by gap % descending, cap results
    candidates.sort(key=lambda x: x["gap_pct"], reverse=True)
    top = candidates[:max_results]

    print(f"\n  Auto-screen complete: {len(candidates)} raw hits → "
          f"returning top {len(top)}")
    return top
