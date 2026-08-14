from datetime import datetime, timedelta, timezone

from scanner.quote_validation import validate_quote


def test_tight_quote_passes():
    result = validate_quote(100.00, 100.10)
    assert result.valid
    assert round(result.spread_pct, 3) == 0.1


def test_wide_quote_fails():
    result = validate_quote(945.00, 972.00, max_spread_pct=1.0)
    assert not result.valid
    assert result.reason == "spread_too_wide"


def test_crossed_quote_fails():
    result = validate_quote(101, 100)
    assert not result.valid
    assert result.reason == "crossed_quote"


def test_stale_quote_fails():
    result = validate_quote(
        100, 100.1,
        quote_timestamp=datetime.now(timezone.utc) - timedelta(minutes=3),
        max_age_seconds=120,
    )
    assert not result.valid
    assert result.reason == "stale_quote"


def test_reference_mismatch_fails():
    result = validate_quote(
        100, 100.1,
        reference_price=98,
        max_reference_deviation_pct=1.0,
    )
    assert not result.valid
    assert result.reason == "quote_reference_mismatch"
