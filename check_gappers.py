import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent / '.env')
import requests
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

symbols = [
    "WETO", "CAPR", "CGTL", "AKAN", "VALN", "SXTC",
    "HTFL", "LBGJ", "IMXI", "VERA", "ETON", "BOXL"
]

api_key = os.environ["ALPACA_API_KEY"]
api_secret = os.environ["ALPACA_SECRET_KEY"]

et = ZoneInfo("America/New_York")
now = datetime.now(et)
today = now.date()
previous_day = today - timedelta(days=1)

for symbol in symbols:
    print("\n" + "=" * 70)
    print(symbol)

    url = f"https://data.alpaca.markets/v2/stocks/{symbol}/bars"
    params = {
        "timeframe": "1Min",
        "start": f"{previous_day}T19:59:00Z",
        "end": f"{today}T13:30:00Z",
        "feed": "iex",
        "limit": 1000,
    }
    headers = {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": api_secret,
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        bars = response.json().get("bars", [])
        premarket = []
        close_bars = []

        for bar in bars:
            timestamp = datetime.fromisoformat(
                bar["t"].replace("Z", "+00:00")
            ).astimezone(et)

            if timestamp.date() == today and time(4, 0) <= timestamp.time() < time(9, 30):
                premarket.append((timestamp, bar))
            if timestamp.date() == previous_day and time(15, 59) <= timestamp.time() <= time(16, 1):
                close_bars.append((timestamp, bar))

        if not premarket:
            print("Premarket bar: NONE")
            print("Reason: no Alpaca IEX premarket bar returned")
            continue

        latest_time, latest_bar = premarket[-1]
        premarket_price = float(latest_bar["c"])
        premarket_volume = sum(int(bar["v"]) for _, bar in premarket)

        print("Premarket bar: FOUND")
        print(f"Latest premarket time: {latest_time:%Y-%m-%d %H:%M:%S ET}")
        print(f"Premarket price: ${premarket_price:.4f}")
        print(f"Premarket volume: {premarket_volume:,}")

        if not close_bars:
            print("Previous close: NONE")
            print("Reason: no previous regular-session close returned")
            continue

        _, close_bar = close_bars[-1]
        previous_close = float(close_bar["c"])
        gap_pct = ((premarket_price - previous_close) / previous_close) * 100

        print(f"Previous close: ${previous_close:.4f}")
        print(f"Calculated gap: {gap_pct:.2f}%")

        reasons = []
        if not 1 <= premarket_price <= 20:
            reasons.append("price outside $1-$20")
        if gap_pct < 5:
            reasons.append("gap below 5%")
        if premarket_volume < 100000:
            reasons.append("volume below 100,000")

        if reasons:
            print("Result: REJECTED")
            print("Reasons: " + "; ".join(reasons))
        else:
            print("Result: PASSES BASIC GAP/PRICE/VOLUME CHECKS")

    except Exception as error:
        print(f"ERROR: {error}")

