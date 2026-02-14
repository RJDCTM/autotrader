#!/usr/bin/env python3
"""
command_center.py — Unified Dashboard
Shows account, positions, alerts, and market status on one screen.

Usage:
    python command_center.py
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.config import load_config
from core.broker import AlpacaBroker


def display(broker: AlpacaBroker):
    """Show everything on one screen."""
    os.system('cls' if os.name == 'nt' else 'clear')
    
    print("=" * 70)
    print(f"  RD AUTOTRADER COMMAND CENTER    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    # Account
    acct = broker.get_account()
    clock = broker.get_clock()
    market_status = "🟢 OPEN" if clock["is_open"] else "🔴 CLOSED"
    
    print(f"\n  ACCOUNT                                   Market: {market_status}")
    print(f"  {'─'*60}")
    print(f"  Equity:      ${acct.equity:>12,.2f}")
    print(f"  Cash:        ${acct.cash:>12,.2f}")
    print(f"  Buying Power:${acct.buying_power:>12,.2f}")
    print(f"  Daily P&L:   ${acct.daily_pnl:>+12,.2f} ({acct.daily_pnl_pct:>+.2f}%)")
    
    # Risk status
    if acct.daily_pnl_pct <= -3.0:
        print(f"  ⚠️  CIRCUIT BREAKER: Daily loss exceeds -3%!")
    elif acct.daily_pnl_pct <= -2.0:
        print(f"  ⚠️  CAUTION: Daily loss exceeds -2%, reduce sizing")
    
    # Positions
    positions = broker.get_positions()
    print(f"\n  POSITIONS ({len(positions)})")
    print(f"  {'─'*60}")
    
    if positions:
        total_pnl = 0
        print(f"  {'Ticker':<7} {'Side':<6} {'Qty':>5} {'Entry':>9} {'Now':>9} {'P&L':>10} {'%':>7}")
        for p in sorted(positions, key=lambda x: x.unrealized_pnl, reverse=True):
            icon = "🟢" if p.unrealized_pnl >= 0 else "🔴"
            print(f"  {icon} {p.ticker:<5} {p.side:<5} {p.qty:>5.0f} "
                  f"${p.avg_entry_price:>8.2f} ${p.current_price:>8.2f} "
                  f"${p.unrealized_pnl:>+9.2f} {p.unrealized_pnl_pct:>+6.1f}%")
            total_pnl += p.unrealized_pnl
        print(f"  {'─'*60}")
        print(f"  Total Unrealized P&L: ${total_pnl:>+,.2f}")
    else:
        print("  No open positions.")
    
    # Open orders
    orders = broker.get_open_orders()
    if orders:
        print(f"\n  OPEN ORDERS ({len(orders)})")
        print(f"  {'─'*60}")
        for o in orders:
            print(f"  {o}")
    
    # Quick actions
    print(f"\n  QUICK ACTIONS")
    print(f"  {'─'*60}")
    print(f"  python morning_scan.py --save     Run morning scanner")
    print(f"  python alerts.py                  Check position alerts")
    print(f"  python trailing_stop.py --update-all  Update all stops")
    print(f"  python performance.py             View performance stats")
    print("=" * 70)


def main():
    cfg = load_config()
    broker = AlpacaBroker(cfg.broker)
    display(broker)


if __name__ == "__main__":
    main()
