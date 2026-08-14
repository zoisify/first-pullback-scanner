"""
scanner/pillars.py

The 5-pillar universe filter from the transcript, scored per ticker.
Uses alpaca-py (new SDK) for real-time bars and quote data.
Float lookup via Financial Modeling Prep (FMP) free API.

Ross's pillars:
1. Relative volume >= 5x
2. Gap >= 10% from prior close
3. Price between $2 and $20
4. Float <= 20 million shares
5. Total volume >= 100K
"""

import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def get_alpaca_client():
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.trading.client import TradingClient

    api_key = os.environ["ALPACA_API_KEY"]
    secret_key = os.environ["ALPACA_SECRET_KEY"]

    data_client = StockHistoricalDataClient(api_key, secret_key)
    trading_client = TradingClient(api_key, secret_key, paper=True)

    return data_client, trading_client


def get_bars(api, ticker: str, limit: int = 60) -> pd.DataFrame:
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

        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(ticker, level="symbol")

        df.index = df.index.tz_convert(ET)
        df.columns = [c.capitalize() for c in df.columns]

        today = datetime.now(ET).date()
        df = df[df.index.date == today]

        return df.tail(limit)

    except Exception as e:
        print(f"[{ticker}] bars error: {e}")
        return pd.DataFrame()


def get_asset_info(api, ticker: str) -> dict:
    try:
        asset = api.get_asset(ticker)
        return {"tradable": asset.tradable, "fractionable": asset.fractionable}
    except Exception:
        return {}


def get_float_fmp(ticker: str) -> int | None:
    """
    Get float shares from Financial Modeling Prep free API.
    Called only on the single #1 gapper so no rate limit issues.
    Returns float share count or None on failure.
    """
    try:
        api_key = os.environ.get("FMP_API_KEY", "")
        if not api_key:
            print(f" [FMP] No FMP_API_KEY set - skipping float lookup")
            return None

        url = f"https://financialmodelingprep.com/stable/shares-float?symbol={ticker}&apikey={api_key}"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()

        if isinstance(data, list) and len(data) > 0:
            float_shares = data[0].get("floatShares")
            if float_shares:
                print(f" [FMP] {ticker} float: {int(float_shares):,}")
                return int(float_shares)

        # Fallback: profile endpoint
        url2 = f"https://financialmodelingprep.com/stable/profile?symbol={ticker}&apikey={api_key}"
        r2 = requests.get(url2, timeout=10)
        r2.raise_for_status()
        data2 = r2.json()

        if isinstance(data2, list) and len(data2) > 0:
            shares = data2[0].get("floatShares") or data2[0].get("sharesOutstanding")
            if shares:
                print(f" [FMP] {ticker} shares (profile): {int(shares):,}")
                return int(shares)

        print(f" [FMP] No float data found for {ticker}")
        return None

    except Exception as e:
        print(f" [FMP] Float lookup failed for {ticker}: {e}")
        return None


def score_ticker(
    api,
    ticker: str,
    min_price: float = 2.0,
    max_price: float = 20.0,
    min_gap_pct: float = 0.10,
    min_rel_vol: float = 5.0,
    max_float: int = 20_000_000,
    min_total_vol: int = 100_000,
    use_fmp_float: bool = False,
) -> dict | None:
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

    # Prior close
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

    # Float - only call FMP for the final #1 stock
    if use_fmp_float:
        float_shares = get_float_fmp(ticker)
    else:
        float_shares = None

    # Score pillars
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
            k: ("OK" if v else ("?" if v is None else "FAIL"))
            for k, v in pillar_results.items()
        },
        "bars": bars,
        "prior_close": prior_close,
    }


# legacy alias
_get_alpaca_client = get_alpaca_client
