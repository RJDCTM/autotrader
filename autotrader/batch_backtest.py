#!/usr/bin/env python3
"""
batch_backtest.py — Multi-Ticker Playbook Generator
Backtests all watchlist tickers across strategies, generates optimal playbook.

Usage:
    python batch_backtest.py                      # Stocks only
    python batch_backtest.py --include-etfs       # Include sector ETFs
    python batch_backtest.py --save               # Save playbook
"""

import argparse
import json
import os
import sys
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.config import load_config
from core.broker import AlpacaBroker
from backtest import get_historical_bars, run_backtest, STRATEGIES
from morning_scan import load_watchlist

SECTOR_ETFS = ["XLE", "XLF", "XLK", "XLV", "XLI", "XLP", "XLY", "XLB", "XLU", "XLRE", "XLC"]
PLAYBOOK_FILE = "data/playbook.json"


def batch_test(broker, tickers, days=180):
    """Test each ticker against all strategies, pick the best."""
    results = []
    total = len(tickers)
    
    for idx, ticker in enumerate(tickers):
        print(f"  [{idx+1}/{total}] Testing {ticker}...", end='\r')
        
        df = get_historical_bars(broker, ticker, days)
        if df.empty or len(df) < 60:
            continue
        
        best_strategy = None
        best_fitness = -999
        best_stats = {}
        
        for strat_name in STRATEGIES:
            trades = run_backtest(df, strat_name)
            if trades.empty:
                continue
            
            wins = trades[trades["pnl"] > 0]
            win_rate = len(wins) / len(trades) * 100
            total_pnl = trades["pnl_pct"].sum()
            avg_pnl = trades["pnl_pct"].mean()
            
            fitness = (win_rate * 0.3 + min(total_pnl, 50) * 0.4 + min(len(trades), 20) * 0.3)
            
            if fitness > best_fitness:
                best_fitness = fitness
                best_strategy = strat_name
                best_stats = {
                    "trades": len(trades),
                    "win_rate": round(win_rate, 1),
                    "total_pnl_pct": round(total_pnl, 2),
                    "avg_pnl_pct": round(avg_pnl, 2),
                    "fitness": round(fitness, 2),
                }
        
        if best_strategy:
            is_etf = ticker in SECTOR_ETFS
            # Tier assignment based on fitness
            if best_fitness >= 25:
                tier = 1
            elif best_fitness >= 15:
                tier = 2
            else:
                tier = 3
            
            results.append({
                "ticker": ticker,
                "best_strategy": best_strategy,
                "tier": tier,
                "is_etf": is_etf,
                **best_stats,
            })
    
    print(f"  Tested {total} tickers across {len(STRATEGIES)} strategies" + " " * 20)
    return pd.DataFrame(results).sort_values("fitness", ascending=False)


def display_playbook(df):
    """Display the generated playbook."""
    print(f"\n{'='*75}")
    print(f"  BATCH PLAYBOOK    {datetime.now().strftime('%Y-%m-%d')}")
    print(f"{'='*75}")
    
    if df.empty:
        print("  No results.")
        return
    
    for tier in [1, 2, 3]:
        subset = df[df["tier"] == tier]
        if subset.empty:
            continue
        
        tier_label = {1: "🥇 TIER 1 (HIGH CONVICTION)", 2: "🥈 TIER 2 (MODERATE)",
                     3: "🥉 TIER 3 (SPECULATIVE)"}
        print(f"\n  {tier_label[tier]} ({len(subset)} tickers)")
        print(f"  {'Ticker':<7} {'Strategy':<20} {'Trades':>7} {'WR%':>6} {'P&L%':>8} {'Fitness':>8}")
        print(f"  {'─'*62}")
        
        for _, row in subset.iterrows():
            etf_tag = " [ETF]" if row.get("is_etf") else ""
            print(f"  {row['ticker']:<7} {row['best_strategy']:<20} "
                  f"{int(row['trades']):>7} {row['win_rate']:>5.1f}% "
                  f"{row['total_pnl_pct']:>+7.1f}% {row['fitness']:>7.1f}{etf_tag}")
    
    print(f"\n  Total: {len(df)} tickers | "
          f"T1: {len(df[df['tier']==1])} | T2: {len(df[df['tier']==2])} | T3: {len(df[df['tier']==3])}")
    print(f"{'='*75}")


def save_playbook(df):
    """Save playbook to JSON for other tools to consume."""
    os.makedirs("data", exist_ok=True)
    playbook = {}
    for _, row in df.iterrows():
        playbook[row["ticker"]] = {
            "strategy": row["best_strategy"],
            "tier": int(row["tier"]),
            "win_rate": row["win_rate"],
            "fitness": row["fitness"],
            "is_etf": bool(row.get("is_etf", False)),
        }
    with open(PLAYBOOK_FILE, "w") as f:
        json.dump(playbook, f, indent=2)
    print(f"  💾 Playbook saved: {PLAYBOOK_FILE}")
    
    # Also save CSV
    fname = f"logs/playbook_{datetime.now().strftime('%Y%m%d')}.csv"
    os.makedirs("logs", exist_ok=True)
    df.to_csv(fname, index=False)
    print(f"  💾 CSV saved: {fname}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-etfs", action="store_true")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--days", type=int, default=180)
    args = parser.parse_args()
    
    cfg = load_config()
    broker = AlpacaBroker(cfg.broker)
    
    tickers = load_watchlist()
    # Remove ETFs from base list, add back if requested
    tickers = [t for t in tickers if t not in SECTOR_ETFS]
    if args.include_etfs:
        tickers.extend(SECTOR_ETFS)
    
    tickers = list(set(tickers))
    print(f"\n  Batch testing {len(tickers)} tickers...")
    
    df = batch_test(broker, tickers, args.days)
    display_playbook(df)
    
    if args.save:
        save_playbook(df)


if __name__ == "__main__":
    main()
