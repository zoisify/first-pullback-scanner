"""
scanner/signals.py

Detects the "first pullback" entry signal on a 1-minute bar DataFrame.
Ross Cameron strategy - 1:1 implementation.

Entry rules:
1. Stock has made a squeeze: moved >= 5% off a recent swing low
2. Pullback: retraces <= 50% of the up-leg
3. Pullback CLOSES above 9 EMA AND VWAP (wicks below allowed)
4. Volume dries up on red pullback candles
5. ANTICIPATION entry: enter as soon as current candle high breaks
   prior candle high AND candle is green - do not wait for close

Re-entry:
- After a stop out, watch for a second pullback on the same stock
- Same rules apply, treated as a fresh entry

Scale-in:
- If in profit and a new crossing candle forms above entry, add shares
- Only once per trade

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
    """
    Detects first pullback entry using ANTICIPATION logic.
    Enters as soon as current candle high breaks prior candle high
    and candle is currently green - does not wait for candle to close.
    This matches Ross's style of entering on the break, not after confirmation.
    """
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

    # Relaxed EMA/VWAP - closes must be above, wicks allowed
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

    # Anticipation entry
    last_bar = bars.iloc[-1]
    prev_bar = bars.iloc[-2]

    crosses_high = last_bar["High"] > prev_bar["High"]
    candle_is_green = last_bar["Close"] > last_bar["Open"]

    if not (crosses_high and candle_is_green):
        return None

    # Enter at break of prior high + 1 cent
    entry_price = round(prev_bar["High"] + 0.01, 2)
    stop_price = round(pb_low * 0.995, 2)
    risk = entry_price - stop_price
    if risk <= 0:
        return None

    target_2r = round(entry_price + 2 * risk, 2)

    return Signal(
        type="ENTRY",
        ticker=ticker,
        price=entry_price,
        stop=stop_price,
        target_2r=target_2r,
        risk_per_share=round(risk, 2),
        reason="first_pullback_anticipation",
        pillars=candidate.get("pillars", {}),
        score=score,
        gap_pct=gap_pct,
        rel_vol=candidate.get("rel_vol", 0),
        total_vol=candidate.get("total_vol", 0),
    )


def detect_reentry(candidate: dict, stop_out_price: float,
                   squeeze_threshold: float = 0.05,
                   max_retrace: float = 0.50) -> Signal | None:
    """
    Detects a second pullback entry after being stopped out.
    Ross looks for a fresh setup on the same stock after a stop.
    Stock must have recovered above stop-out price and formed
    a fresh squeeze and pullback.
    """
    bars = candidate["bars"].copy()
    if len(bars) < 6:
        return None

    bars["EMA9"] = ema(bars["Close"], 9)
    bars["VWAP"] = vwap(bars)

    ticker = candidate["ticker"]
    score = candidate.get("score", 0)
    gap_pct = candidate.get("gap_pct", 0)

    now_et = datetime.now(ET)
    after_930 = now_et.hour > 9 or (now_et.hour == 9 and now_et.minute >= 30)
    if after_930:
        if score < 4 or gap_pct < 20:
            return None

    # Stock must be above stop-out price - shows it recovered
    last_close = bars["Close"].iloc[-1]
    if last_close <= stop_out_price:
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

    pb_close_below_ema = (pullback["Close"] < pullback["EMA9"]).any()
    pb_close_below_vwap = (pullback["Close"] < pullback["VWAP"]).any()
    if pb_close_below_ema or pb_close_below_vwap:
        return None

    recent_green = window[window["Close"] > window["Open"]]["Volume"].tail(5)
    pb_red = pullback[pullback["Close"] < pullback["Open"]]["Volume"]
    if not recent_green.empty and not pb_red.empty:
        if pb_red.mean() > recent_green.mean():
            return None

    last_bar = bars.iloc[-1]
    prev_bar = bars.iloc[-2]

    crosses_high = last_bar["High"] > prev_bar["High"]
    candle_is_green = last_bar["Close"] > last_bar["Open"]

    if not (crosses_high and candle_is_green):
        return None

    entry_price = round(prev_bar["High"] + 0.01, 2)
    stop_price = round(pb_low * 0.995, 2)
    risk = entry_price - stop_price
    if risk <= 0:
        return None

    target_2r = round(entry_price + 2 * risk, 2)

    return Signal(
        type="ENTRY",
        ticker=ticker,
        price=entry_price,
        stop=stop_price,
        target_2r=target_2r,
        risk_per_share=round(risk, 2),
        reason="second_pullback_reentry",
        pillars=candidate.get("pillars", {}),
        score=score,
        gap_pct=gap_pct,
        rel_vol=candidate.get("rel_vol", 0),
        total_vol=candidate.get("total_vol", 0),
    )


def detect_scalein(bars: pd.DataFrame, ticker: str, entry_price: float,
                   original_risk: float, scaled_in_already: bool) -> Signal | None:
    """
    Detect scale-in on new high. Only once per trade.
    Uses anticipation entry same as initial entry.
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

    if last_bar["Close"] <= entry_price:
        return None

    crosses_high = last_bar["High"] > prev_bar["High"]
    candle_is_green = last_bar["Close"] > last_bar["Open"]
    if not (crosses_high and candle_is_green):
        return None

    if last_bar["Close"] < last_bar["EMA9"] or last_bar["Close"] < last_bar["VWAP"]:
        return None

    recent_low = bars.tail(10)["Low"].min()
    stop_price = round(recent_low * 0.995, 2)
    entry_price_si = round(prev_bar["High"] + 0.01, 2)
    risk = entry_price_si - stop_price
    if risk <= 0:
        return None

    return Signal(
        type="SCALEIN",
        ticker=ticker,
        price=entry_price_si,
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

    if last["Low"] <= stop_price:
        return Signal(type="EXIT", ticker=ticker, price=stop_price,
                      reason="stop_loss")

    recent_green = bars[bars["Close"] > bars["Open"]]["Volume"].tail(5)
    avg_green_vol = recent_green.mean() if not recent_green.empty else last["Volume"]
    if is_red and last["Volume"] > 1.5 * avg_green_vol:
        return Signal(type="EXIT", ticker=ticker, price=round(price, 2),
                      reason="vol_spike_seller")

    rng = last["High"] - last["Low"]
    upper_wick = last["High"] - max(price, last["Open"])
    if rng > 0 and (upper_wick / rng) >= 0.50 and is_red:
        return Signal(type="EXIT", ticker=ticker, price=round(price, 2),
                      reason="topping_tail")

    if price < last["EMA9"]:
        return Signal(type="EXIT", ticker=ticker, price=round(price, 2),
                      reason="below_ema9")

    if price < last["VWAP"]:
        return Signal(type="EXIT", ticker=ticker, price=round(price, 2),
                      reason="below_vwap")

    return None


def calc_trailing_stop(bars: pd.DataFrame, entry_price: float,
                       original_risk: float, trail_multiplier: float = 1.0) -> float:
    if bars.empty:
        return entry_price - original_risk

    highest_close = bars["Close"].max()
    trailing = highest_close - (original_risk * trail_multiplier)
    original_stop = entry_price - original_risk
    return round(max(trailing, original_stop), 2)
