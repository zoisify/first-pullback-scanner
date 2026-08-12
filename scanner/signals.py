"""
Signal detection and order execution for first-pullback strategy
Ross-style: Scale-out at 1.5R/3R/5R, hold 25% core with trailing stop
"""

import yfinance as yf
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass
from enum import Enum

class SignalType(Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    SCALE_OUT = "SCALE_OUT"
    TRAIL_STOP = "TRAIL_STOP"

@dataclass
class Signal:
    type: SignalType
    ticker: str
    price: float
    reason: str
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

def detect_first_pullback(ticker: str, lookback_days: int = 5) -> Optional[Signal]:
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=f"{lookback_days}d", interval="1d")
        
        if len(hist) < 3:
            return None
        
        day0 = hist.iloc[-3]
        day1 = hist.iloc[-2]
        day2 = hist.iloc[-1]
        
        prev_close = hist.iloc[-4]['Close'] if len(hist) > 3 else day0['Open']
        gap_up_pct = (day0['Open'] - prev_close) / prev_close
        
        if gap_up_pct < 0.10:
            return None
        
        pullback_low = min(day1['Low'], day2['Low'])
        pullback_high = max(day1['High'], day2['High'])
        
        if pullback_low > day0['Close'] * 0.97:
            avg_volume = (day1['Volume'] + day2['Volume']) / 2
            if avg_volume < day0['Volume'] * 0.7:
                current_price = day2['Close']
                return Signal(
                    type=SignalType.ENTRY,
                    ticker=ticker,
                    price=current_price,
                    reason=f"First pullback after {gap_up_pct*100:.1f}% gap-up, volume drying up"
                )
        
        return None
    except Exception as e:
        print(f"Error detecting signal for {ticker}: {e}")
        return None

def submit_entry_order(signal: Signal, qty: int = 33) -> Optional[Dict]:
    from scanner.executor import get_trading_client
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    
    try:
        client = get_trading_client()
        
        order_data = MarketOrderRequest(
            symbol=signal.ticker,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY
        )
        
        order = client.submit_order(order_data)
        print(f"Entry order submitted: {signal.ticker} x {qty} @ {signal.price}")
        
        return {
            "order_id": order.id,
            "ticker": signal.ticker,
            "qty": qty,
            "entry_price": signal.price,
            "timestamp": signal.timestamp
        }
    except Exception as e:
        print(f"Failed to submit entry order: {e}")
        return None

def submit_scale_out_orders(entry_price: float, current_price: float, current_qty: int, ticker: str) -> List[Dict]:
    from scanner.executor import get_trading_client
    from alpaca.trading.requests import LimitOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    
    client = get_trading_client()
    orders = []
    
    risk_per_share = entry_price * 0.03
    r_multiple = (current_price - entry_price) / risk_per_share
    
    scale_out_levels = [
        {"r": 1.5, "pct": 0.25, "label": "1.5R (25%)"},
        {"r": 3.0, "pct": 0.25, "label": "3R (25%)"},
        {"r": 5.0, "pct": 0.25, "label": "5R (25%)"},
    ]
    
    for level in scale_out_levels:
        target_price = entry_price + (risk_per_share * level["r"])
        
        if current_price >= target_price:
            qty_to_sell = int(current_qty * level["pct"])
            
            if qty_to_sell > 0:
                try:
                    order_data = LimitOrderRequest(
                        symbol=ticker,
                        qty=qty_to_sell,
                        side=OrderSide.SELL,
                        time_in_force=TimeInForce.GTC,
                        limit_price=round(target_price, 2)
                    )
                    
                    order = client.submit_order(order_data)
                    orders.append({
                        "order_id": order.id,
                        "type": "SCALE_OUT",
                        "level": level["label"],
                        "qty": qty_to_sell,
                        "price": round(target_price, 2)
                    })
                    print(f"Scale-out order: {ticker} x {qty_to_sell} @ {target_price:.2f} ({level['label']})")
                except Exception as e:
                    print(f"Failed to submit scale-out order: {e}")
    
    return orders

def submit_trailing_stop(ticker: str, qty: int, entry_price: float, current_price: float) -> Optional[Dict]:
    from scanner.executor import get_trading_client
    from alpaca.trading.requests import StopOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    
    try:
        client = get_trading_client()
        
        trail_pct = 0.10
        stop_price = current_price * (1 - trail_pct)
        
        if stop_price < entry_price:
            stop_price = entry_price * 0.99
        
        order_data = StopOrderRequest(
            symbol=ticker,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.GTC,
            stop_price=round(stop_price, 2)
        )
        
        order = client.submit_order(order_data)
        print(f"Trailing stop: {ticker} x {qty} @ {stop_price:.2f}")
        
        return {
            "order_id": order.id,
            "type": "TRAILING_STOP",
            "qty": qty,
            "stop_price": round(stop_price, 2)
        }
    except Exception as e:
        print(f"Failed to submit trailing stop: {e}")
        return None

def submit_exit_order(signal: Signal, current_qty: int) -> Optional[Dict]:
    from scanner.executor import get_trading_client
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    
    try:
        client = get_trading_client()
        
        order_data = MarketOrderRequest(
            symbol=signal.ticker,
            qty=current_qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY
        )
        
        order = client.submit_order(order_data)
        print(f"Exit order: {signal.ticker} x {current_qty} @ {signal.price}")
        
        return {
            "order_id": order.id,
            "ticker": signal.ticker,
            "qty": current_qty,
            "exit_price": signal.price,
            "reason": signal.reason
        }
    except Exception as e:
        print(f"Failed to submit exit order: {e}")
        return None

def manage_position(ticker: str, entry_price: float, entry_time: datetime) -> Dict:
    from scanner.executor import get_trading_client
    
    result = {
        "ticker": ticker,
        "action": "HOLD",
        "orders": []
    }
    
    try:
        client = get_trading_client()
        pos = client.get_open_position(ticker)
        
        if not pos:
            return result
        
        current_price = float(pos.current_price)
        current_qty = int(pos.qty)
        
        risk_per_share = entry_price * 0.03
        r_multiple = (current_price - entry_price) / risk_per_share
        
        if datetime.now() - entry_time > timedelta(days=3):
            exit_signal = Signal(
                type=SignalType.EXIT,
                ticker=ticker,
                price=current_price,
                reason="Time exit: 3 days held"
            )
            exit_result = submit_exit_order(exit_signal, current_qty)
            if exit_result:
                result["action"] = "EXIT"
                result["orders"].append(exit_result)
            return result
        
        if r_multiple >= 1.5:
            scale_orders = submit_scale_out_orders(entry_price, current_price, current_qty, ticker)
            if scale_orders:
                result["action"] = "SCALE_OUT"
                result["orders"].extend(scale_orders)
        
        if r_multiple >= 1.0 and current_qty > 0:
            print(f"  Should trail stop for {ticker} core position")
        
        return result
    except Exception as e:
        print(f"Error managing position for {ticker}: {e}")
        return result
