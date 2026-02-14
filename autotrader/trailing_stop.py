#!/usr/bin/env python3
"""
trailing_stop.py — Systematic Trailing Stop Manager
4-phase ratcheting: INITIAL → T1_HIT (breakeven) → T2_HIT (50% trail) → RUNAWAY (70% trail)

Usage:
    python trailing_stop.py                         # Show all trailing stops
    python trailing_stop.py --init XLE 54.33 sector_etf  # Initialize position
    python trailing_stop.py --update-all            # Update all stops with live prices
    python trailing_stop.py --status XLE            # Check single position
"""

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

STOPS_FILE = "logs/trailing_stops.json"
HISTORY_FILE = "logs/trailing_stops_history.csv"

# Default phase settings per strategy
PHASE_CONFIGS = {
    "momentum_breakout": {
        "initial_stop_pct": 5.0, "t1_pct": 3.0, "t2_pct": 6.0,
        "t1_trail": 0.002, "t2_trail": 0.50, "runaway_trail": 0.70,
        "runaway_trigger_mult": 2.0,
    },
    "swing": {
        "initial_stop_pct": 5.0, "t1_pct": 4.0, "t2_pct": 8.0,
        "t1_trail": 0.002, "t2_trail": 0.50, "runaway_trail": 0.70,
        "runaway_trigger_mult": 2.0,
    },
    "mean_reversion": {
        "initial_stop_pct": 4.0, "t1_pct": 3.0, "t2_pct": 5.0,
        "t1_trail": 0.002, "t2_trail": 0.50, "runaway_trail": 0.65,
        "runaway_trigger_mult": 2.0,
    },
    "sector_etf": {
        "initial_stop_pct": 5.0, "t1_pct": 4.0, "t2_pct": 8.0,
        "t1_trail": 0.002, "t2_trail": 0.50, "runaway_trail": 0.70,
        "runaway_trigger_mult": 2.0,
    },
    "earnings_run": {
        "initial_stop_pct": 3.0, "t1_pct": 2.5, "t2_pct": 5.0,
        "t1_trail": 0.002, "t2_trail": 0.45, "runaway_trail": 0.60,
        "runaway_trigger_mult": 2.0,
    },
}


def load_stops() -> dict:
    if os.path.exists(STOPS_FILE):
        with open(STOPS_FILE) as f:
            return json.load(f)
    return {}


def save_stops(stops: dict):
    os.makedirs("logs", exist_ok=True)
    with open(STOPS_FILE, "w") as f:
        json.dump(stops, f, indent=2)


