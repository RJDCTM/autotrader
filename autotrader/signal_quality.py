#!/usr/bin/env python3
"""
signal_quality.py — Signal Quality Tracker
Analyzes morning scan signals vs actual trades to measure signal effectiveness.

Usage:
    python signal_quality.py                   # View full report
    python signal_quality.py --export sigs.csv # Export raw signal data
"""

import argparse
import glob
import os
import sys
from datetime import datetime

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TRADE_LOG = "logs/trade_log.csv"


def load_all_scans() -> pd.DataFrame:
    """Load all morning scan CSV files."""
    patterns = ["logs/morning_scan_*.csv", "morning_scan_*.csv"]
    files = []
    for p in patterns:
        files.extend(glob.glob(p))
    
    if not files:
        return pd.DataFrame()
    
    frames = []
    for f in files:
        try:
            df = pd.read_csv(f)
            # Extract date from filename
            basename = os.path.basename(f)
            df["scan_file"] = basename
            frames.append(df)
        except:
            continue
    
    if not frames:
        return pd.DataFrame()
    
    return pd.concat(frames, ignore_index=True)


def load_trades() -> pd.DataFrame:
    if os.path.exists(TRADE_LOG):
        return pd.read_csv(TRADE_LOG)
    return pd.DataFrame()


def find_columns(df):
    """Find relevant columns with flexible naming."""
    cols = {}
    for c in df.columns:
        cl = c.lower().strip()
        if cl in ("ticker", "symbol"):
            cols["ticker"] = c
        elif cl in ("routed_to", "strategy", "best_strategy"):
            cols["strategy"] = c
        elif cl in ("best_score", "score", "signal_score", "bullish_score"):
            cols["score"] = c
        elif "momentum" in cl and "score" in cl:
            cols["momentum_score"] = c
        elif "swing" in cl and "score" in cl:
            cols["swing_score"] = c
        elif "reversion" in cl and "score" in cl:
            cols["reversion_score"] = c
    return cols


