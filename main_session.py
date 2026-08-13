"""
main_session.py

Session monitor — called by trading.yml at 7:05 AM ET.
Runs until 10:00 AM ET hard cutoff.
Polls every 60 seconds for first-pullback entry/exit signals.

Ross-style strategy:
- Risk 1% of account per trade
- Stop: pullback low (separate stop order)
- NO hard 2R exit — exit on indicators only
- Partial sell 60% on first indicator, hold 40% runner
- Trailing stop on runner after first partial exit
- Walk-away if give back 50% of peak P&L or hit max daily loss
- Focus on strongest gapper (sorted by score + gap)
- 30-min P&L update to Discord
- Bid/ask spread check before entry
- Time weighting: stricter after 9:30 AM ET
"""

import os
import csv
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from scanner.pillars import _get_alpaca_client, get_bars, score_ticker
from scanner.signals import detect_entry, detect_exit, calc_trailing_stop, Signal
from scanner.notify import (
    send_entry_signal, send_exit_signal,
    send_daily_cutoff, send_no_candidates,
    send_pnl_update,
)
from scanner.executor import (
    submit_entry_order, submit_exit_order,
    update_trailing_stop, get_trading_client,
)

ET = ZoneInfo("America/New_York")
LOG_DIR = "logs"
POLL_SEC = 60
CUTOFF_H = 10

RISK_PCT = 0.01
ACCOUNT_EQUITY = 65_000.0
MAX_DAILY_LOSS = 2_000.0
FIRST_EXIT_SELL_FRAC = 0.6
PNL_UPDATE_INTERVAL = 30  # minutes between Discord P&L updates

# Trailing stop: trail 1R below highest close since entry
TRAIL_MULTIPLIER = 1.0


def load_candidates() -> list[dict]:
    date_str = datetime.now(ET).strftime("%Y%m%d")
    path = os.path.join(LOG_DIR, f"candidates_{date_str}.json")
    if not os.path.exists(path):
        print(f" No candidates file found at {path}")
        print(" Run main_scan.py first.")
        return []
    with open(path) as f:
        return json.load(f)


def load_watchlist() -> list[str]:
    path = "data/watchlist.csv"
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [
            r[0].strip().upper()
            for r in csv.reader(f)
            if r and r[0].strip() and not r[0].startswith("#") and r[0].strip() != "TICKER"
        ]


def log_signal(row: dict):
    os.makedirs(LOG_DIR, exist_ok=True)
    date_str = datetime.now(ET).strftime("%Y%m%d")
    path = os.path.join(LOG_DIR, f"session_{date_str}.csv")
    fields = [
        "timestamp", "ticker", "action", "price", "stop", "target_2r",
        "risk_per_share", "reason", "score", "gap_pct", "rel_vol", "total_vol",
        "shares", "partial", "daily_pnl", "peak_daily_pnl"
    ]
    write_header = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if write_header:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in fields})


