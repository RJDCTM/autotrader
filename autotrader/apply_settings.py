#!/usr/bin/env python3
"""
apply_settings.py — Apply Optimized Settings
Reads playbook and optimizer results, writes per-ticker settings JSON files.

Usage:
    python apply_settings.py                         # Show current settings
    python apply_settings.py --apply-all-playbook    # Apply from playbook
    python apply_settings.py --ticker XLE --strategy swing  # Apply single
"""

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SETTINGS_DIR = "settings"
PLAYBOOK_FILE = "data/playbook.json"

# Default strategy-to-settings mapping
STRATEGY_DEFAULTS = {
    "momentum_breakout": {"stop_pct": 3.0, "target1_pct": 4.0, "target2_pct": 8.0, "trail_pct": 3.5, "max_hold_days": 5},
    "swing": {"stop_pct": 5.0, "target1_pct": 5.0, "target2_pct": 10.0, "trail_pct": 4.0, "max_hold_days": 10},
    "mean_reversion": {"stop_pct": 4.0, "target1_pct": 3.0, "target2_pct": 6.0, "trail_pct": 3.0, "max_hold_days": 5},
    "sector_etf": {"stop_pct": 4.0, "target1_pct": 4.0, "target2_pct": 8.0, "trail_pct": 3.5, "max_hold_days": 14},
    "earnings_run": {"stop_pct": 2.5, "target1_pct": 3.0, "target2_pct": 5.0, "trail_pct": 2.5, "max_hold_days": 3},
}


def show_current():
    """Show all current per-ticker settings."""
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    files = [f for f in os.listdir(SETTINGS_DIR) if f.endswith(".json")]
    
    if not files:
        print("  No ticker settings found. Run optimizer or apply-all-playbook first.")
        return
    
    print(f"\n  CURRENT SETTINGS ({len(files)} tickers)")
    print(f"  {'─'*60}")
    print(f"  {'Ticker':<7} {'Strategy':<20} {'Stop%':>6} {'T1%':>6} {'T2%':>6} {'Hold':>5}")
    
    for f in sorted(files):
        with open(os.path.join(SETTINGS_DIR, f)) as fh:
            s = json.load(fh)
        ticker = f.replace(".json", "")
        print(f"  {ticker:<7} {s.get('strategy','?'):<20} "
              f"{s.get('stop_pct',0):>5.1f}% {s.get('target1_pct',0):>5.1f}% "
              f"{s.get('target2_pct',0):>5.1f}% {s.get('max_hold_days','?'):>4}")


def apply_from_playbook():
    """Apply settings from batch playbook."""
    if not os.path.exists(PLAYBOOK_FILE):
        print(f"  Playbook not found: {PLAYBOOK_FILE}")
        print(f"  Run: python batch_backtest.py --save")
        return
    
    with open(PLAYBOOK_FILE) as f:
        playbook = json.load(f)
    
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    count = 0
    
    for ticker, info in playbook.items():
        strategy = info.get("strategy", "swing")
        defaults = STRATEGY_DEFAULTS.get(strategy, STRATEGY_DEFAULTS["swing"])
        
        # Check if optimizer has better settings
        opt_path = os.path.join(SETTINGS_DIR, f"{ticker}.json")
        if os.path.exists(opt_path):
            with open(opt_path) as fh:
                existing = json.load(fh)
            # Keep optimizer settings but update strategy/tier
            existing["strategy"] = strategy
            existing["tier"] = info.get("tier", 3)
            existing["updated_at"] = datetime.now().isoformat()
            settings = existing
        else:
            settings = {
                "ticker": ticker,
                "strategy": strategy,
                "tier": info.get("tier", 3),
                **defaults,
                "applied_at": datetime.now().isoformat(),
            }
        
        with open(os.path.join(SETTINGS_DIR, f"{ticker}.json"), "w") as fh:
            json.dump(settings, fh, indent=2)
        count += 1
    
    print(f"  ✅ Applied settings for {count} tickers from playbook.")
    show_current()


def apply_single(ticker, strategy):
    """Apply default settings for a single ticker."""
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    defaults = STRATEGY_DEFAULTS.get(strategy, STRATEGY_DEFAULTS["swing"])
    settings = {
        "ticker": ticker.upper(),
        "strategy": strategy,
        "tier": 2,
        **defaults,
        "applied_at": datetime.now().isoformat(),
    }
    path = os.path.join(SETTINGS_DIR, f"{ticker.upper()}.json")
    with open(path, "w") as f:
        json.dump(settings, f, indent=2)
    print(f"  ✅ Applied {strategy} settings for {ticker.upper()}")
    print(f"  {json.dumps(settings, indent=2)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply-all-playbook", action="store_true")
    parser.add_argument("--ticker", type=str)
    parser.add_argument("--strategy", type=str, default="swing")
    args = parser.parse_args()
    
    if args.apply_all_playbook:
        apply_from_playbook()
    elif args.ticker:
        apply_single(args.ticker, args.strategy)
    else:
        show_current()


if __name__ == "__main__":
    main()
