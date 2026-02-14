#!/usr/bin/env python3
"""
optimizer.py — Strategy Parameter Optimizer
Grid search over ATR multiples, hold periods to find optimal settings per ticker.

Usage:
    python optimizer.py --ticker XLE
    python optimizer.py --ticker NVDA --strategy momentum_breakout
    python optimizer.py --ticker XLE --save
"""

import argparse
import json
import os
import sys
from datetime import datetime
from itertools import product

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.config import load_config
from core.broker import AlpacaBroker
from backtest import get_historical_bars, run_backtest, STRATEGIES

SETTINGS_DIR = "settings"

# Parameter grid
PARAM_GRID = {
    "stop_atr": [1.0, 1.5, 2.0, 2.5, 3.0],
    "target_atr": [2.0, 3.0, 4.0, 5.0],
    "trail_atr": [1.5, 2.0, 2.5, 3.0],
    "max_hold": [3, 5, 7, 10, 14],
}


def optimize(broker, ticker, strategy, days=180):
    """Run grid search optimization."""
    df = get_historical_bars(broker, ticker, days)
    if df.empty or len(df) < 60:
        print(f"  Insufficient data for {ticker}")
        return None
    
    print(f"  Optimizing {ticker} / {strategy} over {len(df)} bars...")
    
    results = []
    combos = list(product(PARAM_GRID["stop_atr"], PARAM_GRID["target_atr"],
                          PARAM_GRID["trail_atr"], PARAM_GRID["max_hold"]))
    
    total = len(combos)
    for i, (stop, target, trail, hold) in enumerate(combos):
        if (i + 1) % 50 == 0:
            print(f"  Testing {i+1}/{total}...", end='\r')
        
        # Skip invalid combos
        if target <= stop:
            continue
        
        params = {"stop_atr": stop, "target_atr": target,
                  "trail_atr": trail, "max_hold": hold}
        
        trades = run_backtest(df, strategy, params)
        
        if trades.empty:
            continue
        
        wins = trades[trades["pnl"] > 0]
        win_rate = len(wins) / len(trades) * 100
        total_pnl = trades["pnl_pct"].sum()
        avg_pnl = trades["pnl_pct"].mean()
        
        # Composite fitness: balance win rate, total P&L, and trade count
        fitness = (win_rate * 0.3 + min(total_pnl, 50) * 0.4 + min(len(trades), 20) * 0.3)
        
        results.append({
            "stop_atr": stop, "target_atr": target, "trail_atr": trail,
            "max_hold": hold, "trades": len(trades), "win_rate": round(win_rate, 1),
            "total_pnl_pct": round(total_pnl, 2), "avg_pnl_pct": round(avg_pnl, 2),
            "fitness": round(fitness, 2),
        })
    
    print(f"  Tested {total} combinations" + " " * 20)
    
    if not results:
        return None
    
    results_df = pd.DataFrame(results).sort_values("fitness", ascending=False)
    return results_df


def display_and_save(ticker, strategy, results_df, save=False):
    """Show top results and optionally save best settings."""
    if results_df is None or results_df.empty:
        print("  No valid results found.")
        return
    
    print(f"\n  TOP 5 SETTINGS for {ticker} / {strategy.upper()}")
    print(f"  {'─'*70}")
    print(f"  {'Stop':>5} {'Target':>7} {'Trail':>6} {'Hold':>5} {'Trades':>7} "
          f"{'WR%':>6} {'P&L%':>7} {'Fitness':>8}")
    
    for _, row in results_df.head(5).iterrows():
        print(f"  {row['stop_atr']:>5.1f} {row['target_atr']:>7.1f} "
              f"{row['trail_atr']:>6.1f} {int(row['max_hold']):>5} "
              f"{int(row['trades']):>7} {row['win_rate']:>5.1f}% "
              f"{row['total_pnl_pct']:>+6.1f}% {row['fitness']:>7.1f}")
    
    if save:
        best = results_df.iloc[0]
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        settings = {
            "ticker": ticker,
            "strategy": strategy,
            "stop_atr": best["stop_atr"],
            "target_atr": best["target_atr"],
            "trail_atr": best["trail_atr"],
            "max_hold": int(best["max_hold"]),
            "stop_pct": round(best["stop_atr"] * 1.5, 1),  # Approximate % from ATR
            "target1_pct": round(best["target_atr"] * 1.0, 1),
            "target2_pct": round(best["target_atr"] * 1.5, 1),
            "trail_pct": round(best["trail_atr"] * 1.2, 1),
            "optimized_at": datetime.now().isoformat(),
            "win_rate": best["win_rate"],
            "fitness": best["fitness"],
        }
        path = os.path.join(SETTINGS_DIR, f"{ticker}.json")
        with open(path, "w") as f:
            json.dump(settings, f, indent=2)
        print(f"\n  💾 Saved: {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", type=str, required=True)
    parser.add_argument("--strategy", type=str, default="swing", choices=list(STRATEGIES.keys()))
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    
    cfg = load_config()
    broker = AlpacaBroker(cfg.broker)
    
    results = optimize(broker, args.ticker, args.strategy, args.days)
    display_and_save(args.ticker, args.strategy, results, save=args.save)


if __name__ == "__main__":
    main()
