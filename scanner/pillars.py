"""
scanner/pillars.py

Five-pillar evaluation for every raw gapper.
FMP float data remains optional and is normally requested only for the
selected candidate to avoid unnecessary API usage.
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
        df.index = df.index.tz_convert(ET)
        df.columns = [c.capitalize() for c in df.columns]
        return df[df.index.date == now.date()].tail(limit)
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
    try:
        api_key = os.environ.get("FMP_API_KEY", "")
        if not api_key:
            print(" [FMP] No FMP_API_KEY set - skipping float lookup")
            return None

        url = f"https://financialmodelingprep.com/stable/shares-float?symbol={ticker}&apikey={api_key}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if isinstance(data, list) and data:
            value = data[0].get("floatShares")
            if value:
                print(f" [FMP] {ticker} float: {int(value):,}")
                return int(value)

        fallback = f"https://financialmodelingprep.com/stable/profile?symbol={ticker}&apikey={api_key}"
        response = requests.get(fallback, timeout=10)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list) and data:
            value = data[0].get("floatShares") or data[0].get("sharesOutstanding")
            if value:
                print(f" [FMP] {ticker} shares (profile): {int(value):,}")
                return int(value)

        print(f" [FMP] No float data found for {ticker}")
    except Exception as e:
        print(f" [FMP] Float lookup failed for {ticker}: {e}")
    return None


def evaluate_ticker(
    api,
    ticker: str,
    min_price: float = 2.0,
    max_price: float = 20.0,
    min_gap_pct: float = 0.10,
    min_rel_vol: float = 5.0,
    max_float: int = 20_000_000,
    min_total_vol: int = 100_000,
    float_shares: int | None = None,
) -> dict:
    """Return full five-pillar diagnostics even when the ticker fails."""
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    result = {
        "ticker": ticker,
        "price": None,
        "gap_pct": None,
        "rel_vol": None,
        "total_vol": None,
        "float": float_shares if float_shares is not None else "unknown",
        "score": 0,
        "pillars": {
            "gap": "UNKNOWN",
            "price": "UNKNOWN",
            "rel_vol": "UNKNOWN",
            "volume": "UNKNOWN",
            "float": "UNKNOWN" if float_shares is None else "FAIL",
        },
        "pillar_details": {},
        "bars": pd.DataFrame(),
    }

    data_client, _ = api
    bars = get_bars(data_client, ticker, limit=120)
    result["bars"] = bars
    if bars.empty or len(bars) < 3:
        result["pillar_details"]["data"] = "Insufficient intraday bars"
        return result

    last_price = float(bars["Close"].iloc[-1])
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
        prior_close = float(previous["close"].iloc[-2]) if len(previous) >= 2 else open_price
    except Exception:
        prior_close = open_price

    gap_pct = ((open_price - prior_close) / prior_close) if prior_close else 0.0

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
        average_volume = float(total_vol)

    expected_volume = average_volume * (elapsed_min / 390)
    rel_vol = total_vol / expected_volume if expected_volume > 0 else 0.0

    checks = {
        "gap": gap_pct >= min_gap_pct,
        "price": min_price <= last_price <= max_price,
        "rel_vol": rel_vol >= min_rel_vol,
        "volume": total_vol >= min_total_vol,
        "float": None if float_shares is None else float_shares <= max_float,
    }

    result.update({
        "price": round(last_price, 2),
        "gap_pct": round(gap_pct * 100, 1),
        "rel_vol": round(rel_vol, 1),
        "total_vol": total_vol,
        "prior_close": round(prior_close, 4),
        "float": int(float_shares) if float_shares is not None else "unknown",
    })
    result["pillars"] = {
        key: "UNKNOWN" if value is None else ("PASS" if value else "FAIL")
        for key, value in checks.items()
    }
    result["score"] = sum(value is True for value in checks.values())
    result["pillar_details"] = {
        "gap": f"{result['gap_pct']}% >= {min_gap_pct * 100:.1f}%",
        "price": f"${result['price']:.2f} in ${min_price:.2f}-${max_price:.2f}",
        "rel_vol": f"{result['rel_vol']:.1f}x >= {min_rel_vol:.1f}x",
        "volume": f"{result['total_vol']:,} >= {min_total_vol:,}",
        "float": (
            "unknown until FMP lookup"
            if float_shares is None
            else f"{int(float_shares):,} <= {max_float:,}"
        ),
    }
    return result


def score_ticker(api, ticker: str, **kwargs) -> dict | None:
    """Compatibility wrapper returning only candidates passing >=4 pillars."""
    result = evaluate_ticker(api, ticker, **kwargs)
    known = [value for value in result["pillars"].values() if value != "UNKNOWN"]
    if result["score"] >= 4 or (result["score"] == 3 and len(known) < 5):
        return result
    return None


_get_alpaca_client = get_alpaca_client
