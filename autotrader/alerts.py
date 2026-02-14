#!/usr/bin/env python3
"""
alerts.py — Continuous Position Alert System
Monitors positions and fires alerts when rules are breached.

Usage:
    python alerts.py              # One-time check
    python alerts.py --loop       # Continuous monitoring (Ctrl+C to exit)
    python alerts.py --interval 60  # Check every 60 seconds
"""

import argparse
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.config import load_config
from core.broker import AlpacaBroker
from monitor import monitor_all


def alert_loop(broker: AlpacaBroker, interval: int = 30):
    """Continuous monitoring loop."""
    print(f"\n  🔔 ALERT MODE — Checking every {interval}s (Ctrl+C to stop)")
    print("=" * 60)
    
    iteration = 0
    while True:
        try:
            iteration += 1
            print(f"\n  --- Check #{iteration} at {datetime.now().strftime('%H:%M:%S')} ---")
            monitor_all(broker)
            
            # Check if market is closing soon
            clock = broker.get_clock()
            if not clock["is_open"]:
                print("\n  Market is closed. Pausing alerts...")
                print("  Alerts will resume when market opens.")
                time.sleep(300)  # Check every 5 min when closed
                continue
            
            time.sleep(interval)
            
        except KeyboardInterrupt:
            print("\n\n  👋 Alert monitoring stopped.")
            break
        except Exception as e:
            print(f"\n  ⚠️ Error: {e}")
            time.sleep(interval)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="Continuous monitoring")
    parser.add_argument("--interval", type=int, default=30, help="Check interval in seconds")
    args = parser.parse_args()
    
    cfg = load_config()
    broker = AlpacaBroker(cfg.broker)
    
    if args.loop:
        alert_loop(broker, args.interval)
    else:
        monitor_all(broker)


if __name__ == "__main__":
    main()
