import csv
import os
from finvizfinance.screener.overview import Overview

def normalize_ticker(t: str) -> str:
    """
    Normalize Finviz tickers like AACVA -> ACVA, RRIOT -> RIOT.
    Simple rule: if it starts with two identical letters, drop the first.
    """
    t = t.strip().upper()
    if len(t) >= 2 and t[0] == t[1]:
        return t[1:]
    return t

def fetch_finviz_gappers():
    foverview = Overview()
    foverview.set_filter(filters_dict={
        "Price": "Over $5",
        "Gap": "Up 10%",
        "Average Volume": "Over 500K",
    })
    df = foverview.screener_view()
    # Normalize tickers
    tickers = [normalize_ticker(x) for x in df["Ticker"].tolist()]
    # De-duplicate
    return sorted(set(tickers))

def build_watchlist():
    tickers = fetch_finviz_gappers()
    print(f"Found {len(tickers)} normalized tickers: {tickers}")
    os.makedirs("data", exist_ok=True)
    path = os.path.join("data", "watchlist.csv")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["TICKER"])
        for t in tickers:
            writer.writerow([t])
    print(f"watchlist.csv updated at {path}")

if __name__ == "__main__":
    build_watchlist()