"""Five-pillar evaluation for every raw gapper."""

import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def get_alpaca_client():
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.trading.client import TradingClient
    key = os.environ["ALPACA_API_KEY"]
    secret = os.environ["ALPACA_SECRET_KEY"]
    return StockHistoricalDataClient(key, secret), TradingClient(key, secret, paper=True)


def get_bars(api, ticker: str, limit: int = 120) -> pd.DataFrame:
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    try:
        now = datetime.now(ET)
        request = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Minute,
            start=now - timedelta(minutes=limit + 10),
            end=now,
            feed="iex",
        )
        df = api.get_stock_bars(request).df
        if df.empty:
            return pd.DataFrame()
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(ticker, level="symbol")
        if getattr(df.index, "tz", None) is not None:
            df.index = df.index.tz_convert(ET)
        df.columns = [column.capitalize() for column in df.columns]
        return df[df.index.date == now.date()].tail(limit)
    except Exception as error:
        print(f"[{ticker}] bars error: {error}")
        return pd.DataFrame()


def get_float(ticker: str) -> int | None:
    """True float from yfinance, with Finviz as a no-key fallback."""
    try:
        import yfinance as yf
        value = yf.Ticker(ticker).info.get("floatShares")
        if value and int(value) > 0:
            print(f"  [{ticker}] Float: {int(value):,} (yfinance)")
            return int(value)
    except Exception as error:
        print(f"  [{ticker}] yfinance float failed: {error}")

    try:
        from finvizfinance.quote import finvizfinance
        data = finvizfinance(ticker).ticker_fundament()
        raw = str(data.get("Shs Float") or data.get("Float") or "").strip().upper()
        if raw.endswith("M"):
            value = int(float(raw[:-1]) * 1_000_000)
        elif raw.endswith("K"):
            value = int(float(raw[:-1]) * 1_000)
        elif raw.replace(".", "", 1).isdigit():
            value = int(float(raw))
        else:
            value = 0
        if value > 0:
            print(f"  [{ticker}] Float: {value:,} (Finviz)")
            return value
    except Exception as error:
        print(f"  [{ticker}] Finviz float failed: {error}")

    print(f"  [{ticker}] Float: unknown (all sources failed)")
    return None


def get_relative_volume(api, ticker: str, current_volume: int | None = None) -> tuple[float | None, str]:
    """Calculate RVOL from current intraday volume versus historical daily volume."""
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    data_client, _ = api
    current_volume = int(current_volume or 0)
    try:
        now = datetime.now(ET)
        request = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Day,
            start=now - timedelta(days=90),
            end=now,
            feed="iex",
        )
        history = data_client.get_stock_bars(request).df
        if isinstance(history.index, pd.MultiIndex):
            history = history.xs(ticker, level="symbol")
        if history.empty or "volume" not in history.columns:
            return None, "no historical daily volume"
        daily = history["volume"].dropna().astype(float)
        if len(daily) > 1:
            daily = daily.iloc[:-1]
        baseline = float(daily.tail(20).mean()) if not daily.empty else 0.0
        if baseline <= 0 or current_volume <= 0:
            return None, "missing current volume or historical baseline"
        return round(current_volume / baseline, 2), "current volume / 20-day average daily volume"
    except Exception as error:
        print(f"[{ticker}] relative volume error: {error}")
        return None, f"calculation error: {error}"


def evaluate_ticker(api, ticker: str, raw_hit: dict | None = None, min_price: float = 2.0, max_price: float = 20.0, min_gap_pct: float = 0.10, min_rel_vol: float = 5.0, max_float: int = 20_000_000, min_total_vol: int = 100_000, float_shares: int | None = None) -> dict:
    """Evaluate all five pillars while retaining raw screener values as fallback."""
    raw_hit = raw_hit or {}
    bars = get_bars(api[0], ticker)
    price = float(raw_hit["price"]) if raw_hit.get("price") is not None else None
    gap_pct = float(raw_hit["gap_pct"]) if raw_hit.get("gap_pct") is not None else None
    total_vol = int(raw_hit.get("today_vol", 0)) or None
    if not bars.empty and len(bars) >= 3:
        price = float(bars["Close"].iloc[-1])
        total_vol = int(bars["Volume"].sum())

    rel_vol, rel_vol_reason = get_relative_volume(api, ticker, total_vol)
    checks = {
        "gap": None if gap_pct is None else gap_pct >= min_gap_pct * 100,
        "price": None if price is None else min_price <= price <= max_price,
        "rel_vol": None if rel_vol is None else rel_vol >= min_rel_vol,
        "volume": None if total_vol is None else total_vol >= min_total_vol,
        "float": None if float_shares is None else float_shares <= max_float,
    }
    result = {
        "ticker": ticker,
        "price": round(price, 2) if price is not None else None,
        "gap_pct": round(gap_pct, 1) if gap_pct is not None else None,
        "rel_vol": rel_vol,
        "total_vol": total_vol,
        "float": int(float_shares) if float_shares is not None else "unknown",
        "score": sum(value is True for value in checks.values()),
        "pillars": {key: "UNKNOWN" if value is None else ("PASS" if value else "FAIL") for key, value in checks.items()},
        "pillar_details": {
            "gap": f"{gap_pct:.1f}% >= {min_gap_pct * 100:.1f}%" if gap_pct is not None else "unavailable",
            "price": f"${price:.2f} in ${min_price:.2f}-${max_price:.2f}" if price is not None else "unavailable",
            "rel_vol": f"{rel_vol:.2f}x >= {min_rel_vol:.1f}x ({rel_vol_reason})" if rel_vol is not None else f"unavailable: {rel_vol_reason}",
            "volume": f"{total_vol:,} >= {min_total_vol:,}" if total_vol is not None else "unavailable",
            "float": f"{int(float_shares):,} <= {max_float:,}" if float_shares is not None else "unavailable: no free float source returned data",
        },
        "bars": bars,
        "prior_close": raw_hit.get("prev_close"),
    }
    return result


_get_alpaca_client = get_alpaca_client
_get_float_yfinance = get_float
