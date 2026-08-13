"""
scanner/executor.py

Order execution layer for Alpaca paper trading.
Uses the modern alpaca-py SDK with typed request objects.

Strategy (Ross Cameron first pullback):
- Entry: plain market buy
- Stop: separate stop order at pullback low
- NO bracket / NO hard 2R exit — let indicators handle exits
- Exit partial (60%) on first indicator via market sell
- Exit runner (40%) on second indicator or 10 AM cutoff
"""

import os
from typing import Optional
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    StopOrderRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce


def get_trading_client() -> TradingClient:
    return TradingClient(
        api_key=os.environ["ALPACA_API_KEY"],
        secret_key=os.environ["ALPACA_SECRET_KEY"],
        paper=True,
    )


def submit_entry_order(
    signal,
    account_size: float = 65_000,
    risk_pct: float = 0.01,
) -> Optional[dict]:
    """
    Submits a market buy + separate stop loss order on entry signal.
    No bracket / no 2R hard exit — exits handled by indicator detection.

    Returns dict with order_id, stop_order_id, shares on success, else None.
    """
    try:
        client = get_trading_client()

        risk_per_share = signal.price - signal.stop
        if risk_per_share <= 0:
            print(f" [{signal.ticker}] Invalid risk: entry={signal.price}, stop={signal.stop}")
            return None

        shares = int((account_size * risk_pct) / risk_per_share)
        if shares <= 0:
            print(f" [{signal.ticker}] Position size too small")
            return None

        # 1. Market buy
        buy_order = MarketOrderRequest(
            symbol=signal.ticker,
            qty=shares,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        buy_resp = client.submit_order(order_data=buy_order)
        print(f" BUY ORDER: {buy_resp.id} — {shares}x {signal.ticker}")
        print(f"   Entry ~${signal.price} | Stop ${signal.stop} | 2R ref ${signal.target_2r}")

        # 2. Separate stop loss order
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


def submit_exit_order(
    signal,
    current_qty: int,
    stop_order_id: Optional[str] = None,
) -> Optional[dict]:
    """
    Submits a market sell for current_qty shares.
    Cancels the stop order first if stop_order_id is provided,
    so we don't double-sell.

    Returns dict with order_id and shares on success, else None.
    """
    try:
        client = get_trading_client()

        if current_qty <= 0:
            print(f" [{signal.ticker}] No shares to sell (qty={current_qty})")
            return None

        # Cancel existing stop order to avoid double-fill
        if stop_order_id:
            try:
                client.cancel_order_by_id(stop_order_id)
                print(f" Cancelled stop order {stop_order_id}")
            except Exception:
                pass  # may already be filled or cancelled

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


def get_current_position_qty(ticker: str) -> int:
    """Query Alpaca for current position size. Returns 0 if no position."""
    try:
        client = get_trading_client()
        position = client.get_open_position(ticker)
        return int(float(position.qty)) if position else 0
    except Exception:
        return 0
