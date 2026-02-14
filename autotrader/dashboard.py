#!/usr/bin/env python3
"""
dashboard.py — View strategy buckets and performance

Usage:
    python dashboard.py              # Show all strategies
    python dashboard.py --sectors    # Show sector momentum rankings too
"""

import argparse
from core.strategy_manager import StrategyManager, rank_sectors_by_momentum
from core.broker import AlpacaBroker
from core.config import load_config


def main():
    parser = argparse.ArgumentParser(description="RD AutoTrader Strategy Dashboard")
    parser.add_argument("--sectors", action="store_true", help="Show sector rankings")
    args = parser.parse_args()

    # Initialize
    config = load_config()
    broker = AlpacaBroker(config.broker)
    mgr = StrategyManager()

    # Account info
    acct = broker.get_account()
    print(f"\nAlpaca Account: ${acct.equity:,.2f} equity | "
          f"${acct.cash:,.2f} cash | "
          f"Daily P&L: ${acct.daily_pnl:+,.2f}")

    # Strategy dashboard
    mgr.print_dashboard()

    # Sector rankings
    if args.sectors:
        print("\n\nSector Momentum Rankings:")
        print("  (Live data will be populated from pipeline runs)")
        print("  For now, run your weekly pipeline to generate ETF momentum data.")

    # Alpaca positions (cross-reference)
    positions = broker.get_positions()
    if positions:
        print(f"\nAlpaca Open Positions ({len(positions)}):")
        for p in sorted(positions, key=lambda x: x.unrealized_pnl_pct, reverse=True):
            print(f"  {p}")


if __name__ == "__main__":
    main()
