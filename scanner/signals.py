"""
scanner/signals.py

Detects the "first pullback" entry signal on a 1-minute bar DataFrame.
Ross Cameron strategy — 1:1 implementation.

Entry rules:
1. Stock has made a squeeze: moved >= 5% off a recent swing low
2. Pullback: retraces <= 50% of the up-leg
3. Pullback CLOSES above 9 EMA AND VWAP (wicks below allowed)
4. Volume dries up on red pullback candles
5. Crossing candle: high exceeds prior candle high, closes green
   → enter on that break; stop = pullback low

Scale-in rule:
- If already in position and price makes a new high above entry,
  and a fresh crossing candle forms, add to the position

Time weighting:
- 7:00-9:30 AM ET: all signals valid
- 9:30-10:00 AM ET: only score>=4 and gap>=20%

Exit signals:
- Stop hit
- Volume spike on red candle
- Topping tail candle
- Close below 9 EMA
- Close below VWAP
- Hard 10:00 AM cutoff (enforced in main_session.py)

Trailing stop:
- Trail = highest close since entry minus original risk amount
"""

import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def vwap(bars: pd.DataFrame) -> pd.Series:
    typical = (bars["High"] + bars["Low"] + bars["Close"]) / 3
    return (typical * bars["Volume"]).cumsum() / bars["Volume"].cumsum()


@dataclass
class Signal:
    type: str  # "ENTRY" | "EXIT" | "SCALEIN"
    ticker: str
    price: float
    stop: float = 0.0
    target_2r: float = 0.0
    risk_per_share: float = 0.0
    reason: str = ""
    pillars: dict = field(default_factory=dict)
    score: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(ET))
    gap_pct: float = 0.0
    rel_vol: float = 0.0
    total_vol: int = 0


def detect_entry(candidate: dict, squeeze_threshold: float = 0.05,
                 max_retrace: float = 0.50) -> Signal | None:
    bars = candidate["bars"].copy()
    if len(bars) < 6:
        return None

    bars["EMA9"] = ema(bars["Close"], 9)
    bars["VWAP"] = vwap(bars)

    ticker = candidate["ticker"]
    score = candidate.get("score", 0)
    gap_pct = candidate.get("gap_pct", 0)

    # Time of entry weighting
    now_et = datetime.now(ET)
    after_930 = now_et.hour > 9 or (now_et.hour == 9 and now_et.minute >= 30)
    if after_930:
        if score < 4 or gap_pct < 20:
            return None

    window = bars.tail(30)
    leg_low_idx = window["Low"].idxmin()
    leg_low = window["Low"][leg_low_idx]
    post_low = window.loc[leg_low_idx:]

    if len(post_low) < 4:
        return None

    leg_high = post_low["High"].max()
    move_pct = (leg_high - leg_low) / leg_low if leg_low > 0 else 0

    if move_pct < squeeze_threshold:
        return None

    leg_high_idx = post_low["High"].idxmax()
    pullback = window.loc[leg_high_idx:]
    if len(pullback) < 2:
        return None

    pb_low = pullback["Low"].min()
    pb_retrace = (leg_high - pb_low) / (leg_high - leg_low) if (leg_high - leg_low) > 0 else 1
    if pb_retrace > max_retrace:
        return None

    # Relaxed EMA/VWAP — closes must be above, wicks allowed
    pb_close_below_ema = (pullback["Close"] < pullback["EMA9"]).any()
    pb_close_below_vwap = (pullback["Close"] < pullback["VWAP"]).any()
    if pb_close_below_ema or pb_close_below_vwap:
        return None

    # Volume dry-up on pullback
    recent_green = window[window["Close"] > window["Open"]]["Volume"].tail(5)
    pb_red = pullback[pullback["Close"] < pullback["Open"]]["Volume"]
    if not recent_green.empty and not pb_red.empty:
        if pb_red.mean() > recent_green.mean():
            return None

    # Crossing candle
    last_bar = bars.iloc[-1]
    prev_bar = bars.iloc[-2]
    crosses_high = last_bar["High"] > prev_bar["High"]
    last_is_green = last_bar["Close"] > last_bar["Open"]

    if not (crosses_high and last_is_green):
        return None

    entry_price = last_bar["High"]
    stop_price = round(pb_low * 0.995, 2)
    risk = entry_price - stop_price
    if risk <= 0:
        return None

    target_2r = round(entry_price + 2 * risk, 2)

    return Signal(
        type="ENTRY",
        ticker=ticker,
        price=round(entry_price, 2),
        stop=stop_price,
        target_2r=target_2r,
        risk_per_share=round(risk, 2),
        reason="first_pullback_crossing_candle",
        pillars=candidate.get("pillars", {}),
        score=score,
        gap_pct=gap_pct,
        rel_vol=candidate.get("rel_vol", 0),
        total_vol=candidate.get("total_vol", 0),
    )


