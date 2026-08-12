"""
scanner/executor.py

Order execution layer for Alpaca paper trading.
Uses the modern alpaca-py SDK (v0.26.0) with typed request objects.

Usage in main_session.py:
    from scanner.executor import submit_entry_order, submit_exit_order
    
    # On entry signal:
    submit_entry_order(entry_sig, account_size=10_000, risk_pct=0.01)
    
    # On exit signal:
    submit_exit_order(exit_sig, current_qty=position_shares[ticker])
"""

import os
from typing import Optional
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass


def get_trading_client() -> TradingClient:
    """
    Instantiate TradingClient using env vars.
    Make sure APCA_API_KEY_ID and APCA_API_SECRET_KEY are set in GitHub Actions secrets.
    """
    return TradingClient(
        api_key=os.environ["APCA_API_KEY_ID"],
        secret_key=os.environ["APCA_API_SECRET_KEY"],
        paper=True,
    )


def submit_entry_order(
    signal,
    account_size: float = 10_000,
    risk_pct: float = 0.01,
) -> Optional[dict]:
    """
    Submits a bracket order for an ENTRY signal using order_class="bracket".
    
    Args:
        signal: scanner.signals.Signal object from detect_entry()
        account_size: total account value in USD (adjust to your actual balance)
        risk_pct: fraction of account to risk per trade (default 1%)
    
    Returns:
        Order response dict on success, None on failure.
    """
    try:
        client = get_trading_client()
        
        # Size the position: risk = entry - stop; shares = (account * risk_pct) / risk
        risk_per_share = signal.price - signal.stop
        if risk_per_share <= 0:
            print(f" [{signal.ticker}] Invalid risk: entry={signal.price}, stop={signal.stop}")
            return None
        
        shares = int((account_size * risk_pct) / risk_per_share)
        if shares <= 0:
            print(f" [{signal.ticker}] Position size too small: {shares} shares")
            return None
        
        # Bracket order via order_class parameter
        order = MarketOrderRequest(
            symbol=signal.ticker,
            qty=shares,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET,
            take_profit=LimitOrderRequest(
                limit_price=signal.target_2r,
                time_in_force=TimeInForce.GTC,
            ),
            stop_loss=MarketOrderRequest(
                stop_price=signal.stop,
                time_in_force=TimeInForce.GTC,
            ),
        )
        
        resp = client.submit_order(order_data=order)
        print(f" ORDER SUBMITTED: {resp.id} — {shares}x {signal.ticker} @ {signal.price}")
        print(f"   Stop: {signal.stop} | Target 2R: {signal.target_2r}")
        return {"order_id": resp.id, "shares": shares, "symbol": signal.ticker}
    
    except Exception as e:
        print(f" [ERROR] Failed to submit entry order for {signal.ticker}: {e}")
        return None


def submit_exit_order(
    signal,
    current_qty: int,
) -> Optional[dict]:
    """
    Submits a market sell order to close a position on EXIT signal.
    
    Args:
        signal: scanner.signals.Signal object from detect_exit()
        current_qty: number of shares currently held (from position tracking)
    
    Returns:
        Order response dict on success, None on failure.
    """
    try:
        client = get_trading_client()
        
        if current_qty <= 0:
            print(f" [{signal.ticker}] No shares to exit (qty={current_qty})")
            return None
        
        order = MarketOrderRequest(
            symbol=signal.ticker,
            qty=current_qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        
        resp = client.submit_order(order_data=order)
        print(f" ORDER SUBMITTED (EXIT): {resp.id} — {current_qty}x {signal.ticker} @ {signal.price}")
        return {"order_id": resp.id, "shares": current_qty, "symbol": signal.ticker}
    
    except Exception as e:
        print(f" [ERROR] Failed to submit exit order for {signal.ticker}: {e}")
        return None


def get_current_position_qty(ticker: str) -> int:
    """
    Query Alpaca for the current position size of a ticker.
    Returns 0 if no position exists.
    """
    try:
        client = get_trading_client()
        position = client.get_open_position(ticker)
        return int(position.qty) if position else 0
    except Exception:
        return 0
