# First Pullback Scanner — Fully Automated GitHub Actions Setup

Automated implementation of the Ross Cameron "first pullback" momentum
day-trading scanner. Runs entirely free on GitHub Actions every trading
morning. No server required. Trades exclusively via Alpaca **paper trading**
— no real money is ever at risk.

## What it does

| Time (ET) | What happens |
|---|---|
| 7:05 AM | Single workflow fires: pre-market scan runs first |
| 7:05 AM | `main_scan.py` scans the **entire US equity market**, filters to the single **#1 gapper**, scores it against 5 pillars |
| Immediately after | `main_session.py` starts polling that one ticker every 60 seconds for a first-pullback entry |
| On entry | Discord alert with entry price, stop, 2R target, pillar score, position-size guide |
| On scale-in / partial exit / full exit | Discord alert with reason (stop hit, vol spike, topping tail, EMA/VWAP break, etc.) |
| Every 30 min | Discord P&L update (running daily P&L + peak P&L + signal count) |
| 10:00 AM | Hard cutoff — any open position is force-closed, no new entries fire |
| Run end | Session/scan logs uploaded as a GitHub Actions artifact (30-day retention) |

**Note:** this is a single-ticker system. It does not manage a multi-stock
watchlist during the live session — it commits to whichever stock wins the
pre-market scan and trades only that one.

## Strategy at a glance

- **Universe filter (5 pillars, need ≥4/5):** gap ≥10%, price $2–$20,
  relative volume ≥5x, today's volume ≥100K, float ≤20M shares.
- **Entry:** squeeze off a swing low (≥5%) → pullback retraces ≤50% of that
  move while closing above 9-EMA/VWAP → a "crossing candle" (breaks prior
  candle's high, closes green) triggers the buy. Stop = pullback low.
- **Sizing:** risk 1% of a $100,000 paper account on entry, 0.5% on a
  one-time scale-in when price makes a fresh high with another crossing
  candle.
- **Exit:** sell 60% on the first exit trigger (stop, volume-spike red
  candle, topping tail, close below 9-EMA/VWAP), hold 40% as a trailing-stop
  runner.
- **Risk breakers:** stop taking new entries if daily P&L gives back 50% of
  its peak, or hits a $2,000 max daily loss. Everything closes by 10:00 AM ET
  regardless.
- **Order safety:** every entry/scale-in checks the live bid/ask spread
  (rejects if >2%) before submitting.

## Free tools used

| Tool | What for | Cost |
|---|---|---|
| GitHub Actions | Scheduling + running the code (single `trading.yml` workflow) | Free (public repo) |
| Alpaca Markets | Real-time/historical bar data, market-wide asset list, paper order execution | Free (paper account) |
| Discord Webhook | Instant notifications on your phone | Free |
| yfinance | Float lookup (`floatShares`, falls back to `sharesOutstanding`) | Free |

---

## One-time setup (takes ~15 minutes)

### Step 1 — Fork or create this repo on GitHub

Make it **public** so GitHub Actions minutes are free.
Go to: https://github.com/new → paste this code in.

### Step 2 — Get a free Alpaca API key

1. Go to https://alpaca.markets → Sign Up (free)
2. After login: go to **Paper Trading** dashboard
3. Click **"Your API Keys"** → **"Generate New Key"**
4. Copy the **Key** and **Secret** — you only see the secret once

Alpaca free tier gives you:
- Real-time US stock data (IEX feed)
- Full historical minute bars
- The full tradable asset list (used for the full-market pre-market scan)
- Paper order execution
- No credit card needed

### Step 3 — Create a Discord webhook (for notifications)

1. Open Discord → go to any channel you want alerts in
2. Click the gear (⚙) next to the channel name → **Integrations** → **Webhooks**
3. Click **"New Webhook"** → copy the **Webhook URL**
4. It looks like: `https://discord.com/api/webhooks/123456/abcdef...`

### Step 4 — Add secrets to GitHub

In your GitHub repo: **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Add these three secrets (both jobs in the single workflow share them):

| Secret name | Value |
|---|---|
| `ALPACA_API_KEY` | Your Alpaca key from Step 2 |
| `ALPACA_SECRET_KEY` | Your Alpaca secret from Step 2 |
| `DISCORD_WEBHOOK_URL` | Your Discord webhook URL from Step 3 |

### Step 5 — Enable Actions

Go to your repo → **Actions** tab → click **"I understand my workflows, enable them"**.
The single `trading.yml` workflow runs automatically every weekday at 7:05 AM ET
(cron: `5 11 * * 1-5`) and can also be triggered manually via `workflow_dispatch`.

---

## Manual override watchlist

`data/watchlist.csv` is normally **auto-written** by `main_scan.py` after the
market-wide scan (it will contain just the #1 gapper). If the daily
candidates file is missing when the session monitor starts, it falls back to
reading whatever tickers are in this file and scores them live — so you can
drop tickers in here manually as a backup, but it's not required day-to-day
like it used to be.

## Known issues / things still worth fixing

- `main_scan.py` imports `python-dotenv` (`from dotenv import load_dotenv`)
  but `python-dotenv` is **not listed in `requirements.txt`** — will fail
  on a clean install unless run where it's already present.
- `notify.py`'s position-size guide example uses **£** while
  `main_session.py`'s `ACCOUNT_EQUITY` is in **$** — cosmetic but inconsistent.
- `.env` and files under `logs/` have been accidentally committed at least
  once despite being listed in `.gitignore` — worth double-checking history
  if the repo is ever made public, in case a real key leaked.
- Single-workflow design means a slow pre-market scan step delays the start
  of the session monitor within the same 180-minute job window.

## Files (current)

```
.github/workflows/
  trading.yml             — single workflow: installs deps, runs main_scan.py
                             then main_session.py, uploads logs/ as an artifact

scanner/
  __init__.py
  auto_screener.py        — scans the full US equity market (no static watchlist)
  pillars.py               — 5-pillar scoring + Alpaca client helpers
  signals.py               — first pullback entry/exit/scale-in/trailing-stop logic
  executor.py               — Alpaca order submission (entry/scale-in/exit/trailing stop)
  notify.py                 — Discord notification formatter (scan/entry/exit/P&L)

data/
  watchlist.csv            — auto-written daily; manual fallback list

logs/
  scan_YYYYMMDD.csv         — all scored candidates for the day
  candidates_YYYYMMDD.json  — the #1 gapper's full data (incl. bars)
  session_YYYYMMDD.csv      — every entry/scale-in/exit event

main_scan.py               — pre-market scan entrypoint
main_session.py            — session monitor entrypoint (7:05–10:00 AM ET)
test_order.py              — standalone script to test a buy/sell round-trip
requirements.txt
```
