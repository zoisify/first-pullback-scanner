"""
scanner/pillars.py

The 5-pillar universe filter from the transcript, scored per ticker.
Uses alpaca-py (new SDK) for real-time bars and quote data.

Ross's pillars (from transcript):
1. Relative volume >= 5x (he mentions 5-10x sweet spot, >20x exceptional)
2. Gap / move >= 10% from prior close
3. Price between $2 and $20
4. Float <= 20 million shares
5. Total volume >= 1M (soft)
"""

import os
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def get_alpaca_client():
    """Returns an Alpaca REST client using env vars set by GitHub Actions secrets."""
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.trading.client import TradingClient

    api_key = os.environ["ALPACA_API_KEY"]
    secret_key = os.environ["ALPACA_SECRET_KEY"]

    data_client = StockHistoricalDataClient(api_key, secret_key)
    trading_client = TradingClient(api_key, secret_key, paper=True)

    return data_client, trading_client


def get_bars(api, ticker: str, limit: int = 60) -> pd.DataFrame:
    """
    Fetch the last `limit` 1-minute bars for a ticker.
    api should be the data_client (StockHistoricalDataClient).
    Returns a DataFrame with columns Open/High/Low/Close/Volume.
    Returns empty DataFrame on failure.
    """
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    try:
        now = datetime.now(ET)
        start = now - timedelta(minutes=limit + 10)

        request = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Minute,
            start=start,
            end=now,
            feed="iex",
        )

        bars_response = api.get_stock_bars(request)
        df = bars_response.df

        if df.empty:
            return pd.DataFrame()

        # alpaca-py returns a multi-index (symbol, timestamp) — drop symbol level
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(ticker, level="symbol")

        df.index = df.index.tz_convert(ET)
        df.columns = [c.capitalize() for c in df.columns]

        # Keep only today's bars
        today = datetime.now(ET).date()
        df = df[df.index.date == today]

        return df.tail(limit)

    except Exception as e:
        print(f"[{ticker}] bars error: {e}")
        return pd.DataFrame()


def get_asset_info(api, ticker: str) -> dict:
    """
    Fetch static asset info.
    api should be the trading_client here.
    """
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
    api is a tuple: (data_client, trading_client)
    Returns a result dict if it passes >= 4 pillars, else None.
    """
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    data_client, trading_client = api

    bars = get_bars(data_client, ticker, limit=120)
    if bars.empty or len(bars) < 3:
        return None

    last_price = bars["Close"].iloc[-1]
    open_price = bars["Open"].iloc[0]
    total_vol = bars["Volume"].sum()
    elapsed_min = len(bars)

    # Prior close: get yesterday's daily bar
    try:
        now = datetime.now(ET)
        request = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Day,
            start=now - timedelta(days=5),
            end=now,
            feed="iex",
        )
        prev_bars = data_client.get_stock_bars(request).df
        if isinstance(prev_bars.index, pd.MultiIndex):
            prev_bars = prev_bars.xs(ticker, level="symbol")
        prior_close = prev_bars["close"].iloc[-2] if len(prev_bars) >= 2 else open_price
    except Exception:
        prior_close = open_price

    gap_pct = (open_price - prior_close) / prior_close if prior_close else 0

    # Relative volume
    try:
        now = datetime.now(ET)
        request = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Day,
            start=now - timedelta(days=15),
            end=now,
            feed="iex",
        )
        hist = data_client.get_stock_bars(request).df
        if isinstance(hist.index, pd.MultiIndex):
            hist = hist.xs(ticker, level="symbol")
        avg_daily_vol = hist["volume"].mean() if not hist.empty else total_vol
    except Exception:
        avg_daily_vol = total_vol

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
        "float": (float_shares <= max_float) if float_shares else None,
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


def _get_float_yfinance(ticker: str) -> int | None:
    """
    Try to get float shares from yfinance.
    Uses floatShares (actual float) not sharesOutstanding.
    Returns float share count (int) or None on failure.
    """
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        return info.get("floatShares") or info.get("sharesOutstanding")
    except Exception:
        return None


# legacy alias
_get_alpaca_client = get_alpaca_client