def analyze():
    """Run signal quality analysis."""
    scans = load_all_scans()
    trades = load_trades()
    
    print(f"\n{'='*70}")
    print(f"  SIGNAL QUALITY REPORT    {datetime.now().strftime('%Y-%m-%d')}")
    print(f"{'='*70}")
    
    if scans.empty:
        print("\n  No scan files found. Run morning_scan.py --save to start collecting data.")
        return
    
    cols = find_columns(scans)
    ticker_col = cols.get("ticker", "ticker")
    strategy_col = cols.get("strategy")
    score_col = cols.get("score")
    
    # If no explicit score column, try to compute from strategy scores
    if score_col is None:
        for alt in ["momentum_score", "swing_score", "reversion_score"]:
            if alt in cols:
                # Use max of available strategy scores
                score_cols = [cols[k] for k in ["momentum_score", "swing_score", "reversion_score"] if k in cols]
                if score_cols:
                    scans["_best_score"] = scans[score_cols].max(axis=1)
                    score_col = "_best_score"
                break
    
    scan_files = scans["scan_file"].nunique()
    total_signals = len(scans)
    unique_tickers = scans[ticker_col].nunique()
    
    print(f"\n  SIGNAL OVERVIEW")
    print(f"  {'─'*55}")
    print(f"  Scan files analyzed:  {scan_files}")
    print(f"  Total signals:        {total_signals}")
    print(f"  Unique tickers:       {unique_tickers}")
    
    # Cross-reference with trades
    traded_tickers = set()
    if not trades.empty and "ticker" in trades.columns:
        traded_tickers = set(trades["ticker"].str.upper().unique())
    
    signaled_tickers = set(scans[ticker_col].str.upper().unique())
    acted_on = signaled_tickers & traded_tickers
    
    conversion = len(acted_on) / len(signaled_tickers) * 100 if signaled_tickers else 0
    print(f"\n  CONVERSION")
    print(f"  {'─'*55}")
    print(f"  Signaled tickers:     {len(signaled_tickers)}")
    print(f"  Traded tickers:       {len(traded_tickers)}")
    print(f"  Conversion rate:      {conversion:.1f}%")
    
    # By strategy
    if strategy_col:
        print(f"\n  BY STRATEGY")
        print(f"  {'─'*55}")
        print(f"  {'Strategy':<20} {'Signals':>8} {'Unique':>8} {'Acted':>8} {'Conv%':>8}")
        
        for strat in scans[strategy_col].unique():
            subset = scans[scans[strategy_col] == strat]
            strat_tickers = set(subset[ticker_col].str.upper().unique())
            strat_acted = strat_tickers & traded_tickers
            strat_conv = len(strat_acted) / len(strat_tickers) * 100 if strat_tickers else 0
            
            print(f"  {str(strat):<20} {len(subset):>8} {len(strat_tickers):>8} "
                  f"{len(strat_acted):>8} {strat_conv:>7.1f}%")
    
    # By score range
    if score_col:
        print(f"\n  BY SCORE RANGE")
        print(f"  {'─'*55}")
        
        ranges = [(80, 100, "80-100 (Strong)"), (60, 79, "60-79 (Good)"),
                  (40, 59, "40-59 (Moderate)"), (0, 39, "0-39 (Weak)")]
        
        for lo, hi, label in ranges:
            subset = scans[(scans[score_col] >= lo) & (scans[score_col] <= hi)]
            if subset.empty:
                continue
            range_tickers = set(subset[ticker_col].str.upper().unique())
            range_acted = range_tickers & traded_tickers
            conv = len(range_acted) / len(range_tickers) * 100 if range_tickers else 0
            print(f"  {label:<20} {len(subset):>5} signals | "
                  f"{len(range_tickers):>3} tickers | {conv:.0f}% conversion")
    
    # Trade outcomes by signal score
    if not trades.empty and "pnl" in trades.columns and score_col:
        print(f"\n  TRADE OUTCOMES BY SIGNAL SCORE")
        print(f"  {'─'*55}")
        
        trade_tickers = trades[trades["side"] == "sell"].copy()
        if not trade_tickers.empty:
            # Match trades to their scan scores
            for lo, hi, label in ranges:
                scored_tickers = set(scans[(scans[score_col] >= lo) & (scans[score_col] <= hi)][ticker_col].str.upper())
                matched = trade_tickers[trade_tickers["ticker"].str.upper().isin(scored_tickers)]
                if matched.empty:
                    continue
                wins = len(matched[matched["pnl"] > 0])
                wr = wins / len(matched) * 100
                pnl = matched["pnl"].sum()
                print(f"  {label:<20} {len(matched)} trades | WR: {wr:.0f}% | P&L: ${pnl:+,.2f}")
    
    # Frequency analysis: most-signaled tickers
    print(f"\n  MOST FREQUENT SIGNALS (top 20)")
    print(f"  {'─'*55}")
    freq = scans[ticker_col].value_counts().head(20)
    for ticker, count in freq.items():
        traded = "✅" if ticker.upper() in traded_tickers else "  "
        print(f"  {traded} {ticker:<7} signaled {count}x")
    
    # Insights
    print(f"\n  💡 INSIGHTS")
    print(f"  {'─'*55}")
    if conversion < 20:
        print(f"  • Low conversion rate ({conversion:.0f}%). Consider lowering score threshold.")
    if strategy_col:
        zero_conv = [s for s in scans[strategy_col].unique()
                    if len(set(scans[scans[strategy_col]==s][ticker_col].str.upper()) & traded_tickers) == 0]
        if zero_conv:
            print(f"  • Strategies with 0 trades: {', '.join(str(s) for s in zero_conv)}")
    
    print(f"  • Data improves with more scans. Run daily for best results.")
    print(f"{'='*70}")


def export_data(filepath):
    """Export all signal data to CSV."""
    scans = load_all_scans()
    if scans.empty:
        print("  No data to export.")
        return
    scans.to_csv(filepath, index=False)
    print(f"  💾 Exported {len(scans)} signals to {filepath}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", type=str, help="Export signal data to CSV")
    args = parser.parse_args()
    
    if args.export:
        export_data(args.export)
    else:
        analyze()


if __name__ == "__main__":
    main()
