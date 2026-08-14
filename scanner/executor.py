"""Order execution layer for Alpaca paper trading."""

import os
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest, StopOrderRequest

from .quote_validation import validate_quote

QUOTE_FEED = os.getenv("ALPACA_QUOTE_FEED", "iex")
MAX_SPREAD_PCT = float(os.getenv("MAX_SPREAD_PCT", "1.0"))
MAX_QUOTE_AGE_SECONDS = float(os.getenv("MAX_QUOTE_AGE_SECONDS", "120"))


def get_trading_client() -> TradingClient:
    return TradingClient(
        api_key=os.environ["ALPACA_API_KEY"],
        secret_key=os.environ["ALPACA_SECRET_KEY"],
        paper=True,
    )


def _latest_quote(ticker: str):
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockLatestQuoteRequest

    data_client = StockHistoricalDataClient(
        os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"]
    )
    request = StockLatestQuoteRequest(
        symbol_or_symbols=ticker,
        feed=QUOTE_FEED,
    )
    return data_client.get_stock_latest_quote(request)[ticker]


def check_spread(ticker: str, max_spread_pct: float = MAX_SPREAD_PCT) -> bool:
    """Return True only for a fresh, valid, sufficiently tight quote."""
    try:
        quote = _latest_quote(ticker)
        check = validate_quote(
            quote.bid_price,
            quote.ask_price,
            max_spread_pct=max_spread_pct,
            quote_timestamp=getattr(quote, "timestamp", None),
            max_age_seconds=MAX_QUOTE_AGE_SECONDS,
        )
        if not check.valid:
            print(
                f" [{ticker}] Quote rejected: {check.reason} "
                f"(bid={check.bid:.2f}, ask={check.ask:.2f}, "
                f"spread={check.spread_pct:.3f}%)"
            )
            return False
        print(
            f" [{ticker}] Spread OK: {check.spread_pct:.3f}% "
            f"(bid={check.bid:.2f}, ask={check.ask:.2f}, feed={QUOTE_FEED})"
        )
        return True
    except Exception as exc:
        print(f" [{ticker}] Quote check failed: {exc} — rejecting trade")
        return False


def submit_entry_order(signal, account_size: float = 65_000, risk_pct: float = 0.01) -> Optional[dict]:
    try:
        if not check_spread(signal.ticker):
            return None
        client = get_trading_client()
        risk_per_share = signal.price - signal.stop
        if risk_per_share <= 0:
            print(f" [{signal.ticker}] Invalid risk: entry={signal.price}, stop={signal.stop}")
            return None
        shares = int((account_size * risk_pct) / risk_per_share)
        if shares <= 0:
            print(f" [{signal.ticker}] Position size too small")
            return None
        buy_resp = client.submit_order(order_data=MarketOrderRequest(
            symbol=signal.ticker, qty=shares, side=OrderSide.BUY, time_in_force=TimeInForce.DAY
        ))
        print(f" BUY ORDER: {buy_resp.id} — {shares}x {signal.ticker}")
        stop_resp = client.submit_order(order_data=StopOrderRequest(
            symbol=signal.ticker, qty=shares, side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY, stop_price=round(signal.stop, 2)
        ))
        print(f" STOP ORDER: {stop_resp.id} — stop at ${signal.stop}")
        return {"order_id": buy_resp.id, "stop_order_id": stop_resp.id, "shares": shares, "symbol": signal.ticker}
    except Exception as exc:
        print(f" [ERROR] Entry order failed for {signal.ticker}: {exc}")
        return None


def submit_scalein_order(signal, account_size: float = 65_000, risk_pct: float = 0.005,
                         old_stop_order_id: Optional[str] = None, total_shares_held: int = 0) -> Optional[dict]:
    try:
        if not check_spread(signal.ticker):
            return None
        client = get_trading_client()
        risk_per_share = signal.price - signal.stop
        if risk_per_share <= 0:
            return None
        shares_to_add = int((account_size * risk_pct) / risk_per_share)
        if shares_to_add <= 0:
            print(f" [{signal.ticker}] Scale-in size too small")
            return None
        if old_stop_order_id:
            try:
                client.cancel_order_by_id(old_stop_order_id)
            except Exception:
                pass
        buy_resp = client.submit_order(order_data=MarketOrderRequest(
            symbol=signal.ticker, qty=shares_to_add, side=OrderSide.BUY, time_in_force=TimeInForce.DAY
        ))
        total_shares = total_shares_held + shares_to_add
        stop_resp = client.submit_order(order_data=StopOrderRequest(
            symbol=signal.ticker, qty=total_shares, side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY, stop_price=round(signal.stop, 2)
        ))
        print(f" SCALE-IN ORDER: {buy_resp.id} — +{shares_to_add}x {signal.ticker}")
        print(f" NEW STOP ORDER: {stop_resp.id} — {total_shares} shares @ ${signal.stop}")
        return {"order_id": buy_resp.id, "stop_order_id": stop_resp.id, "shares_added": shares_to_add, "symbol": signal.ticker}
    except Exception as exc:
        print(f" [ERROR] Scale-in failed for {signal.ticker}: {exc}")
        return None


def submit_exit_order(signal, current_qty: int, stop_order_id: Optional[str] = None) -> Optional[dict]:
    try:
        client = get_trading_client()
        if current_qty <= 0:
            return None
        if stop_order_id:
            try:
                client.cancel_order_by_id(stop_order_id)
            except Exception:
                pass
        resp = client.submit_order(order_data=MarketOrderRequest(
            symbol=signal.ticker, qty=current_qty, side=OrderSide.SELL, time_in_force=TimeInForce.DAY
        ))
        print(f" SELL ORDER: {resp.id} — {current_qty}x {signal.ticker}")
        return {"order_id": resp.id, "shares": current_qty, "symbol": signal.ticker}
    except Exception as exc:
        print(f" [ERROR] Exit order failed for {signal.ticker}: {exc}")
        return None


def update_trailing_stop(ticker: str, current_qty: int, old_stop_order_id: Optional[str], new_stop_price: float) -> Optional[str]:
    try:
        client = get_trading_client()
        if old_stop_order_id:
            try:
                client.cancel_order_by_id(old_stop_order_id)
            except Exception:
                pass
        resp = client.submit_order(order_data=StopOrderRequest(
            symbol=ticker, qty=current_qty, side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY, stop_price=round(new_stop_price, 2)
        ))
        print(f" TRAILING STOP updated: ${new_stop_price} ({ticker})")
        return resp.id
    except Exception as exc:
        print(f" [WARN] Trailing stop update failed for {ticker}: {exc}")
        return old_stop_order_id


def get_current_position_qty(ticker: str) -> int:
    try:
        position = get_trading_client().get_open_position(ticker)
        return int(float(position.qty)) if position else 0
    except Exception:
        return 0