def log_change(ticker, field, old_val, new_val, phase):
    """Log stop changes to history CSV."""
    os.makedirs("logs", exist_ok=True)
    import csv
    row = [datetime.now().isoformat(), ticker, field, str(old_val), str(new_val), phase]
    exists = os.path.exists(HISTORY_FILE)
    with open(HISTORY_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow(["timestamp", "ticker", "field", "old_value", "new_value", "phase"])
        writer.writerow(row)


def init_position(ticker: str, entry_price: float, strategy: str = "swing"):
    """Initialize trailing stop for a new position."""
    stops = load_stops()
    config = PHASE_CONFIGS.get(strategy, PHASE_CONFIGS["swing"])
    
    stop_price = round(entry_price * (1 - config["initial_stop_pct"] / 100), 2)
    t1_target = round(entry_price * (1 + config["t1_pct"] / 100), 2)
    t2_target = round(entry_price * (1 + config["t2_pct"] / 100), 2)
    
    # Runaway trigger = entry + 2x the T2 gain
    t2_gain = t2_target - entry_price
    runaway_target = round(entry_price + config["runaway_trigger_mult"] * t2_gain, 2)
    
    stops[ticker.upper()] = {
        "entry": entry_price,
        "stop": stop_price,
        "phase": "INITIAL",
        "strategy": strategy,
        "t1_target": t1_target,
        "t2_target": t2_target,
        "runaway_target": runaway_target,
        "highest_price": entry_price,
        "config": config,
        "initialized_at": datetime.now().isoformat(),
        "last_updated": datetime.now().isoformat(),
    }
    
    save_stops(stops)
    print(f"  ✅ {ticker.upper()} trailing stop initialized:")
    print(f"     Entry: ${entry_price:.2f} | Stop: ${stop_price:.2f} | Phase: INITIAL")
    print(f"     T1: ${t1_target:.2f} | T2: ${t2_target:.2f} | Runaway: ${runaway_target:.2f}")


def update_stop(ticker: str, current_price: float):
    """Update trailing stop based on current price."""
    stops = load_stops()
    ticker = ticker.upper()
    
    if ticker not in stops:
        print(f"  {ticker} not tracked. Use --init first.")
        return
    
    pos = stops[ticker]
    old_stop = pos["stop"]
    old_phase = pos["phase"]
    entry = pos["entry"]
    config = pos.get("config", PHASE_CONFIGS["swing"])
    
    # Update highest price
    if current_price > pos["highest_price"]:
        pos["highest_price"] = current_price
    
    highest = pos["highest_price"]
    new_stop = old_stop
    new_phase = old_phase
    
    # Phase transitions
    if old_phase == "INITIAL":
        # Check T1 hit
        if current_price >= pos["t1_target"]:
            new_phase = "T1_HIT"
            # Ratchet to breakeven + small buffer
            new_stop = round(entry * (1 + config.get("t1_trail", 0.002)), 2)
            print(f"  [>>] {ticker}: T1 HIT! Stop → ${new_stop:.2f} (breakeven)")
    
    if old_phase == "T1_HIT" or (old_phase == "INITIAL" and new_phase == "T1_HIT"):
        if new_phase == "T1_HIT" or old_phase == "T1_HIT":
            # Check T2 hit
            if current_price >= pos["t2_target"]:
                new_phase = "T2_HIT"
                gain_from_entry = highest - entry
                new_stop = round(entry + gain_from_entry * config.get("t2_trail", 0.50), 2)
                print(f"  [>>] {ticker}: T2 HIT! Stop → ${new_stop:.2f} (50% trail)")
    
    if old_phase == "T2_HIT" or new_phase == "T2_HIT":
        if new_phase in ("T2_HIT",) or old_phase == "T2_HIT":
            # Check runaway
            if current_price >= pos["runaway_target"]:
                new_phase = "RUNAWAY"
                gain_from_entry = highest - entry
                new_stop = round(entry + gain_from_entry * config.get("runaway_trail", 0.70), 2)
                print(f"  [>>] {ticker}: RUNAWAY! Stop → ${new_stop:.2f} (70% trail)")
    
    # Within T2 or RUNAWAY: update trail
    if new_phase == "T2_HIT" and old_phase == "T2_HIT":
        gain_from_entry = highest - entry
        trail_stop = round(entry + gain_from_entry * config.get("t2_trail", 0.50), 2)
        if trail_stop > old_stop:
            new_stop = trail_stop
    
    if new_phase == "RUNAWAY" or old_phase == "RUNAWAY":
        new_phase = "RUNAWAY"
        gain_from_entry = highest - entry
        trail_stop = round(entry + gain_from_entry * config.get("runaway_trail", 0.70), 2)
        if trail_stop > new_stop:
            new_stop = trail_stop
    
    # Stop only moves UP
    new_stop = max(new_stop, old_stop)
    
    # Save
    pos["stop"] = new_stop
    pos["phase"] = new_phase
    pos["last_updated"] = datetime.now().isoformat()
    stops[ticker] = pos
    save_stops(stops)
    
    # Log changes
    if new_stop != old_stop:
        log_change(ticker, "stop", old_stop, new_stop, new_phase)
    if new_phase != old_phase:
        log_change(ticker, "phase", old_phase, new_phase, new_phase)
    
    # Risk from entry
    risk_pct = (new_stop - entry) / entry * 100
    pnl_pct = (current_price - entry) / entry * 100
    
    return {
        "ticker": ticker, "entry": entry, "current": current_price,
        "stop": new_stop, "phase": new_phase, "risk_pct": risk_pct,
        "pnl_pct": pnl_pct, "changed": new_stop != old_stop or new_phase != old_phase,
    }


def update_all(broker=None):
    """Update all tracked positions with live prices."""
    stops = load_stops()
    if not stops:
        print("  No positions tracked.")
        return
    
    if broker is None:
        from core.config import load_config
        from core.broker import AlpacaBroker
        cfg = load_config()
        broker = AlpacaBroker(cfg.broker)
    
    print(f"\n{'='*70}")
    print(f"  TRAILING STOP UPDATE    {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*70}")
    
    print(f"\n  {'Ticker':<7} {'Entry':>8} {'Now':>8} {'Stop':>8} {'Phase':<12} {'P&L%':>7} {'Risk%':>7}")
    print(f"  {'─'*65}")
    
    for ticker in list(stops.keys()):
        price = broker.get_latest_price(ticker)
        if price is None:
            print(f"  {ticker:<7} -- no price data --")
            continue
        
        result = update_stop(ticker, price)
        if result:
            icon = "🟢" if result["pnl_pct"] > 0 else "🔴"
            phase_icon = {"INITIAL": "[ ]", "T1_HIT": "[>]", "T2_HIT": "[>>]", "RUNAWAY": "[>>>]"}
            print(f"  {icon} {result['ticker']:<5} ${result['entry']:>7.2f} ${result['current']:>7.2f} "
                  f"${result['stop']:>7.2f} {phase_icon.get(result['phase'], '?'):<5} {result['phase']:<8} "
                  f"{result['pnl_pct']:>+6.1f}% {result['risk_pct']:>+6.1f}%")
    
    print(f"{'='*70}")


def show_status(ticker=None):
    """Show current trailing stop status."""
    stops = load_stops()
    
    if ticker:
        ticker = ticker.upper()
        if ticker in stops:
            pos = stops[ticker]
            print(f"\n  {ticker} Trailing Stop:")
            for k, v in pos.items():
                if k != "config":
                    print(f"    {k}: {v}")
        else:
            print(f"  {ticker} not tracked.")
        return
    
    print(f"\n  Tracked Positions: {len(stops)}")
    for t, pos in stops.items():
        risk = (pos["stop"] - pos["entry"]) / pos["entry"] * 100
        print(f"  {t}: Entry ${pos['entry']:.2f} | Stop ${pos['stop']:.2f} | "
              f"Phase: {pos['phase']} | Risk: {risk:+.1f}%")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", nargs=3, metavar=("TICKER", "ENTRY", "STRATEGY"),
                       help="Initialize: --init XLE 54.33 sector_etf")
    parser.add_argument("--update-all", action="store_true")
    parser.add_argument("--status", type=str, nargs="?", const="ALL")
    args = parser.parse_args()
    
    if args.init:
        ticker, entry, strategy = args.init
        init_position(ticker, float(entry), strategy)
    elif args.update_all:
        update_all()
    elif args.status:
        show_status(None if args.status == "ALL" else args.status)
    else:
        show_status()


if __name__ == "__main__":
    main()
