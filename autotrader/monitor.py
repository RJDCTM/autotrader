#!/usr/bin/env python3
"""
monitor.py — Position Rule Checker
Checks all open positions against rules: stops, targets, time limits, overextension.

Usage:
    python monitor.py                # Check all positions
    python monitor.py --ticker XLE   # Check single position
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.config import load_config
from core.broker import AlpacaBroker

TRADE_LOG = "logs/trade_log.csv"
SETTINGS_DIR = "settings"


def load_trade_log() -> pd.DataFrame:
    """Load trade log to check entry dates."""
    if os.path.exists(TRADE_LOG):
        return pd.read_csv(TRADE_LOG)
    return pd.DataFrame()


def load_settings(ticker: str) -> dict:
    """Load per-ticker optimized settings."""
    path = os.path.join(SETTINGS_DIR, f"{ticker}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    # Defaults
    return {
        "stop_pct": 5.0,
        "target1_pct": 3.0,
        "target2_pct": 6.0,
        "max_hold_days": 14,
        "trail_pct": 4.0,
    }


def check_position(position, settings: dict, entry_date=None) -> list:
    """Check a single position against rules. Returns list of alerts."""
    alerts = []
    ticker = position.ticker
    pnl_pct = position.unrealized_pnl_pct
    
    # Stop loss check
    stop_pct = settings.get("stop_pct", 5.0)
    if pnl_pct <= -stop_pct:
        alerts.append(f"🔴 {ticker}: STOP HIT — P&L {pnl_pct:+.1f}% (stop: -{stop_pct}%)")
    elif pnl_pct <= -(stop_pct * 0.7):
        alerts.append(f"🟡 {ticker}: NEAR STOP — P&L {pnl_pct:+.1f}% (stop: -{stop_pct}%)")
    
    # Target checks
    t1 = settings.get("target1_pct", 3.0)
    t2 = settings.get("target2_pct", 6.0)
    if pnl_pct >= t2:
        alerts.append(f"🎯 {ticker}: TARGET 2 HIT — P&L {pnl_pct:+.1f}% (T2: +{t2}%)")
    elif pnl_pct >= t1:
        alerts.append(f"🎯 {ticker}: TARGET 1 HIT — P&L {pnl_pct:+.1f}% (T1: +{t1}%)")
    
    # Time limit
    if entry_date:
        max_days = settings.get("max_hold_days", 14)
        days_held = (datetime.now() - entry_date).days
        if days_held >= max_days:
            alerts.append(f"⏰ {ticker}: MAX HOLD ({days_held}d / {max_days}d max) — Review or exit")
        elif days_held >= max_days * 0.8:
            alerts.append(f"⏰ {ticker}: APPROACHING MAX HOLD ({days_held}d / {max_days}d)")
    
    # Overextension (>12% above entry)
    if pnl_pct > 12:
        alerts.append(f"⚡ {ticker}: OVEREXTENDED +{pnl_pct:.1f}% — Consider scaling out")
    
    return alerts


def monitor_all(broker: AlpacaBroker, ticker_filter: str = None):
    """Check all positions."""
    print("\n" + "=" * 70)
    print(f"  POSITION MONITOR    {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)
    
    positions = broker.get_positions()
    if ticker_filter:
        positions = [p for p in positions if p.ticker == ticker_filter.upper()]
    
    if not positions:
        print("  No open positions to monitor.")
        return
    
    # Load trade log for entry dates
    log = load_trade_log()
    
    all_alerts = []
    for pos in positions:
        settings = load_settings(pos.ticker)
        
        # Find entry date from trade log
        entry_date = None
        if not log.empty and "ticker" in log.columns:
            entries = log[(log["ticker"] == pos.ticker) & (log["side"] == "buy")]
            if not entries.empty:
                try:
                    entry_date = pd.to_datetime(entries.iloc[-1].get("timestamp", None))
                except:
                    pass
        
        alerts = check_position(pos, settings, entry_date)
        all_alerts.extend(alerts)
    
    if all_alerts:
        print(f"\n  ⚠️  ALERTS ({len(all_alerts)})")
        print(f"  {'─'*60}")
        for a in all_alerts:
            print(f"  {a}")
    else:
        print(f"\n  ✅ All {len(positions)} positions within normal parameters.")
    
    # Summary
    print(f"\n  POSITION SUMMARY")
    print(f"  {'─'*60}")
    print(f"  {'Ticker':<7} {'P&L%':>8} {'Stop':>8} {'T1':>8} {'T2':>8} {'Status'}")
    for pos in sorted(positions, key=lambda x: x.unrealized_pnl_pct, reverse=True):
        s = load_settings(pos.ticker)
        status = "OK"
        if pos.unrealized_pnl_pct <= -s["stop_pct"]:
            status = "⛔ STOP"
        elif pos.unrealized_pnl_pct >= s["target2_pct"]:
            status = "🎯 T2"
        elif pos.unrealized_pnl_pct >= s["target1_pct"]:
            status = "🎯 T1"
        elif pos.unrealized_pnl_pct <= -(s["stop_pct"] * 0.7):
            status = "⚠️ NEAR"
        
        print(f"  {pos.ticker:<7} {pos.unrealized_pnl_pct:>+7.1f}% "
              f"{-s['stop_pct']:>+7.1f}% {s['target1_pct']:>+7.1f}% "
              f"{s['target2_pct']:>+7.1f}% {status}")
    
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", type=str, help="Check specific ticker")
    args = parser.parse_args()
    
    cfg = load_config()
    broker = AlpacaBroker(cfg.broker)
    monitor_all(broker, args.ticker)


if __name__ == "__main__":
    main()
