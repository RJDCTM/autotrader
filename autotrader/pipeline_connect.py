#!/usr/bin/env python3
"""
pipeline_connect.py — Weekly Pipeline Bridge
Reads output from the weekly bullish setups pipeline and converts to autotrader signals.

Usage:
    python pipeline_connect.py --file data/weekly_bullish_setups.xlsx
    python pipeline_connect.py --file data/weekly_bullish_setups.xlsx --auto-route
"""

import argparse
import os
import sys
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PIPELINE_OUTPUT = "data/weekly_bullish_setups.xlsx"


def load_pipeline(filepath: str) -> pd.DataFrame:
    """Load pipeline output Excel file."""
    if not os.path.exists(filepath):
        print(f"  Pipeline file not found: {filepath}")
        print(f"  Run the weekly pipeline first, then copy output here.")
        return pd.DataFrame()
    
    # Try common sheet names
    for sheet in ["Top 50 Bullish", "Master Ranked", "Portfolio Ranked", 0]:
        try:
            df = pd.read_excel(filepath, sheet_name=sheet)
            if not df.empty:
                print(f"  Loaded sheet '{sheet}': {len(df)} rows")
                return df
        except:
            continue
    
    return pd.DataFrame()


def convert_to_signals(df: pd.DataFrame, min_score: float = 65) -> pd.DataFrame:
    """Convert pipeline output to autotrader signal format."""
    # Standardize column names
    rename = {}
    for col in df.columns:
        cl = col.lower().strip()
        if "ticker" in cl or "symbol" in cl:
            rename[col] = "ticker"
        elif "bullish" in cl and "score" in cl:
            rename[col] = "bullish_score"
        elif "crowding" in cl:
            rename[col] = "crowding_score"
        elif "surge" in cl:
            rename[col] = "surge_score"
        elif "structure" in cl or "urkel" in cl:
            rename[col] = "structure"
        elif "action" in cl and "recommend" in cl:
            rename[col] = "action"
        elif col.lower() == "price":
            rename[col] = "price"
        elif "sector" in cl:
            rename[col] = "sector"
    
    df = df.rename(columns=rename)
    
    if "ticker" not in df.columns:
        print("  Could not find ticker column in pipeline output.")
        return pd.DataFrame()
    
    # Filter by score
    if "bullish_score" in df.columns:
        df = df[df["bullish_score"] >= min_score].copy()
    
    # Map to strategy
    def map_strategy(row):
        struct = str(row.get("structure", "")).lower()
        if "momentum" in struct:
            return "momentum_breakout"
        elif "breakout" in struct:
            return "momentum_breakout"
        elif "reversal" in struct:
            return "mean_reversion"
        else:
            return "swing"
    
    df["suggested_strategy"] = df.apply(map_strategy, axis=1)
    
    return df


def display(df: pd.DataFrame):
    """Show pipeline signals."""
    print(f"\n{'='*70}")
    print(f"  PIPELINE SIGNALS    {datetime.now().strftime('%Y-%m-%d')}")
    print(f"{'='*70}")
    
    if df.empty:
        print("  No signals above threshold.")
        return
    
    print(f"\n  {'Ticker':<7} {'Price':>8} {'Score':>7} {'Structure':<15} {'Strategy':<20}")
    print(f"  {'─'*65}")
    
    for _, row in df.head(20).iterrows():
        print(f"  {row['ticker']:<7} ${row.get('price',0):>7.2f} "
              f"{row.get('bullish_score',0):>6.1f} "
              f"{str(row.get('structure','?')):<15} "
              f"{row.get('suggested_strategy','swing'):<20}")
    
    if len(df) > 20:
        print(f"  ... and {len(df) - 20} more")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str, default=PIPELINE_OUTPUT)
    parser.add_argument("--min-score", type=float, default=65)
    parser.add_argument("--auto-route", action="store_true")
    args = parser.parse_args()
    
    df = load_pipeline(args.file)
    if df.empty:
        return
    
    signals = convert_to_signals(df, args.min_score)
    display(signals)
    
    if args.auto_route and not signals.empty:
        # Save as scan-compatible format for run_strategies to consume
        os.makedirs("logs", exist_ok=True)
        fname = f"logs/morning_scan_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        signals.to_csv(fname, index=False)
        print(f"\n  💾 Saved as scan: {fname}")
        print(f"  Now run: python run_strategies.py")


if __name__ == "__main__":
    main()