def main():
    print(f"\n{'='*55}")
    print(f" Session Monitor — {datetime.now(ET).strftime('%Y-%m-%d %H:%M %Z')}")
    print(f" Hard cutoff: {CUTOFF_H}:00 AM ET")
    print(f" Max daily loss: ${MAX_DAILY_LOSS:,.2f}")
    print(f"{'='*55}\n")

    api = _get_alpaca_client()
    data_client, trading_client = api

    candidates = load_candidates()
    if not candidates:
        print(" No pre-market candidates — running live scan of watchlist …")
        watchlist = load_watchlist()
        for ticker in watchlist:
            r = score_ticker(api, ticker)
            if r:
                candidates.append({k: v for k, v in r.items() if k != "bars"})

    if not candidates:
        send_no_candidates("No candidates and watchlist empty. Nothing to monitor.")
        return

    # Sort by score desc then gap desc — focus on strongest gapper first
    candidates.sort(key=lambda x: (x.get("score", 0), x.get("gap_pct", 0)), reverse=True)

    candidate_map = {c["ticker"]: c for c in candidates}
    watchlist = [c["ticker"] for c in candidates]

    print(f" Monitoring {len(watchlist)} candidates (strongest first): {', '.join(watchlist)}\n")

    open_positions: dict[str, dict] = {}
    fired_entries: set[str] = set()
    total_entries: int = 0
    notified_cutoff: bool = False

    daily_pnl: float = 0.0
    peak_daily_pnl: float = 0.0
    stopped_for_day: bool = False

    last_pnl_update: datetime = datetime.now(ET)

    while True:
        now_et = datetime.now(ET)

        # ── Hard 10:00 AM cutoff ──────────────────────────────────────────────
        if now_et.hour >= CUTOFF_H:
            if not notified_cutoff:
                print(f"\n 10:00 AM cutoff — Total signals: {total_entries}")
                send_daily_cutoff(total_entries)

            for ticker, pos in list(open_positions.items()):
                bars = get_bars(data_client, ticker, limit=5)
                exit_price = bars["Close"].iloc[-1] if not bars.empty else pos["entry_price"]
                pnl = (exit_price - pos["entry_price"]) * pos["shares_remaining"]
                daily_pnl += pnl

                exit_sig = Signal(
                    type="EXIT",
                    ticker=ticker,
                    price=exit_price,
                    reason="hard_cutoff",
                )
                submit_exit_order(
                    exit_sig,
                    current_qty=pos["shares_remaining"],
                    stop_order_id=pos.get("stop_order_id"),
                )
                send_exit_signal(exit_sig, pos["entry_price"], pnl)
                log_signal({
                    "timestamp": now_et.isoformat(),
                    "ticker": ticker,
                    "action": "EXIT",
                    "price": exit_price,
                    "reason": "hard_cutoff",
                    "risk_per_share": pnl / pos["shares_total"] if pos["shares_total"] else 0,
                    "shares": pos["shares_remaining"],
                    "partial": False,
                    "daily_pnl": daily_pnl,
                    "peak_daily_pnl": peak_daily_pnl,
                    "stop": pos["stop"],
                    "target_2r": pos["target_2r"],
                    "score": "",
                    "gap_pct": "",
                    "rel_vol": "",
                    "total_vol": "",
                })
                del open_positions[ticker]

            notified_cutoff = True
            send_pnl_update(daily_pnl, peak_daily_pnl, total_entries, final=True)
            break

        # ── 30-min P&L Discord update ─────────────────────────────────────────
        mins_since_update = (now_et - last_pnl_update).seconds / 60
        if mins_since_update >= PNL_UPDATE_INTERVAL:
            send_pnl_update(daily_pnl, peak_daily_pnl, total_entries, final=False)
            last_pnl_update = now_et

        # ── Daily walk-away check ─────────────────────────────────────────────
        if not stopped_for_day:
            if peak_daily_pnl > 0 and daily_pnl <= 0.5 * peak_daily_pnl:
                print("\n Walk-away: given back >= 50% of peak P&L. No new entries.")
                stopped_for_day = True
            elif daily_pnl <= -MAX_DAILY_LOSS:
                print("\n Walk-away: max daily loss hit. No new entries.")
                stopped_for_day = True

        # ── Poll each candidate ───────────────────────────────────────────────
        for ticker in watchlist:
            bars = get_bars(data_client, ticker, limit=60)
            if bars.empty:
                continue

            meta = candidate_map.get(ticker, {})

            # ── Trailing stop update (runner only, after first partial exit) ──
            if ticker in open_positions:
                pos = open_positions[ticker]

                if pos["exits_fired"] >= 1 and pos["shares_remaining"] > 0:
                    # Calculate new trailing stop
                    bars_since_entry = bars[bars.index >= pos.get("entry_time", bars.index[0])]
                    new_trail = calc_trailing_stop(
                        bars_since_entry,
                        pos["entry_price"],
                        pos["original_risk"],
                        TRAIL_MULTIPLIER,
                    )

                    # Only update if trail has moved up
                    if new_trail > pos["stop"]:
                        new_stop_id = update_trailing_stop(
                            ticker,
                            pos["shares_remaining"],
                            pos.get("stop_order_id"),
                            new_trail,
                        )
                        pos["stop"] = new_trail
                        pos["stop_order_id"] = new_stop_id

                # ── Exit check ───────────────────────────────────────────────
                exit_sig = detect_exit(bars, pos["entry_price"], pos["stop"], ticker)

                if exit_sig and pos["shares_remaining"] > 0:
                    pnl = (exit_sig.price - pos["entry_price"]) * pos["shares_remaining"]
                    daily_pnl += pnl
                    peak_daily_pnl = max(peak_daily_pnl, daily_pnl)

                    if pos["exits_fired"] == 0:
                        # First exit: sell core (60%), keep runner (40%)
                        shares_to_sell = int(pos["shares_total"] * FIRST_EXIT_SELL_FRAC)
                        shares_remaining = pos["shares_total"] - shares_to_sell
                        partial = True
                        reason = f"{exit_sig.reason}_partial_core"
                        pos["exits_fired"] += 1
                        pos["shares_remaining"] = shares_remaining
                        pos["entry_pnl_at_first_exit"] = pnl

                        submit_exit_order(
                            exit_sig,
                            current_qty=shares_to_sell,
                            stop_order_id=pos.get("stop_order_id"),
                        )
                        pos["stop_order_id"] = None

                        # Resubmit stop for runner
                        if shares_remaining > 0:
                            from alpaca.trading.requests import StopOrderRequest
                            from alpaca.trading.enums import OrderSide, TimeInForce
                            try:
                                tc = get_trading_client()
                                runner_stop = StopOrderRequest(
                                    symbol=ticker,
                                    qty=shares_remaining,
                                    side=OrderSide.SELL,
                                    time_in_force=TimeInForce.DAY,
                                    stop_price=round(pos["stop"], 2),
                                )
                                r = tc.submit_order(order_data=runner_stop)
                                pos["stop_order_id"] = r.id
                                print(f" Runner stop: {r.id} ({shares_remaining} shares @ ${pos['stop']})")
                            except Exception as e:
                                print(f" [WARN] Runner stop failed: {e}")

                        print(
                            f" {now_et.strftime('%H:%M')} EXIT (partial) {ticker} "
                            f"@${exit_sig.price} — sold {shares_to_sell}, "
                            f"keeping {shares_remaining} runner. P&L: ${pnl:,.2f}"
                        )

                    else:
                        # Second exit: sell runner
                        shares_to_sell = pos["shares_remaining"]
                        shares_remaining = 0
                        partial = False
                        reason = f"{exit_sig.reason}_full_runner"
                        pos["shares_remaining"] = 0

                        submit_exit_order(
                            exit_sig,
                            current_qty=shares_to_sell,
                            stop_order_id=pos.get("stop_order_id"),
                        )

                        print(
                            f" {now_et.strftime('%H:%M')} EXIT (runner) {ticker} "
                            f"@${exit_sig.price} — sold {shares_to_sell}. "
                            f"Total P&L: ${pnl:,.2f}"
                        )

                    send_exit_signal(exit_sig, pos["entry_price"], pnl)
                    log_signal({
                        "timestamp": now_et.isoformat(),
                        "ticker": ticker,
                        "action": "EXIT",
                        "price": exit_sig.price,
                        "reason": reason,
                        "risk_per_share": pnl / pos["shares_total"] if pos["shares_total"] else 0,
                        "shares": shares_to_sell,
                        "partial": partial,
                        "daily_pnl": daily_pnl,
                        "peak_daily_pnl": peak_daily_pnl,
                        "stop": pos["stop"],
                        "target_2r": pos["target_2r"],
                        "score": "",
                        "gap_pct": "",
                        "rel_vol": "",
                        "total_vol": "",
                    })

                    if shares_remaining == 0:
                        del open_positions[ticker]

                continue

            # ── Entry check ──────────────────────────────────────────────────
            if ticker in fired_entries:
                continue

            if stopped_for_day:
                continue

            live_candidate = dict(meta)
            live_candidate["bars"] = bars

            entry_sig = detect_entry(live_candidate)
            if entry_sig:
                total_entries += 1
                fired_entries.add(ticker)

                order_result = submit_entry_order(
                    entry_sig,
                    account_size=ACCOUNT_EQUITY,
                    risk_pct=RISK_PCT,
                )

                risk_per_share = entry_sig.risk_per_share
                if risk_per_share <= 0:
                    continue
                dollar_risk = ACCOUNT_EQUITY * RISK_PCT
                shares_total = max(1, int(dollar_risk / risk_per_share))

                open_positions[ticker] = {
                    "entry_price": entry_sig.price,
                    "entry_time": now_et,
                    "stop": entry_sig.stop,
                    "original_risk": risk_per_share,
                    "target_2r": entry_sig.target_2r,
                    "shares_total": shares_total,
                    "shares_remaining": shares_total,
                    "exits_fired": 0,
                    "entry_pnl_at_first_exit": 0.0,
                    "order_id": order_result["order_id"] if order_result else None,
                    "stop_order_id": order_result["stop_order_id"] if order_result else None,
                }

                print(
                    f" {now_et.strftime('%H:%M')} ENTRY {ticker} @${entry_sig.price}"
                    f" stop=${entry_sig.stop} 2R=${entry_sig.target_2r}"
                    f" shares={shares_total} risk=${dollar_risk:,.2f}"
                )
                send_entry_signal(entry_sig)
                log_signal({
                    "timestamp": now_et.isoformat(),
                    "ticker": ticker,
                    "action": "ENTRY",
                    "price": entry_sig.price,
                    "stop": entry_sig.stop,
                    "target_2r": entry_sig.target_2r,
                    "risk_per_share": entry_sig.risk_per_share,
                    "reason": entry_sig.reason,
                    "score": entry_sig.score,
                    "gap_pct": entry_sig.gap_pct,
                    "rel_vol": entry_sig.rel_vol,
                    "total_vol": entry_sig.total_vol,
                    "shares": shares_total,
                    "partial": False,
                    "daily_pnl": daily_pnl,
                    "peak_daily_pnl": peak_daily_pnl,
                })
            else:
                print(f" {now_et.strftime('%H:%M')} {ticker} no signal", flush=True)

        print(f" — sleeping {POLL_SEC}s …", flush=True)
        time.sleep(POLL_SEC)

    print(" Session monitor complete.")


if __name__ == "__main__":
    main()
