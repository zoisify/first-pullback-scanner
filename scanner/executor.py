"""
scanner/executor.py

Order execution layer for Alpaca paper trading.
Ross Cameron first pullback strategy — 1:1 implementation.

- Entry: market buy + bid/ask spread check + separate stop order
- Scale-in: additional market buy on new high with updated stop
- Exit partial: sell 60% core on first indicator
- Exit runner: sell remaining 40% on second indicator or cutoff
- Trailing stop: updated every poll on runner
"""

import os
from typing import Optional
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, StopOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce


def get_trading_client() -> TradingClient:
    return TradingClient(
        api_key=os.environ["ALPACA_API_KEY"],
        secret_key=os.environ["ALPACA_SECRET_KEY"],
        paper=True,
    )


def check_spread(ticker: str, max_spread_pct: float = 0.02) -> bool:
    """
    Check bid/ask spread before entering.
    Returns True if tight enough, False if too wide.
    Proxy for Ross's Level 2 sentiment check.
    """
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockLatestQuoteRequest

        data_client = StockHistoricalDataClient(
            os.environ["ALPACA_API_KEY"],
            os.environ["ALPACA_SECRET_KEY"],
        )
        request = StockLatestQuoteRequest(symbol_or_symbols=ticker)
        quote = data_client.get_stock_latest_quote(request)[ticker]

        bid = quote.bid_price
        ask = quote.ask_price
        if not bid or not ask or bid <= 0:
            return True  # can't check, allow through

        spread_pct = (ask - bid) / ((ask + bid) / 2)
        if spread_pct > max_spread_pct:
            print(f" [{ticker}] Spread too wide: {spread_pct:.1%} (bid={bid}, ask={ask})")
            return False

        print(f" [{ticker}] Spread OK: {spread_pct:.1%} (bid={bid}, ask={ask})")
        return True

    except Exception as e:
        print(f" [{ticker}] Spread check failed: {e} — allowing through")
        return True


def submit_entry_order(
    signal,
    account_size: float = 65_000,
    risk_pct: float = 0.01,
) -> Optional[dict]:
    """
    Spread check → market buy → separate stop order.
    Returns dict with order_id, stop_order_id, shares on success.
    """
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

        buy_order = MarketOrderRequest(
            symbol=signal.ticker,
            qty=shares,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        buy_resp = client.submit_order(order_data=buy_order)
        print(f" BUY ORDER: {buy_resp.id} — {shares}x {signal.ticker}")
        print(f"   Entry ~${signal.price} | Stop ${signal.stop} | 2R ref ${signal.target_2r}")

        stop_order = StopOrderRequest(
            symbol=signal.ticker,
            qty=shares,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            stop_price=round(signal.stop, 2),
        )
        stop_resp = client.submit_order(order_data=stop_order)
        print(f" STOP ORDER: {stop_resp.id} — stop at ${signal.stop}")

        return {
            "order_id": buy_resp.id,
            "stop_order_id": stop_resp.id,
            "shares": shares,
            "symbol": signal.ticker,
        }

    except Exception as e:
        print(f" [ERROR] Entry order failed for {signal.ticker}: {e}")
        return None


def submit_scalein_order(
    signal,
    account_size: float = 65_000,
    risk_pct: float = 0.005,  # half size on scale-in (0.5% risk)
    old_stop_order_id: Optional[str] = None,
    total_shares_held: int = 0,
) -> Optional[dict]:
    """
    Scale-in: additional buy on new high.
    Cancels old stop, buys more shares, submits new stop covering all shares.
    Uses half the normal risk (0.5%) so total risk stays controlled.
    Returns dict with order_id, stop_order_id, shares added.
    """
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

        # Cancel old stop before adding shares
        if old_stop_order_id:
            try:
                client.cancel_order_by_id(old_stop_order_id)
                print(f" Cancelled old stop for scale-in: {old_stop_order_id}")
            except Exception:
                pass

        # Buy additional shares
        buy_order = MarketOrderRequest(
            symbol=signal.ticker,
            qty=shares_to_add,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        buy_resp = client.submit_order(order_data=buy_order)
        print(f" SCALE-IN ORDER: {buy_resp.id} — +{shares_to_add}x {signal.ticker} @~${signal.price}")

        # New stop covers ALL shares (original + added)
        total_shares = total_shares_held + shares_to_add
        stop_order = StopOrderRequest(
            symbol=signal.ticker,
            qty=total_shares,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            stop_price=round(signal.stop, 2),
        )
        stop_resp = client.submit_order(order_data=stop_order)
        print(f" NEW STOP ORDER: {stop_resp.id} — {total_shares} shares @ ${signal.stop}")

        return {
            "order_id": buy_resp.id,
            "stop_order_id": stop_resp.id,
            "shares_added": shares_to_add,
            "symbol": signal.ticker,
        }

    except Exception as e:
        print(f" [ERROR] Scale-in failed for {signal.ticker}: {e}")
        return None


def submit_exit_order(
    signal,
    current_qty: int,
    stop_order_id: Optional[str] = None,
) -> Optional[dict]:
    """Market sell for current_qty shares. Cancels stop first to avoid double-fill."""
    try:
        client = get_trading_client()

        if current_qty <= 0:
            print(f" [{signal.ticker}] No shares to sell (qty={current_qty})")
            return None

        if stop_order_id:
            try:
                client.cancel_order_by_id(stop_order_id)
                print(f" Cancelled stop order {stop_order_id}")
            except Exception:
                pass

        order = MarketOrderRequest(
            symbol=signal.ticker,
            qty=current_qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        resp = client.submit_order(order_data=order)
        print(f" SELL ORDER: {resp.id} — {current_qty}x {signal.ticker} @ ~${signal.price}")
        return {"order_id": resp.id, "shares": current_qty, "symbol": signal.ticker}

    except Exception as e:
        print(f" [ERROR] Exit order failed for {signal.ticker}: {e}")
        return None


def update_trailing_stop(
    ticker: str,
    current_qty: int,
    old_stop_order_id: Optional[str],
    new_stop_price: float,
) -> Optional[str]:
    """Cancel old stop, submit new one at higher price. Returns new stop_order_id."""
    try:
        client = get_trading_client()

        if old_stop_order_id:
            try:
                client.cancel_order_by_id(old_stop_order_id)
            except Exception:
                pass

        stop_order = StopOrderRequest(
            symbol=ticker,
            qty=current_qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            stop_price=round(new_stop_price, 2),
        )
        resp = client.submit_order(order_data=stop_order)
        print(f" TRAILING STOP updated: ${new_stop_price} ({ticker})")
        return resp.id

    except Exception as e:
        print(f" [WARN] Trailing stop update failed for {ticker}: {e}")
        return old_stop_order_id


def get_current_position_qty(ticker: str) -> int:
    try:
        client = get_trading_client()
        position = client.get_open_position(ticker)
        return int(float(position.qty)) if position else 0
    except Exception:
        return 0
