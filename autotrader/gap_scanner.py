#!/usr/bin/env python3
"""
gap_scanner.py — Pre-Market Gap Scanner
Detects overnight gaps, provides action recommendations for held positions vs watchlist.

Usage:
    python gap_scanner.py                    # Full scan (stocks + ETFs)
    python gap_scanner.py --etfs-only        # Sector ETFs only
    python gap_scanner.py --save             # Save to logs/gap_scan_YYYYMMDD.csv
    python gap_scanner.py --watchlist w.csv  # Custom ticker list
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.config import load_config
from core.broker import AlpacaBroker

STOPS_FILE = "logs/trailing_stops.json"

DEFAULT_STOCKS = [
    "NVDA", "AMD", "META", "GOOGL", "AAPL", "MSFT", "AMZN", "TSLA",
    "JPM", "GS", "CVX", "XOM", "SLB", "LLY", "UNH", "CAT", "DE",
    "GE", "BA", "V", "MA", "COST", "WMT", "HD", "CRM", "ORCL",
    "AVGO", "MU", "QCOM", "NFLX",
]
DEFAULT_ETFS = [
    "XLE", "XLF", "XLK", "XLV", "XLI", "XLP", "XLY", "XLB",
    "XLU", "XLRE", "XLC", "SPY", "QQQ", "IWM",
]


def get_held_tickers() -> set:
    """Get tickers with active trailing stops."""
    if os.path.exists(STOPS_FILE):
        with open(STOPS_FILE) as f:
            stops = json.load(f)
        return set(stops.keys())
    return set()


def scan_gap(broker: AlpacaBroker, ticker: str) -> dict:
    """Analyze gap for a single ticker."""
    try:
        end = datetime.now()
        start = end - timedelta(days=20)
        bars = broker.api.get_bars(ticker, "1Day",
                                    start=start.strftime("%Y-%m-%d"),
                                    end=end.strftime("%Y-%m-%d"), limit=15)
        if not bars or len(bars) < 2:
            return None
        
        data = [{"date": b.t, "open": b.o, "high": b.h, "low": b.l,
                 "close": b.c, "volume": b.v} for b in bars]
        df = pd.DataFrame(data)
        
        prev_close = df.iloc[-2]["close"]
        today_open = df.iloc[-1]["open"]
        current = df.iloc[-1]["close"]
        
        # ATR (10-day)
        tr = []
        for i in range(1, min(11, len(df))):
            tr.append(max(df.iloc[i]["high"] - df.iloc[i]["low"],
                         abs(df.iloc[i]["high"] - df.iloc[i-1]["close"]),
                         abs(df.iloc[i]["low"] - df.iloc[i-1]["close"])))
        atr = np.mean(tr) if tr else 1
        
        # Gap calculations
        open_gap_pct = (today_open - prev_close) / prev_close * 100
        running_gap_pct = (current - prev_close) / prev_close * 100
        gap_atr = abs(running_gap_pct / 100 * prev_close) / atr if atr > 0 else 0
        
        # Direction and severity
        if running_gap_pct > 0.1:
            direction = "UP"
        elif running_gap_pct < -0.1:
            direction = "DOWN"
        else:
            direction = "FLAT"
        
        abs_gap = abs(running_gap_pct)
        if abs_gap >= 5:
            severity = "EXTREME"
        elif abs_gap >= 3:
            severity = "LARGE"
        elif abs_gap >= 1.5:
            severity = "MODERATE"
        elif abs_gap >= 0.5:
            severity = "SMALL"
        else:
            severity = "NONE"
        
        return {
            "ticker": ticker,
            "prev_close": round(prev_close, 2),
            "open": round(today_open, 2),
            "current": round(current, 2),
            "gap_pct": round(running_gap_pct, 2),
            "gap_atr": round(gap_atr, 1),
            "direction": direction,
            "severity": severity,
        }
    except Exception:
        return None


def get_action(gap: dict, is_held: bool) -> str:
    """Get action recommendation."""
    direction = gap["direction"]
    severity = gap["severity"]
    
    if is_held:
        if direction == "DOWN" and severity in ("LARGE", "EXTREME"):
            return "CHECK STOPS - may gap through"
        elif direction == "DOWN" and severity == "MODERATE":
            return "Monitor - stop should hold"
        elif direction == "UP" and severity in ("LARGE", "EXTREME"):
            return "Consider scaling out into strength"
        elif direction == "UP" and severity == "MODERATE":
            return "Trail stop up"
        else:
            return "Hold"
    else:
        if direction == "DOWN" and severity in ("LARGE", "EXTREME"):
            return "Possible mean reversion bounce play"
        elif direction == "DOWN" and severity == "MODERATE":
            return "Watch for support hold then entry"
        elif direction == "UP" and severity in ("LARGE", "EXTREME"):
            return "DO NOT CHASE - wait for pullback"
        elif direction == "UP" and severity == "MODERATE":
            return "Breakout candidate if vol confirms"
        else:
            return "Watch"


def run_scan(broker, tickers, held_tickers):
    """Scan all tickers for gaps."""
    results = []
    total = len(tickers)
    
    for i, ticker in enumerate(tickers):
        if (i + 1) % 10 == 0:
            print(f"  Scanning... {i+1}/{total}", end='\r')
        
        gap = scan_gap(broker, ticker)
        if gap:
            gap["is_held"] = ticker in held_tickers
            gap["action"] = get_action(gap, gap["is_held"])
            results.append(gap)
    
    return results


def display_results(results, held_tickers):
    """Pretty print gap scan."""
    print(f"\n{'='*78}")
    print(f"  RD AUTOTRADER PRE-MARKET GAP SCANNER    {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*78}")
    
    if not results:
        print("  No data available. Market may be closed.")
        return
    
    # Held positions first
    held = [r for r in results if r["is_held"]]
    if held:
        print(f"\n  HELD POSITIONS - GAP ALERT ({len(held)})")
        print(f"  {'─'*70}")
        print(f"  {'Ticker':<8} {'Prev':>8} {'Open':>8} {'Now':>8} {'Gap%':>7} {'ATR':>5} {'Severity':<10} Action")
        for r in sorted(held, key=lambda x: abs(x["gap_pct"]), reverse=True):
            icon = "^" if r["direction"] == "UP" else "v" if r["direction"] == "DOWN" else " "
            print(f"  {icon} {r['ticker']:<6} ${r['prev_close']:>7.2f} ${r['open']:>7.2f} "
                  f"${r['current']:>7.2f} {r['gap_pct']:>+6.2f}% {r['gap_atr']:>4.1f}x "
                  f"{r['severity']:<10} {r['action']}")
    
    # Gap up
    gap_up = [r for r in results if not r["is_held"] and r["gap_pct"] >= 1.0]
    if gap_up:
        print(f"\n  GAP UP (>= 1%) ({len(gap_up)})")
        print(f"  {'─'*70}")
        print(f"  {'Ticker':<8} {'Prev':>8} {'Open':>8} {'Now':>8} {'Gap%':>7} {'ATR':>5} {'Severity':<10} Action")
        for r in sorted(gap_up, key=lambda x: x["gap_pct"], reverse=True):
            print(f"  ^ {r['ticker']:<6} ${r['prev_close']:>7.2f} ${r['open']:>7.2f} "
                  f"${r['current']:>7.2f} {r['gap_pct']:>+6.2f}% {r['gap_atr']:>4.1f}x "
                  f"{r['severity']:<10} {r['action']}")
    
    # Gap down
    gap_down = [r for r in results if not r["is_held"] and r["gap_pct"] <= -1.0]
    if gap_down:
        print(f"\n  GAP DOWN (<= -1%) ({len(gap_down)})")
        print(f"  {'─'*70}")
        print(f"  {'Ticker':<8} {'Prev':>8} {'Open':>8} {'Now':>8} {'Gap%':>7} {'ATR':>5} {'Severity':<10} Action")
        for r in sorted(gap_down, key=lambda x: x["gap_pct"]):
            print(f"  v {r['ticker']:<6} ${r['prev_close']:>7.2f} ${r['open']:>7.2f} "
                  f"${r['current']:>7.2f} {r['gap_pct']:>+6.2f}% {r['gap_atr']:>4.1f}x "
                  f"{r['severity']:<10} {r['action']}")
    
    # Flat/small
    flat = [r for r in results if not r["is_held"] and abs(r["gap_pct"]) < 1.0]
    if flat:
        print(f"\n  FLAT / SMALL MOVES ({len(flat)})")
        print(f"  {'─'*70}")
        for r in sorted(flat, key=lambda x: x["gap_pct"], reverse=True):
            held_mark = "* " if r["ticker"] in held_tickers else "  "
            print(f"  {held_mark}{r['ticker']:<7} ${r['current']:>8.2f}  {r['gap_pct']:>+6.2f}%")
    
    # Market breadth
    up = sum(1 for r in results if r["gap_pct"] > 0.1)
    down = sum(1 for r in results if r["gap_pct"] < -0.1)
    flat_count = len(results) - up - down
    avg_gap = np.mean([r["gap_pct"] for r in results])
    
    print(f"\n  MARKET BREADTH: {up} up  |  {down} down  |  {flat_count} flat  |  Avg gap: {avg_gap:+.2f}%")
    if avg_gap > 0.5:
        print(f"  > Bullish open - favor momentum trades")
    elif avg_gap < -0.5:
        print(f"  > Bearish open - favor mean reversion, watch stops")
    else:
        print(f"  > Neutral open - follow morning scan signals")
    
    print(f"\n  * = held position   ^ = gap up   v = gap down")
    print(f"  Best used pre-market or at open. Run BEFORE morning_scan.py")
    print(f"{'='*78}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--etfs-only", action="store_true")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--watchlist", type=str)
    args = parser.parse_args()
    
    cfg = load_config()
    broker = AlpacaBroker(cfg.broker)
    
    # Build ticker list
    if args.watchlist:
        if os.path.exists(args.watchlist):
            df = pd.read_csv(args.watchlist)
            tickers = df.iloc[:, 0].dropna().str.strip().str.upper().tolist()
        else:
            print(f"  Watchlist file not found: {args.watchlist}")
            return
    elif args.etfs_only:
        tickers = DEFAULT_ETFS
    else:
        tickers = DEFAULT_STOCKS + DEFAULT_ETFS
    
    held_tickers = get_held_tickers()
    
    print(f"\n  Scanning {len(tickers)} tickers for gaps...")
    print(f"  Held positions: {', '.join(held_tickers) if held_tickers else 'None'}")
    
    results = run_scan(broker, tickers, held_tickers)
    display_results(results, held_tickers)
    
    if args.save and results:
        os.makedirs("logs", exist_ok=True)
        fname = f"logs/gap_scan_{datetime.now().strftime('%Y%m%d')}.csv"
        pd.DataFrame(results).to_csv(fname, index=False)
        print(f"\n  💾 Saved: {fname}")


if __name__ == "__main__":
    main()
