# First Pullback Scanner — Fully Automated GitHub Actions Setup

Automated implementation of the Ross Cameron "first pullback" momentum
day-trading scanner. Runs entirely free on GitHub Actions every trading
morning. No server required.

## What it does

| Time (ET) | What happens |
|---|---|
| 7:00 AM | Pre-market scan fires — scores all tickers against 5 pillars |
| 7:00–10:00 AM | Session monitor polls every minute for entry signals |
| On signal | Discord notification with ticker, price, stop, target, pillar scores |
| 10:00 AM | Hard cutoff — no new signals sent |
| Market close | Daily log saved as GitHub Actions artifact |

## Free tools used

| Tool | What for | Cost |
|---|---|---|
| GitHub Actions | Scheduling + running the code | Free (public repo) |
| Alpaca Markets | Real-time + historical bar data | Free (paper account) |
| Discord Webhook | Instant notifications on your phone | Free |
| yfinance | Float/info fallback | Free |

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
- Real-time US stock data (IEX feed — covers ~80% of stocks)
- Full historical minute bars
- Paper order execution
- No credit card needed

### Step 3 — Create a Discord webhook (for notifications)

1. Open Discord → go to any channel you want alerts in
2. Click the gear (⚙) next to the channel name → **Integrations** → **Webhooks**
3. Click **"New Webhook"** → copy the **Webhook URL**
4. It looks like: `https://discord.com/api/webhooks/123456/abcdef...`

### Step 4 — Add secrets to GitHub

In your GitHub repo: **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Add these three secrets:

| Secret name | Value |
|---|---|
| `ALPACA_API_KEY` | Your Alpaca key from Step 2 |
| `ALPACA_SECRET_KEY` | Your Alpaca secret from Step 2 |
| `DISCORD_WEBHOOK_URL` | Your Discord webhook URL from Step 3 |

### Step 5 — Enable Actions

Go to your repo → **Actions** tab → click **"I understand my workflows, enable them"**

That's it. The workflow runs automatically every weekday morning.

---

## Expanding the watchlist

Edit `data/watchlist.csv` and add tickers — one per line.
Build it up by saving every Finviz gap-scan result each morning:
https://finviz.com/screener.ashx?v=111&f=sh_price_u20,sh_price_o2,ta_gap_u10&o=-gap

The more tickers in the watchlist, the better the scanner gets over time.

## Files

```
.github/workflows/
  premarket_scan.yml     — runs at 7:00 AM ET, scores all tickers
  session_monitor.yml    — runs 7:00–10:00 AM ET, fires entry signals

scanner/
  pillars.py             — 5 pillar universe filter
  signals.py             — first pullback entry/exit signal logic
  notify.py              — Discord notification formatter

data/
  watchlist.csv          — tickers to scan (edit this to expand)

main_scan.py             — pre-market scan entrypoint
main_session.py          — session monitor entrypoint
requirements.txt
```
