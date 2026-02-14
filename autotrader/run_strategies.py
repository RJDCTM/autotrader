#!/usr/bin/env python3
"""
run_strategies.py — Signal Router
Takes morning scan output and routes signals to appropriate strategy buckets.
Applies per-ticker settings and confirms before execution.

Usage:
    python run_strategies.py                    # Interactive mode
    python run_strategies.py --auto             # Auto-execute (no confirm)
    python run_strategies.py --dry-run          # Show what would execute
"""

import argparse
import glob
import json
import os
import sys
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.config import load_config
from core.broker import AlpacaBroker

SETTINGS_DIR = "settings"
PLAYBOOK_FILE = "data/playbook.json"


def load_latest_scan() -> pd.DataFrame:
    """Load the most recent morning scan CSV."""
    patterns = ["logs/morning_scan_*.csv", "morning_scan_*.csv"]
    files = []
    for p in patterns:
        files.extend(glob.glob(p))
    
    if not files:
        print("  No morning scan files found. Run: python morning_scan.py --save")
        return pd.DataFrame()
    
    latest = max(files, key=os.path.getmtime)
    print(f"  Loading: {latest}")
    return pd.read_csv(latest)


def load_playbook() -> dict:
    """Load playbook for tier/strategy info."""
    if os.path.exists(PLAYBOOK_FILE):
        with open(PLAYBOOK_FILE) as f:
            return json.load(f)
    return {}


def load_settings(ticker: str) -> dict:
    """Load per-ticker settings."""
    path = os.path.join(SETTINGS_DIR, f"{ticker}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def route_signals(scan_df: pd.DataFrame, broker: AlpacaBroker, min_score: float = 60):
    """Route scan signals to strategies."""
    if scan_df.empty:
        return []
    
    playbook = load_playbook()
    positions = {p.ticker: p for p in broker.get_positions()}
    
    routed = []
    for _, row in scan_df.iterrows():
        ticker = row["ticker"]
        best_score = row.get("best_score", 0)
        strategy = row.get("routed_to", "swing")
        
        # Skip low scores
        if best_score < min_score:
            continue
        
        # Skip already held
        if ticker in positions:
            continue
        
        # Get playbook info
        pb = playbook.get(ticker, {})
        settings = load_settings(ticker)
        
        # Override strategy from playbook if available
        if pb.get("strategy"):
            strategy = pb["strategy"]
        
        tier = pb.get("tier", settings.get("tier", 3))
        
        routed.append({
            "ticker": ticker,
            "price": row.get("price", 0),
            "score": best_score,
            "strategy": strategy,
            "tier": tier,
            "rsi": row.get("rsi", 50),
            "vol_ratio": row.get("vol_ratio", 1.0),
            "stop_pct": settings.get("stop_pct", 5.0),
            "target1_pct": settings.get("target1_pct", 4.0),
        })
    
    # Sort by tier (lower = better) then score
    routed.sort(key=lambda x: (x["tier"], -x["score"]))
    return routed


def display_and_confirm(signals: list, dry_run: bool = False, auto: bool = False):
    """Display routed signals and optionally execute."""
    print(f"\n{'='*70}")
    print(f"  ROUTED SIGNALS ({len(signals)})")
    print(f"{'='*70}")
    
    if not signals:
        print("  No actionable signals above threshold.")
        return
    
    for i, sig in enumerate(signals):
        tier_icon = {1: "🥇", 2: "🥈", 3: "🥉"}.get(sig["tier"], "  ")
        print(f"  {tier_icon} {i+1}. {sig['ticker']:<7} ${sig['price']:>8.2f} "
              f"Score:{sig['score']:>5.1f} Strategy:{sig['strategy']:<20} "
              f"Stop:{sig['stop_pct']:.1f}% T1:{sig['target1_pct']:.1f}%")
    
    if dry_run:
        print(f"\n  [DRY RUN] No trades executed.")
        return
    
    if not auto:
        print(f"\n  Enter signal numbers to execute (comma-separated), or 'q' to skip:")
        choice = input("  > ").strip()
        if choice.lower() == 'q':
            return
        
        try:
            indices = [int(x.strip()) - 1 for x in choice.split(",")]
        except:
            print("  Invalid input.")
            return
    else:
        # Auto mode: execute tier 1 and 2 only
        indices = [i for i, s in enumerate(signals) if s["tier"] <= 2]
    
    for idx in indices:
        if 0 <= idx < len(signals):
            sig = signals[idx]
            print(f"\n  ⚡ Executing: {sig['ticker']} @ ~${sig['price']:.2f} ({sig['strategy']})")
            # This would call run.py or broker directly
            print(f"  → Run: python run.py --ticker {sig['ticker']} --strategy {sig['strategy']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--min-score", type=float, default=60)
    args = parser.parse_args()
    
    cfg = load_config()
    broker = AlpacaBroker(cfg.broker)
    
    scan = load_latest_scan()
    signals = route_signals(scan, broker, args.min_score)
    display_and_confirm(signals, dry_run=args.dry_run, auto=args.auto)


if __name__ == "__main__":
    main()
