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


def get_float_fmp(ticker: str) -> int | None:
    try:
        key = os.environ.get("FMP_API_KEY", "")
        if not key:
            print(" [FMP] No FMP_API_KEY set")
            return None
        url = f"https://financialmodelingprep.com/stable/shares-float?symbol={ticker}&apikey={key}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list) and data:
            value = data[0].get("floatShares")
            if value:
                print(f" [FMP] {ticker} float: {int(value):,}")
                return int(value)
        fallback = f"https://financialmodelingprep.com/stable/profile?symbol={ticker}&apikey={key}"
        response = requests.get(fallback, timeout=10)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list) and data:
            value = data[0].get("floatShares") or data[0].get("sharesOutstanding")
            if value:
                print(f" [FMP] {ticker} shares: {int(value):,}")
                return int(value)
        print(f" [FMP] No float data found for {ticker}")
    except Exception as error:
        print(f" [FMP] Float lookup failed for {ticker}: {error}")
    return None


def evaluate_ticker(
    api,
    ticker: str,
    raw_hit: dict | None = None,
    min_price: float = 2.0,
    max_price: float = 20.0,
    min_gap_pct: float = 0.10,
    min_rel_vol: float = 5.0,
    max_float: int = 20_000_000,
    min_total_vol: int = 100_000,
    float_shares: int | None = None,
) -> dict:
    """Evaluate all five pillars; raw screener values prevent false UNKNOWN results."""
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    raw_hit = raw_hit or {}
    data_client, _ = api
    bars = get_bars(data_client, ticker)

    price = float(raw_hit["price"]) if raw_hit.get("price") is not None else None
    gap_pct_value = float(raw_hit["gap_pct"]) if raw_hit.get("gap_pct") is not None else None
    total_vol = int(raw_hit.get("today_vol", 0)) or None
    rel_vol = None
    prior_close = raw_hit.get("prev_close")

    if not bars.empty and len(bars) >= 3:
        price = float(bars["Close"].iloc[-1])
        open_price = float(bars["Open"].iloc[0])
        total_vol = int(bars["Volume"].sum())
        elapsed_min = len(bars)
        try:
            now = datetime.now(ET)
            request = StockBarsRequest(
                symbol_or_symbols=ticker,
                timeframe=TimeFrame.Day,
                start=now - timedelta(days=5),
                end=now,
                feed="iex",
            )
            previous = data_client.get_stock_bars(request).df
            if isinstance(previous.index, pd.MultiIndex):
                previous = previous.xs(ticker, level="symbol")
            prior_close = float(previous["close"].iloc[-2]) if len(previous) >= 2 else prior_close
        except Exception:
            pass
        if prior_close:
            gap_pct_value = (open_price - prior_close) / prior_close * 100
        try:
            now = datetime.now(ET)
            request = StockBarsRequest(
                symbol_or_symbols=ticker,
                timeframe=TimeFrame.Day,
                start=now - timedelta(days=15),
                end=now,
                feed="iex",
            )
            history = data_client.get_stock_bars(request).df
            if isinstance(history.index, pd.MultiIndex):
                history = history.xs(ticker, level="symbol")
            average_volume = float(history["volume"].mean()) if not history.empty else float(total_vol)
        except Exception:
            average_volume = float(total_vol or 0)
        expected = average_volume * (elapsed_min / 390)
        rel_vol = total_vol / expected if expected > 0 else None

    checks = {
        "gap": None if gap_pct_value is None else gap_pct_value >= min_gap_pct * 100,
        "price": None if price is None else min_price <= price <= max_price,
        "rel_vol": None if rel_vol is None else rel_vol >= min_rel_vol,
        "volume": None if total_vol is None else total_vol >= min_total_vol,
        "float": None if float_shares is None else float_shares <= max_float,
    }
    result = {
        "ticker": ticker,
        "price": round(price, 2) if price is not None else None,
        "gap_pct": round(gap_pct_value, 1) if gap_pct_value is not None else None,
        "rel_vol": round(rel_vol, 1) if rel_vol is not None else None,
        "total_vol": total_vol,
        "float": int(float_shares) if float_shares is not None else "unknown",
        "score": sum(value is True for value in checks.values()),
        "pillars": {key: "UNKNOWN" if value is None else ("PASS" if value else "FAIL") for key, value in checks.items()},
        "pillar_details": {
            "gap": f"{gap_pct_value:.1f}% >= {min_gap_pct * 100:.1f}%" if gap_pct_value is not None else "unavailable",
            "price": f"${price:.2f} in ${min_price:.2f}-${max_price:.2f}" if price is not None else "unavailable",
            "rel_vol": f"{rel_vol:.1f}x >= {min_rel_vol:.1f}x" if rel_vol is not None else "unavailable: insufficient intraday bars",
            "volume": f"{total_vol:,} >= {min_total_vol:,}" if total_vol is not None else "unavailable",
            "float": f"{int(float_shares):,} <= {max_float:,}" if float_shares is not None else "unavailable: FMP lookup failed",
        },
        "bars": bars,
        "prior_close": prior_close,
    }
    return result


_get_alpaca_client = get_alpaca_client
