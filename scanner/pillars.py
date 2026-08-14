"""Five-pillar evaluation with explicit data-source diagnostics."""

from datetime import datetime, timedelta
import os
import pandas as pd
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def get_float(ticker: str) -> int | None:
    """Return SEC public float, or explicitly labelled shares-outstanding proxy."""
    try:
        from edgar import Company
        company = Company(ticker)
        value = company.public_float
        if value and int(value) > 0:
            print(f" [{ticker}] Float source: SEC EDGAR public float ({int(value):,})")
            return int(value)
        value = company.shares_outstanding
        if value and int(value) > 0:
            print(f" [{ticker}] Float source: SEC EDGAR shares outstanding proxy ({int(value):,})")
            return int(value)
    except Exception as error:
        print(f" [{ticker}] Float source: unavailable ({error})")
    return None


def get_relative_volume(api, ticker: str, current_volume: int, now=None):
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    now = now or datetime.now(ET)
    try:
        request = StockBarsRequest(symbol_or_symbols=ticker, timeframe=TimeFrame.Day, start=now - timedelta(days=90), end=now, feed="iex")
        history = api.get_stock_bars(request).df
        if isinstance(history.index, pd.MultiIndex): history = history.xs(ticker, level="symbol")
        if history.empty or "volume" not in history.columns: return None, "IEX daily history unavailable"
        daily = history["volume"].dropna().astype(float)
        if len(daily) > 1: daily = daily.iloc[:-1]
        baseline = float(daily.tail(20).mean())
        if baseline <= 0: return None, "IEX historical baseline unavailable"
        return round(current_volume / baseline, 2), "IEX pre-market volume / 20-day daily IEX baseline estimate"
    except Exception as error:
        return None, f"IEX relative-volume estimate unavailable: {error}"
