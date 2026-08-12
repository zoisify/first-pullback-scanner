"""
scanner/pillars.py

The 5-pillar universe filter from the transcript, scored per ticker.
Uses Alpaca free tier for real-time bars and quote data.

Ross's pillars (from transcript):
1. Relative volume >= 5x (he mentions 5-10x sweet spot, >20x exceptional)
2. Gap / move >= 10% from prior close
3. Price between $2 and $20
4. Float <= 20 million shares
5. Total volume >= 1M (soft — he says "not much volume" at 45K shares early on YXT)
"""

import os
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def get_alpaca_client():
    """Returns an Alpaca REST client using env vars set by GitHub Actions secrets."""
    import alpaca_trade_api as tradeapi

    return tradeapi.REST(
        key_id=os.environ["ALPACA_API_KEY"],
        secret_key=os.environ["ALPACA_SECRET_KEY"],
        base_url="https://paper-api.alpaca.markets",
        api_version="v2",
    )


def get_bars(api, ticker: str, limit: int = 60) -> pd.DataFrame:
    """
    Fetch the last `limit` 1-minute bars for a ticker.
    Returns a DataFrame with columns Open/High/Low/Close/Volume.
    Returns empty DataFrame on failure.
    """
    try:
        bars = api.get_bars(
            ticker,
            "1Min",
            limit=limit,
            feed="iex",  # free tier — IEX feed
            adjustment="raw",
        ).df

        if bars.empty:
            return pd.DataFrame()

        bars.index = bars.index.tz_convert(ET)
        bars.columns = [c.capitalize() for c in bars.columns]

        # Keep only today's bars
        today = datetime.now(ET).date()
        return bars[bars.index.date == today]
    except Exception as e:
        print(f" [{ticker}] bars error: {e}")
        return pd.DataFrame()


def get_asset_info(api, ticker: str) -> dict:
    """Fetch static asset info (shares outstanding as float proxy)."""
    try:
        asset = api.get_asset(ticker)
        return {"tradable": asset.tradable, "fractionable": asset.fractionable}
    except Exception:
        return {}


def score_ticker(
    api,
    ticker: str,
    min_price: float = 2.0,
    max_price: float = 20.0,
    min_gap_pct: float = 0.10,
    min_rel_vol: float = 5.0,
    max_float: int = 20_000_000,
    min_total_vol: int = 500_000,
) -> dict | None:
    """
    Score a single ticker against the 5 pillars.
    Returns a result dict if it passes >= 4 pillars, else None.
    """
    bars = get_bars(api, ticker, limit=120)
    if bars.empty or len(bars) < 3:
        return None

    last_price = bars["Close"].iloc[-1]
    open_price = bars["Open"].iloc[0]
    total_vol = bars["Volume"].sum()
    elapsed_min = len(bars)

    # Prior close: get yesterday's last bar
    try:
        prev_bars = api.get_bars(
            ticker, "1Day", limit=2, feed="iex", adjustment="raw"
        ).df
        prior_close = prev_bars["close"].iloc[-2] if len(prev_bars) >= 2 else open_price
    except Exception:
        prior_close = open_price

    gap_pct = (open_price - prior_close) / prior_close if prior_close else 0

    # Relative volume: scale today's volume to what we'd expect at this time of day
    # Use average daily vol from recent bars
    try:
        hist = api.get_bars(
            ticker, "1Day", limit=10, feed="iex", adjustment="raw"
        ).df
        avg_daily_vol = hist["volume"].mean() if not hist.empty else total_vol
    except Exception:
        avg_daily_vol = total_vol

    # Scale to fraction of day elapsed (390-min session)
    expected_vol = avg_daily_vol * (elapsed_min / 390)
    rel_vol = total_vol / expected_vol if expected_vol > 0 else 0

    # Float via yfinance
    float_shares = _get_float_yfinance(ticker)

    # --- Score each pillar ---
    pillar_results = {
        "gap": gap_pct >= min_gap_pct,
        "price": min_price <= last_price <= max_price,
        "rel_vol": rel_vol >= min_rel_vol,
        "volume": total_vol >= min_total_vol,
        "float": (float_shares <= max_float) if float_shares else None,  # None = unknown
    }

    # Count definitive passes (None = unknown)
    definitive = {k: v for k, v in pillar_results.items() if v is not None}
    score = sum(definitive.values())
    unknowns = len(pillar_results) - len(definitive)

    # Need >= 4 definitive passes (or 3 passes + 1 unknown)
    passes = score >= 4 or (score == 3 and unknowns >= 1)
    if not passes:
        return None

    return {
        "ticker": ticker,
        "price": round(last_price, 2),
        "gap_pct": round(gap_pct * 100, 1),
        "rel_vol": round(rel_vol, 1),
        "total_vol": int(total_vol),
        "float": int(float_shares) if float_shares else "unknown",
        "score": score,
        "pillars": {
            k: ("✓" if v else ("?" if v is None else "✗"))
            for k, v in pillar_results.items()
        },
        "bars": bars,  # pass through for signal detection
        "prior_close": prior_close,
    }


def _get_float_yfinance(ticker: str) -> int | None:
    """
    Try to get float shares from yfinance.
    Returns shares float (int) or None on failure.
    """
    try:
        import yfinance as yf

        info = yf.Ticker(ticker).fast_info
        return getattr(info, "shares", None)
    except Exception:
        return None

# legacy alias
_get_alpaca_client = get_alpaca_client
