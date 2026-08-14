"""
scanner/notify.py

Sends formatted Discord messages via webhook.
No library needed — just a POST request.

All messages use Discord embeds so they're easy to read on mobile.
"""

import os
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def _post(payload: dict) -> bool:
    """POST to Discord webhook. Returns True on success."""
    url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not url:
        print("  WARNING: DISCORD_WEBHOOK_URL not set — skipping notification")
        return False
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"  Discord notify error: {e}")
        return False


def send_scan_summary(candidates: list[dict]) -> bool:
    now = datetime.now(ET).strftime("%I:%M %p ET")

    if not candidates:
        payload = {
            "embeds": [{
                "title": f"📭 Pre-Market Scan — {now}",
                "description": "No candidates passing ≥4 pillars today. Sit on hands.",
                "color": 0x808080,
            }]
        }
        return _post(payload)

    fields = []
    for c in candidates[:8]:
        pillar_str = "  ".join(f"{k}:{v}" for k, v in c["pillars"].items())
        fields.append({
            "name": f"**{c['ticker']}**  ${c['price']}  |  {c['score']}/5 pillars",
            "value": (
                f"Gap: **{c['gap_pct']}%**  "
                f"RVol: **{c['rel_vol']}×**  "
                f"Vol: **{c['total_vol']:,}**\n"
                f"`{pillar_str}`"
            ),
            "inline": False,
        })

    payload = {
        "embeds": [{
            "title": f"🔍 Pre-Market Scan — {now}",
            "description": (
                f"**{len(candidates)} candidate(s)** passing ≥4/5 pillars.\n"
                f"Watching for first pullback entry signals 7–10 AM ET."
            ),
            "color": 0x00B0F0,
            "fields": fields,
            "footer": {"text": "Ross Cameron first pullback — automated scanner"},
        }]
    }
    return _post(payload)


def send_entry_signal(signal) -> bool:
    now = datetime.now(ET).strftime("%I:%M %p ET")
    pillar_str = "  ".join(f"{k}:{v}" for k, v in signal.pillars.items())

    payload = {
        "embeds": [{
            "title": f"🟢 ENTRY SIGNAL — {signal.ticker}  @${signal.price}",
            "description": (
                f"**First pullback crossing candle detected at {now}**\n\n"
                f"Gap: **{signal.gap_pct}%**  "
                f"RVol: **{signal.rel_vol}×**  "
                f"Vol: **{signal.total_vol:,}**\n"
                f"Pillars: `{pillar_str}`"
            ),
            "color": 0x00FF00,
            "fields": [
                {"name": "Entry",       "value": f"**${signal.price}**",    "inline": True},
                {"name": "Stop Loss",   "value": f"**${signal.stop}**",     "inline": True},
                {"name": "Target (2R)", "value": f"**${signal.target_2r}**","inline": True},
                {"name": "Risk/share",  "value": f"${signal.risk_per_share}","inline": True},
                {"name": "Pillar score","value": f"{signal.score}/5",       "inline": True},
                {
                    "name": "Position size guide",
                    "value": (
                        "Risk 1% of account ÷ risk/share = shares\n"
                        "e.g. £1000 acct → £10 risk → "
                        f"{int(10 / signal.risk_per_share) if signal.risk_per_share else '?'} shares"
                    ),
                    "inline": False,
                },
            ],
            "footer": {"text": "Stop = pullback low  |  Exit on: stop / vol spike / topping tail / EMA break"},
        }]
    }
    return _post(payload)


def send_exit_signal(signal, entry_price: float, pnl_per_share: float) -> bool:
    now = datetime.now(ET).strftime("%I:%M %p ET")
    color = 0xFF0000 if pnl_per_share < 0 else 0xFFA500

    reason_labels = {
        "stop_loss":             "🛑 Stop loss hit",
        "vol_spike_seller":      "⚠️ Volume spike (big seller proxy)",
        "topping_tail":          "⚠️ Topping tail candle",
        "below_ema9":            "⚠️ Price below 9 EMA",
        "below_vwap":            "⚠️ Price below VWAP",
        "hard_cutoff":           "⏰ 10:00 AM hard cutoff",
        "2r_target":             "✅ 2R target reached — scale out",
    }
    reason_label = reason_labels.get(signal.reason, signal.reason)

    payload = {
        "embeds": [{
            "title": f"🔴 EXIT — {signal.ticker}  @${signal.price}  |  {now}",
            "description": reason_label,
            "color": color,
            "fields": [
                {"name": "Entry",     "value": f"${entry_price}",          "inline": True},
                {"name": "Exit",      "value": f"${signal.price}",          "inline": True},
                {"name": "P&L/share", "value": f"${pnl_per_share:+.2f}",   "inline": True},
            ],
        }]
    }
    return _post(payload)


def send_no_candidates(reason: str = "") -> bool:
    now = datetime.now(ET).strftime("%I:%M %p ET")
    payload = {
        "embeds": [{
            "title": f"⏸️ No candidates — {now}",
            "description": reason or "Nothing passing ≥4 pillars. Sit on hands today.",
            "color": 0x808080,
        }]
    }
    return _post(payload)


def send_daily_cutoff(total_signals: int) -> bool:
    payload = {
        "embeds": [{
            "title": "⏰ 10:00 AM — Hard cutoff reached",
            "description": (
                f"No new entry signals will fire today.\n"
                f"Total entry signals this session: **{total_signals}**"
            ),
            "color": 0x808080,
        }]
    }
    return _post(payload)


def send_pnl_update(
    daily_pnl: float,
    peak_daily_pnl: float,
    total_signals: int,
    final: bool = False,
) -> bool:
    """Send a 30-minute P&L update to Discord."""
    now = datetime.now(ET).strftime("%I:%M %p ET")
    color = 0x00FF00 if daily_pnl >= 0 else 0xFF0000
    title = f"{'✅ Final' if final else '📊 P&L Update'} — {now}"

    payload = {
        "embeds": [{
            "title": title,
            "color": color,
            "fields": [
                {"name": "Daily P&L",      "value": f"**${daily_pnl:+,.2f}**",      "inline": True},
                {"name": "Peak P&L",       "value": f"${peak_daily_pnl:+,.2f}",      "inline": True},
                {"name": "Total signals",  "value": str(total_signals),               "inline": True},
            ],
        }]
    }
    return _post(payload)
