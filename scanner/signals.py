"""
scanner/signals.py

Detects the "first pullback" entry signal on a 1-minute bar DataFrame.
Returns structured signal dicts that notify.py formats for Discord.

Entry rules (from transcript + systematization):
  1. Stock has made a squeeze: moved >= 5% off a recent swing low
  2. Pullback: retraces <= 50% of the up-leg
  3. Pullback stays above 9 EMA AND above VWAP
  4. Volume dries up on red pullback candles
  5. "Crossing candle": first candle whose HIGH exceeds the prior candle's HIGH
     → enter on that break; stop = pullback low

Exit signals (Ross's exit indicators, systematized):
  - Stop hit (coded as a level returned, not executed — paper order handles this)
  - Volume spike on red candle (proxy for "big seller on Level 2")
  - Topping tail candle (large upper wick, closes red)
  - Price closes below 9 EMA
  - Price closes below VWAP
  - Hard 10:00 AM ET cutoff
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


# ── Indicator helpers ──────────────────────────────────────────────────────────

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def vwap(bars: pd.DataFrame) -> pd.Series:
    """Session VWAP — resets daily (bars should be today's bars only)."""
    typical = (bars["High"] + bars["Low"] + bars["Close"]) / 3
    return (typical * bars["Volume"]).cumsum() / bars["Volume"].cumsum()


# ── Signal dataclass ───────────────────────────────────────────────────────────

@dataclass
class Signal:
    type: str           # "ENTRY" | "EXIT"
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


# ── Core signal detector ───────────────────────────────────────────────────────

def detect_entry(candidate: dict, squeeze_threshold: float = 0.05,
                 max_retrace: float = 0.50) -> Signal | None:
    """
    Run the first-pullback entry logic on a candidate's bar data.
    Returns a Signal if an entry triggers, else None.
    """
    bars = candidate["bars"].copy()
    if len(bars) < 6:
        return None

    bars["EMA9"]  = ema(bars["Close"], 9)
    bars["VWAP"]  = vwap(bars)

    ticker = candidate["ticker"]
    price  = bars["Close"].iloc[-1]

    # Don't enter after 10:00 AM ET hard cutoff (Ross's own hardest rule)
    now_et = datetime.now(ET)
    if now_et.hour >= 10:
        return None

    # ── Find swing low and the up-leg ────────────────────────────────────────
    window = bars.tail(30)   # look back max 30 bars for the setup
    leg_low_idx  = window["Low"].idxmin()
    leg_low      = window["Low"][leg_low_idx]
    post_low     = window.loc[leg_low_idx:]

    if len(post_low) < 4:
        return None

    leg_high     = post_low["High"].max()
    move_pct     = (leg_high - leg_low) / leg_low if leg_low > 0 else 0

    # Must have squeezed at least squeeze_threshold off the low
    if move_pct < squeeze_threshold:
        return None

    # ── Find the pullback ────────────────────────────────────────────────────
    leg_high_idx = post_low["High"].idxmax()
    pullback     = window.loc[leg_high_idx:]

    if len(pullback) < 2:
        return None

    pb_low       = pullback["Low"].min()
    pb_retrace   = (leg_high - pb_low) / (leg_high - leg_low) if (leg_high - leg_low) > 0 else 1

    # Pullback must not retrace more than 50%
    if pb_retrace > max_retrace:
        return None

    # Pullback must stay above 9 EMA and VWAP
    pb_below_ema  = (pullback["Close"] < pullback["EMA9"]).any()
    pb_below_vwap = (pullback["Close"] < pullback["VWAP"]).any()
    if pb_below_ema or pb_below_vwap:
        return None

    # Volume should dry up during pullback (red candles lighter than preceding green candles)
    recent_green = window[window["Close"] > window["Open"]]["Volume"].tail(5)
    pb_red       = pullback[pullback["Close"] < pullback["Open"]]["Volume"]
    if not recent_green.empty and not pb_red.empty:
        avg_green_vol = recent_green.mean()
        avg_red_vol   = pb_red.mean()
        if avg_red_vol > avg_green_vol:
            return None   # volume not drying up — weaker setup

    # ── "Crossing candle" — entry trigger ────────────────────────────────────
    last_bar      = bars.iloc[-1]
    prev_bar      = bars.iloc[-2]
    crosses_high  = last_bar["High"] > prev_bar["High"]
    last_is_green = last_bar["Close"] > last_bar["Open"]

    if not (crosses_high and last_is_green):
        return None

    # ── Build the signal ─────────────────────────────────────────────────────
    entry_price   = last_bar["High"]        # stop-buy above prior high
    stop_price    = round(pb_low * 0.995, 2) # slight buffer below pullback low
    risk          = entry_price - stop_price
    if risk <= 0:
        return None

    target_2r     = round(entry_price + 2 * risk, 2)

    return Signal(
        type           = "ENTRY",
        ticker         = ticker,
        price          = round(entry_price, 2),
        stop           = stop_price,
        target_2r      = target_2r,
        risk_per_share = round(risk, 2),
        reason         = "first_pullback_crossing_candle",
        pillars        = candidate["pillars"],
        score          = candidate["score"],
        gap_pct        = candidate["gap_pct"],
        rel_vol        = candidate["rel_vol"],
        total_vol      = candidate["total_vol"],
    )


def detect_exit(bars: pd.DataFrame, entry_price: float,
                stop_price: float, ticker: str) -> Signal | None:
    """
    Checks exit conditions on updated bars.
    Returns an EXIT Signal if any condition is met, else None.
    Ross's exit indicators in priority order:
      1. Stop hit
      2. Volume-spike red candle (big seller proxy)
      3. Topping tail
      4. Below 9 EMA
      5. Below VWAP
    """
    if len(bars) < 3:
        return None

    bars = bars.copy()
    bars["EMA9"] = ema(bars["Close"], 9)
    bars["VWAP"] = vwap(bars)

    last    = bars.iloc[-1]
    price   = last["Close"]
    is_red  = price < last["Open"]

    # 1. Stop hit
    if last["Low"] <= stop_price:
        return Signal(type="EXIT", ticker=ticker, price=stop_price,
                      reason="stop_loss")

    # 2. Volume spike on red candle (big seller proxy — Level 2 substitute)
    recent_green = bars[bars["Close"] > bars["Open"]]["Volume"].tail(5)
    avg_green_vol = recent_green.mean() if not recent_green.empty else last["Volume"]
    if is_red and last["Volume"] > 1.5 * avg_green_vol:
        return Signal(type="EXIT", ticker=ticker, price=round(price, 2),
                      reason="vol_spike_seller")

    # 3. Topping tail (upper wick >= 50% of total range, closes red)
    rng        = last["High"] - last["Low"]
    upper_wick = last["High"] - max(price, last["Open"])
    if rng > 0 and (upper_wick / rng) >= 0.50 and is_red:
        return Signal(type="EXIT", ticker=ticker, price=round(price, 2),
                      reason="topping_tail")

    # 4. Below 9 EMA
    if price < last["EMA9"]:
        return Signal(type="EXIT", ticker=ticker, price=round(price, 2),
                      reason="below_ema9")

    # 5. Below VWAP
    if price < last["VWAP"]:
        return Signal(type="EXIT", ticker=ticker, price=round(price, 2),
                      reason="below_vwap")

    return None
