#!/usr/bin/env python3
"""
report.py — Daily & Weekly Report Generator
Creates comprehensive reports of trading activity and performance.

Usage:
    python report.py --daily                 # Daily report to console
    python report.py --weekly --save         # Weekly report saved to file
    python report.py --daily --save --csv    # Daily with CSV export
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TRADE_LOG = "logs/trade_log.csv"
EQUITY_LOG = "logs/equity_snapshots.csv"
JOURNAL_FILE = "logs/journal.csv"


def load_data():
    """Load all data sources."""
    trades = pd.read_csv(TRADE_LOG) if os.path.exists(TRADE_LOG) else pd.DataFrame()
    equity = pd.read_csv(EQUITY_LOG) if os.path.exists(EQUITY_LOG) else pd.DataFrame()
    journal = pd.read_csv(JOURNAL_FILE) if os.path.exists(JOURNAL_FILE) else pd.DataFrame()
    
    if not trades.empty and "timestamp" in trades.columns:
        trades["timestamp"] = pd.to_datetime(trades["timestamp"])
    if not equity.empty and "date" in equity.columns:
        equity["date"] = pd.to_datetime(equity["date"])
    
    return trades, equity, journal


def generate_report(period: str = "daily"):
    """Generate report for given period."""
    trades, equity, journal = load_data()
    
    now = datetime.now()
    title = "DAILY" if period == "daily" else "WEEKLY"
    
    if period == "daily":
        cutoff = now - timedelta(days=1)
    else:
        cutoff = now - timedelta(days=7)
    
    print(f"\n{'='*70}")
    print(f"  {title} REPORT — {now.strftime('%Y-%m-%d')}")
    print(f"{'='*70}")
    
    # Equity curve
    if not equity.empty:
        recent_eq = equity[equity["date"] >= cutoff.strftime("%Y-%m-%d")]
        if not recent_eq.empty:
            start_eq = recent_eq.iloc[0]["equity"]
            end_eq = recent_eq.iloc[-1]["equity"]
            change = end_eq - start_eq
            change_pct = (change / start_eq * 100) if start_eq > 0 else 0
            
            print(f"\n  EQUITY")
            print(f"  {'─'*55}")
            print(f"  Start:  ${start_eq:>12,.2f}")
            print(f"  End:    ${end_eq:>12,.2f}")
            print(f"  Change: ${change:>+12,.2f} ({change_pct:+.2f}%)")
    
    # Trade activity
    if not trades.empty and "timestamp" in trades.columns:
        period_trades = trades[trades["timestamp"] >= cutoff]
        
        if not period_trades.empty:
            buys = period_trades[period_trades["side"] == "buy"]
            sells = period_trades[period_trades["side"] == "sell"]
            
            print(f"\n  TRADE ACTIVITY")
            print(f"  {'─'*55}")
            print(f"  Total Trades: {len(period_trades)}")
            print(f"  Buys:  {len(buys)}")
            print(f"  Sells: {len(sells)}")
            
            if "pnl" in sells.columns and not sells.empty:
                wins = sells[sells["pnl"] > 0]
                losses = sells[sells["pnl"] <= 0]
                print(f"  Wins:  {len(wins)} | Losses: {len(losses)}")
                print(f"  P&L:   ${sells['pnl'].sum():>+,.2f}")
            
            print(f"\n  Trades:")
            for _, t in period_trades.iterrows():
                pnl_str = f"P&L: ${t.get('pnl', 0):+,.2f}" if pd.notna(t.get("pnl")) else ""
                print(f"    {t.get('timestamp', '?')} | {t.get('side','?').upper()} "
                      f"{t.get('ticker','?')} @ ${t.get('price',0):.2f} "
                      f"x{t.get('qty',0):.0f} {pnl_str}")
    else:
        print(f"\n  No trades in this period.")
    
    # Journal summary
    if not journal.empty:
        recent_j = journal.tail(1) if period == "daily" else journal.tail(5)
        if not recent_j.empty:
            print(f"\n  JOURNAL NOTES")
            print(f"  {'─'*55}")
            for _, j in recent_j.iterrows():
                mood = j.get("mood", "?")
                print(f"  {j.get('date','?')} — Mood: {mood}/10 | {j.get('notes','')}")
    
    print(f"\n{'='*70}")
    return trades, equity


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily", action="store_true")
    parser.add_argument("--weekly", action="store_true")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--csv", action="store_true")
    args = parser.parse_args()
    
    period = "weekly" if args.weekly else "daily"
    trades, equity = generate_report(period)
    
    if args.save:
        os.makedirs("logs", exist_ok=True)
        date_str = datetime.now().strftime("%Y%m%d")
        
        if args.csv and not isinstance(trades, type(None)) and not trades.empty:
            fname = f"logs/report_{period}_{date_str}.csv"
            trades.to_csv(fname, index=False)
            print(f"  💾 CSV: {fname}")
        
        print(f"  💾 Report generated for {period}")


if __name__ == "__main__":
    main()
