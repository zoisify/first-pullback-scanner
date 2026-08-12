"""
test_discord_signal.py

Dry-run test: simulates a first-pullback entry signal and sends the Discord notification
exactly as main_session.py would. Submits a real paper order to Alpaca using live prices.

Usage:
    python test_discord_signal.py              # Discord only
    python test_discord_signal.py --order      # Discord + submit paper order
"""

from dotenv import load_dotenv
load_dotenv()

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from scanner.signals import Signal
from scanner.notify import send_entry_signal
from scanner.executor import submit_entry_order, get_trading_client

ET = ZoneInfo("America/New_York")


def main():
    print("=== Fake Signal Test ===")
    print(f"Time: {datetime.now(ET).strftime('%Y-%m-%d %H:%M %Z')}\n")

    # Fetch live AAPL quote for realistic prices
    print("Fetching live AAPL quote...")
    try:
        client = get_trading_client()
        quote = client.get_latest_quote('AAPL')
        current_price = quote.ask_price  # use ask price as entry proxy
        
        # Calculate realistic stop and target based on current price
        entry_price = round(current_price, 2)
        stop_price = round(current_price * 0.99, 2)  # 1% below entry
        target_price = round(current_price * 1.02, 2)  # 2% above entry (approx 2R)
        
        print(f"  Current AAPL price: ${current_price}")
        print(f"  Simulated entry: ${entry_price}")
        print(f"  Simulated stop: ${stop_price}")
        print(f"  Simulated target 2R: ${target_price}\n")
    except Exception as e:
        print(f"  ✗ Failed to fetch quote: {e}")
        print("  Using fallback prices...\n")
        entry_price = 305.00
        stop_price = 302.00
        target_price = 311.00

    # Create a realistic entry signal for AAPL (real ticker, live prices)
    fake_signal = Signal(
        type="ENTRY",
        ticker="AAPL",  # real ticker
        price=entry_price,
        stop=stop_price,
        target_2r=target_price,
        risk_per_share=round(entry_price - stop_price, 2),
        reason="first_pullback_crossing_candle",
        pillars={
            "gap": "✓",
            "price": "✓",
            "rel_vol": "✓",
            "volume": "✓",
            "float": "?",
        },
        score=4,
        timestamp=datetime.now(ET),
        gap_pct=12.5,
        rel_vol=6.2,
        total_vol=2_500_000,
    )

    print(f"Simulated entry signal:")
    print(f"  Ticker: {fake_signal.ticker}")
    print(f"  Price: ${fake_signal.price}")
    print(f"  Stop: ${fake_signal.stop}")
    print(f"  Target 2R: ${fake_signal.target_2r}")
    print(f"  Score: {fake_signal.score}/5\n")

    # Send Discord notification (this is what main_session.py does)
    print("Sending Discord notification...")
    try:
        send_entry_signal(fake_signal)
        print("✓ Discord message sent\n")
    except Exception as e:
        print(f"✗ Discord failed: {e}\n")

    # Optionally submit a real paper order
    if "--order" in sys.argv:
        print("Submitting paper order to Alpaca...")
        result = submit_entry_order(fake_signal, account_size=10_000, risk_pct=0.01)
        if result:
            print(f"✓ Order submitted: {result['order_id']} — {result['shares']}x {fake_signal.ticker}")
            print("\nCheck your Alpaca paper dashboard: https://app.alpaca.markets/paper/dashboard")
        else:
            print("✗ Order failed (check secrets / API)")
    else:
        print("Skipping order submission (use --order flag to test)")

    print("\n=== Test Complete ===")


if __name__ == "__main__":
    main()