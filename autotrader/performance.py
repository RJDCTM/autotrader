#!/usr/bin/env python3
"""
performance.py — Performance Analytics
Tracks win rates, P&L, strategy effectiveness, and trade statistics.

Usage:
    python performance.py              # Show performance report
    python performance.py --snapshot   # Log current equity snapshot
    python performance.py --strategy momentum  # Filter by strategy
"""

import argparse
import os
import sys
from datetime import datetime

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TRADE_LOG = "logs/trade_log.csv"
EQUITY_LOG = "logs/equity_snapshots.csv"


def load_trades() -> pd.DataFrame:
    if os.path.exists(TRADE_LOG):
        df = pd.read_csv(TRADE_LOG)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df
    return pd.DataFrame()


def save_equity_snapshot(equity: float, cash: float, positions: int):
    """Save daily equity snapshot."""
    os.makedirs("logs", exist_ok=True)
    row = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": datetime.now().strftime("%H:%M"),
        "equity": equity,
        "cash": cash,
        "positions": positions,
    }
    if os.path.exists(EQUITY_LOG):
        df = pd.read_csv(EQUITY_LOG)
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    else:
        df = pd.DataFrame([row])
    df.to_csv(EQUITY_LOG, index=False)
    print(f"  💾 Equity snapshot saved: ${equity:,.2f}")


def compute_stats(trades: pd.DataFrame, label: str = "ALL"):
    """Compute and display trade statistics."""
    if trades.empty:
        print(f"\n  {label}: No trades found.")
        return
    
    # Separate buys and sells
    sells = trades[trades["side"] == "sell"].copy()
    if sells.empty or "pnl" not in sells.columns:
        # Try to compute P&L from trade pairs
        print(f"\n  {label}: {len(trades)} trades logged, P&L data not yet available.")
        print(f"  (P&L computed when positions are closed)")
        return
    
    wins = sells[sells["pnl"] > 0]
    losses = sells[sells["pnl"] <= 0]
    
    total_pnl = sells["pnl"].sum()
    win_rate = len(wins) / len(sells) * 100 if len(sells) > 0 else 0
    avg_win = wins["pnl"].mean() if not wins.empty else 0
    avg_loss = losses["pnl"].mean() if not losses.empty else 0
    
    # Profit factor
    gross_profit = wins["pnl"].sum() if not wins.empty else 0
    gross_loss = abs(losses["pnl"].sum()) if not losses.empty else 0.01
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    # Expectancy
    expectancy = (win_rate/100 * avg_win) + ((1 - win_rate/100) * avg_loss)
    
    # Max drawdown (sequential)
    cumulative = sells["pnl"].cumsum()
    peak = cumulative.cummax()
    drawdown = (cumulative - peak).min()
    
    print(f"\n  {label}")
    print(f"  {'─'*50}")
    print(f"  Total Trades:    {len(sells)}")
    print(f"  Win Rate:        {win_rate:.1f}%  ({len(wins)}W / {len(losses)}L)")
    print(f"  Total P&L:       ${total_pnl:>+,.2f}")
    print(f"  Avg Win:         ${avg_win:>+,.2f}")
    print(f"  Avg Loss:        ${avg_loss:>+,.2f}")
    print(f"  Profit Factor:   {profit_factor:.2f}")
    print(f"  Expectancy:      ${expectancy:>+,.2f} per trade")
    print(f"  Max Drawdown:    ${drawdown:>,.2f}")
    
    if not wins.empty:
        print(f"  Best Trade:      ${wins['pnl'].max():>+,.2f} ({wins.loc[wins['pnl'].idxmax(), 'ticker']})")
    if not losses.empty:
        print(f"  Worst Trade:     ${losses['pnl'].min():>+,.2f} ({losses.loc[losses['pnl'].idxmin(), 'ticker']})")


def show_report(strategy_filter: str = None):
    """Show full performance report."""
    print("\n" + "=" * 60)
    print(f"  PERFORMANCE REPORT    {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    
    trades = load_trades()
    
    if trades.empty:
        print("\n  No trades logged yet. Execute some trades first!")
        print("  Trade log location: logs/trade_log.csv")
        return
    
    # Overall stats
    compute_stats(trades, "OVERALL")
    
    # By strategy
    if "strategy" in trades.columns:
        strategies = trades["strategy"].dropna().unique()
        if strategy_filter:
            strategies = [s for s in strategies if strategy_filter.lower() in s.lower()]
        
        for strat in strategies:
            subset = trades[trades["strategy"] == strat]
            compute_stats(subset, f"STRATEGY: {strat.upper()}")
    
    # Equity curve
    if os.path.exists(EQUITY_LOG):
        eq = pd.read_csv(EQUITY_LOG)
        if not eq.empty:
            print(f"\n  EQUITY CURVE (last 10 snapshots)")
            print(f"  {'─'*50}")
            for _, row in eq.tail(10).iterrows():
                print(f"  {row['date']} {row.get('time', '')}  ${row['equity']:>12,.2f}  "
                      f"Pos: {row.get('positions', '?')}")
    
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", action="store_true", help="Save equity snapshot")
    parser.add_argument("--strategy", type=str, help="Filter by strategy name")
    args = parser.parse_args()
    
    if args.snapshot:
        try:
            from core.config import load_config
            from core.broker import AlpacaBroker
            cfg = load_config()
            broker = AlpacaBroker(cfg.broker)
            acct = broker.get_account()
            save_equity_snapshot(acct.equity, acct.cash, acct.open_position_count)
        except Exception as e:
            print(f"  Error taking snapshot: {e}")
    
    show_report(args.strategy)


if __name__ == "__main__":
    main()
