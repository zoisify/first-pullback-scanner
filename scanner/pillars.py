"""
scanner/pillars.py

The 5-pillar universe filter, scored per ticker.
Uses Alpaca for real-time bars and quote data.
"""

from dotenv import load_dotenv
load_dotenv()

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import alpaca_trade_api as tradeapi
import pandas as pd

ET = ZoneInfo("America/New_York")


def _get_alpaca_client() -> tradeapi.REST:
    """
    Build an Alpaca REST client using environment variables.

    Preferred env vars (what GitHub Actions and .env should set):
      - APCA_API_KEY_ID
      - APCA_API_SECRET_KEY
      - APCA_API_BASE_URL  (optional, defaults to paper)

    Fallbacks for local setups:
      - ALPACA_API_KEY
      - ALPACA_SECRET_KEY
      - ALPACA_BASE_URL
    """
    key = os.environ.get("APCA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY")
    secret = os.environ.get("APCA_API_SECRET_KEY") or os.environ.get("ALPACA_SECRET_KEY")
    base_url = (
        os.environ.get("APCA_API_BASE_URL")
        or os.environ.get("ALPACA_BASE_URL")
        or "https://paper-api.alpaca.markets"
    )

    print(f"[DEBUG] Alpaca base_url={base_url}, key_present={bool(key)}, secret_present={bool(secret)}")

    return tradeapi.REST(
        key_id=key,
        secret_key=secret,
        base_url=base_url,
        api_version="v2",
    )


def get_bars(api: tradeapi.REST, ticker: str, limit: int = 60) -> pd.DataFrame:
    """
    Fetch 1-minute bars for a ticker.

    Uses Alpaca's default feed (no explicit 'iex'), which is safer in CI.
    """
    try:
        bars = api.get_bars(
            ticker,
            "1Min",
            limit=limit,
            adjustment="raw",
        ).df

        if bars.empty:
            return pd.DataFrame()

        bars.index = bars.index.tz_convert(ET)
        bars.columns = [c.capitalize() for c in bars.columns]
        return bars
    except Exception as e:
        print(f"[{ticker}] bars error: {repr(e)}")
        return pd.DataFrame()


def get_asset_info(api: tradeapi.REST, ticker: str) -> dict:
    try:
        asset = api.get_asset(ticker)
        return {"tradable": asset.tradable, "fractionable": asset.fractionable}
    except Exception:
        return {}


def _get_float_yfinance(ticker: str) -> int | None:
    try:
        import yfinance as yf

        info = yf.Ticker(ticker).fast_info
        return getattr(info, "shares", None)
    except Exception:
        return None


def score_ticker(
    api: tradeapi.REST,
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

    Returns a dict with metadata if it passes, or None if it fails / not enough data.
    """

    bars = get_bars(api, ticker, limit=120)
    if bars.empty or len(bars) < 3:
        return None

    last_price = bars["Close"].iloc[-1]
    open_price = bars["Open"].iloc[0]
    total_vol = bars["Volume"].sum()
    elapsed_min = len(bars)

    # Prior close for gap %
    try:
        prev_bars = api.get_bars(
            ticker,
            "1Day",
            limit=2,
            adjustment="raw",
        ).df
        prior_close = prev_bars["close"].iloc[-2] if len(prev_bars) >= 2 else open_price
    except Exception:
        prior_close = open_price

    gap_pct = (open_price - prior_close) / prior_close if prior_close else 0.0

    # Relative volume
    try:
        hist = api.get_bars(
            ticker,
            "1Day",
            limit=10,
            adjustment="raw",
        ).df
        avg_daily_vol = hist["volume"].mean() if not hist.empty else total_vol
    except Exception:
        avg_daily_vol = total_vol

    expected_vol = avg_daily_vol * (elapsed_min / 390)
    rel_vol = total_vol / expected_vol if expected_vol > 0 else 0.0

    float_shares = _get_float_yfinance(ticker)

    pillar_results = {
        "gap": gap_pct >= min_gap_pct,
        "price": min_price <= last_price <= max_price,
        "rel_vol": rel_vol >= min_rel_vol,
        "volume": total_vol >= min_total_vol,
        "float": True if float_shares is None else (float_shares <= max_float),
    }

    definitive = {k: v for k, v in pillar_results.items() if v is not None}
    score = sum(definitive.values())
    unknowns = len(pillar_results) - len(definitive)

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
        "bars": bars,
        "prior_close": prior_close,
    }


def get_alpaca_client() -> tradeapi.REST:
    """Public helper to get the Alpaca client."""
    return _get_alpaca_client()