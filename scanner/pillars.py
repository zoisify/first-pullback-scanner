"""Universe filters and Alpaca market-data helpers."""

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

ET = ZoneInfo("America/New_York")
DATA_FEED = os.getenv("ALPACA_DATA_FEED", "iex")


def get_alpaca_client():
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.trading.client import TradingClient

    api_key = os.environ["ALPACA_API_KEY"]
    secret_key = os.environ["ALPACA_SECRET_KEY"]
    return (
        StockHistoricalDataClient(api_key, secret_key),
        TradingClient(api_key, secret_key, paper=True),
    )


def get_bars(api, ticker: str, limit: int = 60) -> pd.DataFrame:
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    try:
        now = datetime.now(ET)
        response = api.get_stock_bars(StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Minute,
            start=now - timedelta(minutes=limit + 10),
            end=now,
            feed=DATA_FEED,
        ))
        frame = response.df
        if frame.empty:
            return pd.DataFrame()
        if isinstance(frame.index, pd.MultiIndex):
            frame = frame.xs(ticker, level="symbol")
        if frame.index.tz is not None:
            frame.index = frame.index.tz_convert(ET)
        frame.columns = [column.capitalize() for column in frame.columns]
        return frame[frame.index.date == now.date()].tail(limit)
    except Exception as exc:
        print(f"[{ticker}] bars error: {exc}")
        return pd.DataFrame()


def get_asset_info(api, ticker: str) -> dict:
    try:
        asset = api.get_asset(ticker)
        return {"tradable": asset.tradable, "fractionable": asset.fractionable}
    except Exception:
        return {}


def score_ticker(api, ticker: str, min_price: float = 2.0, max_price: float = 20.0,
                 min_gap_pct: float = 0.10, min_rel_vol: float = 5.0,
                 max_float: int = 20_000_000, min_total_vol: int = 100_000) -> dict | None:
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    data_client, _ = api
    bars = get_bars(data_client, ticker, limit=120)
    if bars.empty or len(bars) < 3:
        return None
    last_price = bars["Close"].iloc[-1]
    open_price = bars["Open"].iloc[0]
    total_vol = bars["Volume"].sum()
    elapsed_min = len(bars)

    try:
        now = datetime.now(ET)
        prev = data_client.get_stock_bars(StockBarsRequest(
            symbol_or_symbols=ticker, timeframe=TimeFrame.Day,
            start=now - timedelta(days=5), end=now, feed=DATA_FEED,
        )).df
        if isinstance(prev.index, pd.MultiIndex):
            prev = prev.xs(ticker, level="symbol")
        prior_close = prev["close"].iloc[-2] if len(prev) >= 2 else open_price
    except Exception:
        prior_close = open_price
    gap_pct = (open_price - prior_close) / prior_close if prior_close else 0

    try:
        now = datetime.now(ET)
        hist = data_client.get_stock_bars(StockBarsRequest(
            symbol_or_symbols=ticker, timeframe=TimeFrame.Day,
            start=now - timedelta(days=15), end=now, feed=DATA_FEED,
        )).df
        if isinstance(hist.index, pd.MultiIndex):
            hist = hist.xs(ticker, level="symbol")
        avg_daily_vol = hist["volume"].mean() if not hist.empty else total_vol
    except Exception:
        avg_daily_vol = total_vol
    expected_vol = avg_daily_vol * (elapsed_min / 390)
    rel_vol = total_vol / expected_vol if expected_vol > 0 else 0

    float_shares = _get_float_yfinance(ticker)
    pillars = {
        "gap": gap_pct >= min_gap_pct,
        "price": min_price <= last_price <= max_price,
        "rel_vol": rel_vol >= min_rel_vol,
        "volume": total_vol >= min_total_vol,
        "float": (float_shares <= max_float) if float_shares else None,
    }
    known = {key: value for key, value in pillars.items() if value is not None}
    score = sum(known.values())
    unknowns = len(pillars) - len(known)
    if not (score >= 4 or (score == 3 and unknowns >= 1)):
        return None
    return {
        "ticker": ticker, "price": round(last_price, 2),
        "gap_pct": round(gap_pct * 100, 1), "rel_vol": round(rel_vol, 1),
        "total_vol": int(total_vol),
        "float": int(float_shares) if float_shares else "unknown",
        "score": score,
        "pillars": {key: ("✓" if value else ("?" if value is None else "✗")) for key, value in pillars.items()},
        "bars": bars, "prior_close": prior_close,
    }


def _get_float_yfinance(ticker: str) -> int | None:
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        return info.get("floatShares") or info.get("sharesOutstanding")
    except Exception:
        return None


_get_alpaca_client = get_alpaca_client
