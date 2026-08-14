"""Five-pillar evaluation with explicit pre-market metadata and SEC float."""

import os
from datetime import datetime, timedelta
import pandas as pd
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def get_alpaca_client():
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.trading.client import TradingClient
    key, secret = os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"]
    return StockHistoricalDataClient(key, secret), TradingClient(key, secret, paper=True)


def get_float(ticker: str) -> int | None:
    """Reported public float from SEC EDGAR; outstanding shares are a labelled proxy."""
    try:
        from edgar import Company
        company = Company(ticker)
        value = company.public_float
        if value and int(value) > 0:
            print(f"  [{ticker}] Float: {int(value):,} (SEC EDGAR)")
            return int(value)
        value = company.shares_outstanding
        if value and int(value) > 0:
            print(f"  [{ticker}] Float proxy: {int(value):,} (SEC EDGAR shares outstanding)")
            return int(value)
    except Exception as error:
        print(f"  [{ticker}] edgartools float failed: {error}")
    return None


def get_relative_volume(api, ticker, current_volume, now=None):
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    now = now or datetime.now(ET)
    try:
        request = StockBarsRequest(symbol_or_symbols=ticker, timeframe=TimeFrame.Day, start=now - timedelta(days=90), end=now, feed="iex")
        history = api.get_stock_bars(request).df
        if isinstance(history.index, pd.MultiIndex):
            history = history.xs(ticker, level="symbol")
        if history.empty or "volume" not in history.columns:
            return None, "no daily history"
        daily = history["volume"].dropna().astype(float)
        if len(daily) > 1:
            daily = daily.iloc[:-1]
        baseline = float(daily.tail(20).mean())
        if baseline <= 0:
            return None, "zero historical baseline"
        return round(current_volume / baseline, 2), "pre-market volume / 20-day daily baseline (estimate)"
    except Exception as error:
        return None, f"calculation error: {error}"


def evaluate_ticker(api, ticker, raw_hit=None, **kwargs):
    raw_hit = raw_hit or {}
    float_shares = kwargs.get("float_shares")
    volume = int(raw_hit.get("today_vol") or 0)
    rel_vol, rel_reason = get_relative_volume(api[0], ticker, volume)
    price = float(raw_hit["price"]) if raw_hit.get("price") is not None else None
    gap = float(raw_hit["gap_pct"]) if raw_hit.get("gap_pct") is not None else None
    checks = {"gap": gap is not None and gap >= 10, "price": price is not None and 2 <= price <= 20, "rel_vol": rel_vol is not None and rel_vol >= 5, "volume": volume >= 100000, "float": None if float_shares is None else float_shares <= 20000000}
    return {
        "ticker": ticker, "price": round(price, 2) if price is not None else None, "gap_pct": round(gap, 1) if gap is not None else None, "rel_vol": rel_vol, "total_vol": volume, "float": int(float_shares) if float_shares is not None else "unknown", "score": sum(value is True for value in checks.values()), "pillars": {key: "UNKNOWN" if value is None else ("PASS" if value else "FAIL") for key, value in checks.items()}, "pillar_details": {"gap": f"{gap:.1f}% versus previous regular close" if gap is not None else "unavailable", "price": f"${price:.2f} in $2-$20" if price is not None else "unavailable", "rel_vol": f"{rel_vol:.2f}x >= 5x ({rel_reason})" if rel_vol is not None else f"UNKNOWN ({rel_reason})", "volume": f"{volume:,} from {raw_hit.get('premarket_start')} to {raw_hit.get('premarket_end')}", "float": f"{int(float_shares):,} <= 20,000,000" if float_shares is not None else "unknown"}, "session": {key: raw_hit.get(key) for key in ("latest_trade_at", "premarket_start", "premarket_end", "reference_close_at", "reference_session", "gap_method")}


_get_alpaca_client = get_alpaca_client
