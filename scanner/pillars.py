"""Five-pillar diagnostics using current-session metadata."""

import os
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


def get_float(ticker: str) -> int | None:
    try:
        import yfinance as yf
        value = yf.Ticker(ticker).info.get("floatShares")
        if value and int(value) > 0:
            return int(value)
    except Exception as error:
        print(f"[{ticker}] yfinance float failed: {error}")
    try:
        from finvizfinance.quote import finvizfinance
        data = finvizfinance(ticker).ticker_fundament()
        raw = str(data.get("Shs Float") or data.get("Float") or "").strip().upper()
        if raw.endswith("M"):
            return int(float(raw[:-1]) * 1_000_000)
        if raw.endswith("K"):
            return int(float(raw[:-1]) * 1_000)
        if raw.replace(".", "", 1).isdigit():
            return int(float(raw))
    except Exception as error:
        print(f"[{ticker}] Finviz float failed: {error}")
    return None


def get_relative_volume(api, ticker: str, current_volume: int, session_date, now: datetime | None = None):
    """Use comparable daily volume only; pre-market RVOL is unavailable without extended-hours history."""
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    now = now or datetime.now(ET)
    try:
        request = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Day,
            start=now - timedelta(days=90),
            end=now,
            feed="iex",
        )
        history = api.get_stock_bars(request).df
        if isinstance(history.index, pd.MultiIndex):
            history = history.xs(ticker, level="symbol")
        if history.empty or "volume" not in history.columns:
            return None, "no daily history"
        daily = history["volume"].dropna().astype(float)
        if len(daily) > 1:
            daily = daily.iloc[:-1]
        baseline = float(daily.tail(20).mean()) if not daily.empty else 0.0
        if baseline <= 0:
            return None, "zero historical baseline"
        return round(current_volume / baseline, 2), "current pre-market volume / 20-day full-day average (diagnostic estimate)"
    except Exception as error:
        return None, f"calculation error: {error}"


def evaluate_ticker(api, ticker: str, raw_hit: dict | None = None, **kwargs) -> dict:
    raw_hit = raw_hit or {}
    session_date = datetime.fromisoformat(raw_hit["latest_trade_at"]).date() if raw_hit.get("latest_trade_at") else datetime.now(ET).date()
    float_shares = kwargs.get("float_shares")
    current_volume = int(raw_hit.get("today_vol") or 0)
    rel_vol, rel_vol_reason = get_relative_volume(api[0], ticker, current_volume, session_date)
    price = float(raw_hit["price"]) if raw_hit.get("price") is not None else None
    gap_pct = float(raw_hit["gap_pct"]) if raw_hit.get("gap_pct") is not None else None
    checks = {
        "gap": None if gap_pct is None else gap_pct >= 10.0,
        "price": None if price is None else 2.0 <= price <= 20.0,
        "rel_vol": None if rel_vol is None else rel_vol >= 5.0,
        "volume": None if current_volume <= 0 else current_volume >= 100_000,
        "float": None if float_shares is None else float_shares <= 20_000_000,
    }
    return {
        "ticker": ticker,
        "price": round(price, 2) if price is not None else None,
        "gap_pct": round(gap_pct, 1) if gap_pct is not None else None,
        "rel_vol": rel_vol,
        "total_vol": current_volume,
        "float": int(float_shares) if float_shares is not None else "unknown",
        "score": sum(value is True for value in checks.values()),
        "pillars": {key: "UNKNOWN" if value is None else ("PASS" if value else "FAIL") for key, value in checks.items()},
        "pillar_details": {
            "gap": f"{gap_pct:.1f}% versus previous regular close" if gap_pct is not None else "unavailable",
            "price": f"${price:.2f} in $2.00-$20.00" if price is not None else "unavailable",
            "rel_vol": f"{rel_vol:.2f}x >= 5.0x ({rel_vol_reason})" if rel_vol is not None else f"UNKNOWN ({rel_vol_reason})",
            "volume": f"{current_volume:,} from {raw_hit.get('premarket_start', '04:00 ET')} onward",
            "float": f"{int(float_shares):,} <= 20,000,000" if float_shares is not None else "unknown",
        },
        "session": {
            "latest_trade_at": raw_hit.get("latest_trade_at"),
            "premarket_start": raw_hit.get("premarket_start"),
            "reference_session": raw_hit.get("reference_session"),
            "gap_method": raw_hit.get("gap_method"),
        },
    }


_get_alpaca_client = get_alpaca_client
