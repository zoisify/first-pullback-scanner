"""Quote validation helpers for safe paper/live execution."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass(frozen=True)
class QuoteCheck:
    valid: bool
    bid: float = 0.0
    ask: float = 0.0
    spread_pct: float = 0.0
    reason: str = ""


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def validate_quote(
    bid: Any,
    ask: Any,
    *,
    max_spread_pct: float = 1.0,
    quote_timestamp: Any = None,
    max_age_seconds: Optional[float] = 120.0,
    reference_price: Any = None,
    max_reference_deviation_pct: Optional[float] = 1.0,
) -> QuoteCheck:
    """Validate a quote and fail closed when data is unusable.

    ``max_spread_pct`` and deviation values are percentages, not fractions.
    """
    bid_value = _as_float(bid)
    ask_value = _as_float(ask)
    if bid_value is None or ask_value is None:
        return QuoteCheck(False, reason="non_numeric_quote")
    if bid_value <= 0 or ask_value <= 0:
        return QuoteCheck(False, bid_value, ask_value, reason="non_positive_quote")
    if ask_value < bid_value:
        return QuoteCheck(False, bid_value, ask_value, reason="crossed_quote")

    midpoint = (bid_value + ask_value) / 2.0
    spread_pct = ((ask_value - bid_value) / midpoint) * 100.0
    if spread_pct > max_spread_pct:
        return QuoteCheck(False, bid_value, ask_value, spread_pct, "spread_too_wide")

    if quote_timestamp is not None and max_age_seconds is not None:
        try:
            timestamp = quote_timestamp
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds()
            if age < -5 or age > max_age_seconds:
                return QuoteCheck(False, bid_value, ask_value, spread_pct, "stale_quote")
        except (AttributeError, TypeError, ValueError):
            return QuoteCheck(False, bid_value, ask_value, spread_pct, "invalid_quote_timestamp")

    reference_value = _as_float(reference_price)
    if reference_value is not None and reference_value > 0 and max_reference_deviation_pct is not None:
        deviation_pct = abs(midpoint - reference_value) / reference_value * 100.0
        if deviation_pct > max_reference_deviation_pct:
            return QuoteCheck(False, bid_value, ask_value, spread_pct, "quote_reference_mismatch")

    return QuoteCheck(True, bid_value, ask_value, spread_pct, "ok")