def detect_scalein(bars: pd.DataFrame, ticker: str, entry_price: float,
                   original_risk: float, scaled_in_already: bool) -> Signal | None:
    """
    Detect a scale-in opportunity after initial entry.
    Ross adds to winners when the stock breaks to a new high
    and forms a fresh crossing candle.

    Rules:
    - Only scale in once (scaled_in_already must be False)
    - Price must be above the original entry (in profit)
    - A new crossing candle must form above the prior high
    - Stop for added shares = most recent pullback low

    Returns a SCALEIN Signal or None.
    """
    if scaled_in_already:
        return None

    if len(bars) < 6:
        return None

    bars = bars.copy()
    bars["EMA9"] = ema(bars["Close"], 9)
    bars["VWAP"] = vwap(bars)

    last_bar = bars.iloc[-1]
    prev_bar = bars.iloc[-2]

    # Must be above entry price (in profit)
    if last_bar["Close"] <= entry_price:
        return None

    # Fresh crossing candle above prior high
    crosses_high = last_bar["High"] > prev_bar["High"]
    last_is_green = last_bar["Close"] > last_bar["Open"]
    if not (crosses_high and last_is_green):
        return None

    # Must be above EMA and VWAP
    if last_bar["Close"] < last_bar["EMA9"] or last_bar["Close"] < last_bar["VWAP"]:
        return None

    # Stop for added shares = recent pullback low (last 5 bars)
    recent_low = bars.tail(10)["Low"].min()
    stop_price = round(recent_low * 0.995, 2)
    risk = last_bar["High"] - stop_price
    if risk <= 0:
        return None

    return Signal(
        type="SCALEIN",
        ticker=ticker,
        price=round(last_bar["High"], 2),
        stop=stop_price,
        risk_per_share=round(risk, 2),
        reason="scale_in_new_high",
    )


def detect_exit(bars: pd.DataFrame, entry_price: float,
                stop_price: float, ticker: str) -> Signal | None:
    if len(bars) < 3:
        return None

    bars = bars.copy()
    bars["EMA9"] = ema(bars["Close"], 9)
    bars["VWAP"] = vwap(bars)

    last = bars.iloc[-1]
    price = last["Close"]
    is_red = price < last["Open"]

    # Stop hit
    if last["Low"] <= stop_price:
        return Signal(type="EXIT", ticker=ticker, price=stop_price,
                      reason="stop_loss")

    # Volume spike on red candle
    recent_green = bars[bars["Close"] > bars["Open"]]["Volume"].tail(5)
    avg_green_vol = recent_green.mean() if not recent_green.empty else last["Volume"]
    if is_red and last["Volume"] > 1.5 * avg_green_vol:
        return Signal(type="EXIT", ticker=ticker, price=round(price, 2),
                      reason="vol_spike_seller")

    # Topping tail
    rng = last["High"] - last["Low"]
    upper_wick = last["High"] - max(price, last["Open"])
    if rng > 0 and (upper_wick / rng) >= 0.50 and is_red:
        return Signal(type="EXIT", ticker=ticker, price=round(price, 2),
                      reason="topping_tail")

    # Close below 9 EMA
    if price < last["EMA9"]:
        return Signal(type="EXIT", ticker=ticker, price=round(price, 2),
                      reason="below_ema9")

    # Close below VWAP
    if price < last["VWAP"]:
        return Signal(type="EXIT", ticker=ticker, price=round(price, 2),
                      reason="below_vwap")

    return None


def calc_trailing_stop(bars: pd.DataFrame, entry_price: float,
                       original_risk: float, trail_multiplier: float = 1.0) -> float:
    """
    Trail at (highest close since entry) minus (original risk * multiplier).
    Never goes below original stop.
    """
    if bars.empty:
        return entry_price - original_risk

    highest_close = bars["Close"].max()
    trailing = highest_close - (original_risk * trail_multiplier)
    original_stop = entry_price - original_risk
    return round(max(trailing, original_stop), 2)
