#!/usr/bin/env python3
"""
watchlist.py — Watchlist Manager
Manage the scanner watchlist. Add, remove, import from playbook.

Usage:
    python watchlist.py                       # Show watchlist
    python watchlist.py --add NVDA AMD META   # Add tickers
    python watchlist.py --remove TSLA         # Remove ticker
    python watchlist.py --import-playbook     # Import from playbook
"""

import argparse
import json
import os
import sys

import pandas as pd

WATCHLIST_FILE = "data/watchlist.csv"
PLAYBOOK_FILE = "data/playbook.json"

DEFAULT_TICKERS = [
    "NVDA", "AMD", "META", "GOOGL", "AAPL", "MSFT", "AMZN", "TSLA",
    "JPM", "GS", "CVX", "XOM", "SLB", "LLY", "UNH", "CAT", "DE",
    "GE", "BA", "V", "MA", "COST", "WMT", "HD", "CRM", "ORCL",
    "AVGO", "MU", "QCOM", "NFLX",
]


def load_watchlist() -> list:
    if os.path.exists(WATCHLIST_FILE):
        df = pd.read_csv(WATCHLIST_FILE)
        return df.iloc[:, 0].dropna().str.strip().str.upper().tolist()
    return DEFAULT_TICKERS.copy()


def save_watchlist(tickers: list):
    os.makedirs("data", exist_ok=True)
    df = pd.DataFrame({"ticker": sorted(set(tickers))})
    df.to_csv(WATCHLIST_FILE, index=False)


def show():
    tickers = load_watchlist()
    print(f"\n  WATCHLIST ({len(tickers)} tickers)")
    print(f"  {'─'*40}")
    for i in range(0, len(tickers), 6):
        row = tickers[i:i+6]
        print(f"  {' '.join(f'{t:<7}' for t in row)}")
    print(f"\n  File: {WATCHLIST_FILE}")


def add(new_tickers: list):
    current = load_watchlist()
    added = []
    for t in new_tickers:
        t = t.upper().strip()
        if t and t not in current:
            current.append(t)
            added.append(t)
    save_watchlist(current)
    print(f"  ✅ Added: {', '.join(added) if added else 'None (already in list)'}")
    print(f"  Total: {len(current)} tickers")


def remove(tickers: list):
    current = load_watchlist()
    removed = []
    for t in tickers:
        t = t.upper().strip()
        if t in current:
            current.remove(t)
            removed.append(t)
    save_watchlist(current)
    print(f"  ✅ Removed: {', '.join(removed) if removed else 'None (not in list)'}")


def import_playbook():
    if not os.path.exists(PLAYBOOK_FILE):
        print(f"  Playbook not found: {PLAYBOOK_FILE}")
        return
    with open(PLAYBOOK_FILE) as f:
        pb = json.load(f)
    
    current = load_watchlist()
    added = 0
    for ticker in pb:
        if ticker not in current:
            current.append(ticker)
            added += 1
    save_watchlist(current)
    print(f"  ✅ Imported {added} new tickers from playbook. Total: {len(current)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--add", nargs="+", type=str)
    parser.add_argument("--remove", nargs="+", type=str)
    parser.add_argument("--import-playbook", action="store_true")
    args = parser.parse_args()
    
    if args.add:
        add(args.add)
    elif args.remove:
        remove(args.remove)
    elif args.import_playbook:
        import_playbook()
    
    show()


if __name__ == "__main__":
    main()
