"""Discord webhook notifications."""

import os
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def _post(payload: dict) -> bool:
    url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not url:
        print(" WARNING: DISCORD_WEBHOOK_URL not set - skipping notification")
        return False
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f" Discord notify error: {e}")
        return False


def send_all_pillar_report(results: list[dict]) -> bool:
    """Send every raw gapper's five-pillar diagnostics, split safely."""
    now = datetime.now(ET).strftime("%I:%M %p ET")
    if not results:
        return _post({"embeds": [{
            "title": f"📭 Raw gapper report — {now}",
            "description": "No raw gappers found.",
            "color": 0x808080,
        }]})

    chunks = []
    current = []
    current_length = 0
    for result in results:
        pillars = result.get("pillars", {})
        details = result.get("pillar_details", {})
        ticker = result.get("ticker", "?")
        score = result.get("score", 0)
        lines = [
            f"Gap: {pillars.get('gap', 'UNKNOWN')} ({details.get('gap', 'n/a')})",
            f"Price: {pillars.get('price', 'UNKNOWN')} ({details.get('price', 'n/a')})",
            f"Rel vol: {pillars.get('rel_vol', 'UNKNOWN')} ({details.get('rel_vol', 'n/a')})",
            f"Volume: {pillars.get('volume', 'UNKNOWN')} ({details.get('volume', 'n/a')})",
            f"Float: {pillars.get('float', 'UNKNOWN')} ({details.get('float', 'n/a')})",
        ]
        value = "\n".join(lines)
        field = {
            "name": f"{ticker} | {score}/5 | ${result.get('price', 'n/a')}",
            "value": value[:1024],
            "inline": False,
        }
        field_length = len(field["name"]) + len(field["value"])
        if current and (len(current) >= 20 or current_length + field_length > 5500):
            chunks.append(current)
            current = []
            current_length = 0
        current.append(field)
        current_length += field_length
    if current:
        chunks.append(current)

    total = len(chunks)
    success = True
    for index, fields in enumerate(chunks, start=1):
        payload = {"embeds": [{
            "title": f"🔍 Raw Gapper Pillars {index}/{total} — {now}",
            "description": f"All raw gappers | {len(results)} ticker(s) | thresholds: gap ≥10%, price $2-$20, relative volume ≥5x, volume ≥100K, float ≤20M.",
            "color": 0x00B0F0,
            "fields": fields,
            "footer": {"text": "PASS/FAIL/UNKNOWN are diagnostic only; trade selection remains unchanged."},
        }]}
        success = _post(payload) and success
    return success


def send_scan_summary(candidates: list[dict]) -> bool:
    now = datetime.now(ET).strftime("%I:%M %p ET")
    if not candidates:
        return _post({"embeds": [{
            "title": f"📭 Pre-Market Scan — {now}",
            "description": "No candidates passing ≥4 pillars today. Sit on hands.",
            "color": 0x808080,
        }]})
    fields = []
    for candidate in candidates[:8]:
        pillar_str = " ".join(f"{key}:{value}" for key, value in candidate.get("pillars", {}).items())
        fields.append({
            "name": f"**{candidate['ticker']}** ${candidate['price']} | {candidate['score']}/5 pillars",
            "value": f"Gap: **{candidate['gap_pct']}%** RVol: **{candidate['rel_vol']}x** Vol: **{candidate['total_vol']:,}**\n`{pillar_str}`",
            "inline": False,
        })
    return _post({"embeds": [{
        "title": f"🔍 Pre-Market Scan — {now}",
        "description": f"**{len(candidates)} candidate(s)** passing ≥4/5 pillars.",
        "color": 0x00B0F0,
        "fields": fields,
        "footer": {"text": "Ross Cameron first pullback - automated scanner"},
    }]})


def send_no_candidates(reason: str = "") -> bool:
    now = datetime.now(ET).strftime("%I:%M %p ET")
    return _post({"embeds": [{
        "title": f"⏸️ No candidates — {now}",
        "description": reason or "Nothing passing ≥4 pillars. Sit on hands today.",
        "color": 0x808080,
    }]})


def send_entry_signal(signal) -> bool:
    now = datetime.now(ET).strftime("%I:%M %p ET")
    pillar_str = " ".join(f"{key}:{value}" for key, value in signal.pillars.items())
    return _post({"embeds": [{
        "title": f"🟢 ENTRY SIGNAL — {signal.ticker} @${signal.price}",
        "description": f"**First pullback crossing candle detected at {now}**\n\nGap: **{signal.gap_pct}%** RVol: **{signal.rel_vol}x** Vol: **{signal.total_vol:,}**\nPillars: `{pillar_str}`",
        "color": 0x00FF00,
        "fields": [
            {"name": "Entry", "value": f"**${signal.price}**", "inline": True},
            {"name": "Stop Loss", "value": f"**${signal.stop}**", "inline": True},
            {"name": "Target (2R)", "value": f"**${signal.target_2r}**", "inline": True},
            {"name": "Risk/share", "value": f"${signal.risk_per_share}", "inline": True},
            {"name": "Pillar score", "value": f"{signal.score}/5", "inline": True},
        ],
    }]})


def send_exit_signal(signal, entry_price: float, pnl_per_share: float) -> bool:
    now = datetime.now(ET).strftime("%I:%M %p ET")
    color = 0xFF0000 if pnl_per_share < 0 else 0xFFA500
    labels = {
        "stop_loss": "🛑 Stop loss hit", "vol_spike_seller": "⚠️ Volume spike",
        "topping_tail": "⚠️ Topping tail candle", "below_ema9": "⚠️ Price below 9 EMA",
        "below_vwap": "⚠️ Price below VWAP", "hard_cutoff": "⏰ 10:00 AM hard cutoff",
        "2r_target": "✅ 2R target reached — scale out",
    }
    return _post({"embeds": [{
        "title": f"🔴 EXIT — {signal.ticker} @${signal.price} | {now}",
        "description": labels.get(signal.reason, signal.reason),
        "color": color,
        "fields": [
            {"name": "Entry", "value": f"${entry_price}", "inline": True},
            {"name": "Exit", "value": f"${signal.price}", "inline": True},
            {"name": "P&L/share", "value": f"${pnl_per_share:+.2f}", "inline": True},
        ],
    }]})


def send_daily_cutoff(total_signals: int) -> bool:
    return _post({"embeds": [{
        "title": "⏰ 10:00 AM — Hard cutoff reached",
        "description": f"No new entry signals will fire today.\nTotal entry signals this session: **{total_signals}**",
        "color": 0x808080,
    }]})


def send_pnl_update(daily_pnl: float, peak_daily_pnl: float, total_signals: int, final: bool = False) -> bool:
    now = datetime.now(ET).strftime("%I:%M %p ET")
    color = 0x00FF00 if daily_pnl >= 0 else 0xFF0000
    title = f"{'✅ Final' if final else '📊 P&L Update'} — {now}"
    return _post({"embeds": [{
        "title": title,
        "color": color,
        "fields": [
            {"name": "Daily P&L", "value": f"**${daily_pnl:+,.2f}**", "inline": True},
            {"name": "Peak P&L", "value": f"${peak_daily_pnl:+,.2f}", "inline": True},
            {"name": "Total signals", "value": str(total_signals), "inline": True},
        ],
    }]})
