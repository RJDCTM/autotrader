#!/usr/bin/env python3
"""
sector_ranker.py — Sector Momentum Ranker
Ranks sector ETFs by momentum score for rotation strategy.

Usage:
    python sector_ranker.py              # Print sector rankings
    python sector_ranker.py --save       # Save to CSV
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.config import load_config
from core.broker import AlpacaBroker

SECTOR_ETFS = {
    "XLE": "Energy", "XLF": "Financials", "XLK": "Technology",
    "XLV": "Healthcare", "XLI": "Industrials", "XLP": "Cons Staples",
    "XLY": "Cons Disc", "XLB": "Materials", "XLU": "Utilities",
    "XLRE": "Real Estate", "XLC": "Communication",
}
BENCHMARKS = ["SPY", "QQQ", "IWM"]


def get_performance(broker: AlpacaBroker, ticker: str, days: int = 90) -> dict:
    """Get multi-timeframe performance for a ticker."""
    try:
        end = datetime.now()
        start = end - timedelta(days=days + 10)
        bars = broker.api.get_bars(ticker, "1Day",
                                    start=start.strftime("%Y-%m-%d"),
                                    end=end.strftime("%Y-%m-%d"), limit=days)
        if not bars:
            return None
        
        closes = [b.c for b in bars]
        volumes = [b.v for b in bars]
        
        current = closes[-1]
        result = {"ticker": ticker, "price": round(current, 2)}
        
        for period, label in [(5, "1w"), (21, "1m"), (63, "3m")]:
            if len(closes) > period:
                result[f"perf_{label}"] = round((current - closes[-period-1]) / closes[-period-1] * 100, 2)
            else:
                result[f"perf_{label}"] = 0
        
        # Relative volume
        if len(volumes) >= 20:
            result["vol_ratio"] = round(volumes[-1] / np.mean(volumes[-20:]), 2)
        else:
            result["vol_ratio"] = 1.0
        
        # Composite momentum score: weight recent more
        result["momentum_score"] = round(
            result.get("perf_1w", 0) * 0.4 +
            result.get("perf_1m", 0) * 0.35 +
            result.get("perf_3m", 0) * 0.25, 2
        )
        
        return result
    except Exception as e:
        return None


def rank_sectors(broker: AlpacaBroker) -> pd.DataFrame:
    """Rank all sectors by momentum."""
    results = []
    
    all_tickers = list(SECTOR_ETFS.keys()) + BENCHMARKS
    for ticker in all_tickers:
        perf = get_performance(broker, ticker)
        if perf:
            perf["sector"] = SECTOR_ETFS.get(ticker, "Benchmark")
            perf["is_benchmark"] = ticker in BENCHMARKS
            results.append(perf)
    
    df = pd.DataFrame(results)
    if df.empty:
        return df
    
    # Rank sectors (exclude benchmarks)
    sectors = df[~df["is_benchmark"]].copy()
    sectors["rank"] = sectors["momentum_score"].rank(ascending=False).astype(int)
    
    benchmarks = df[df["is_benchmark"]].copy()
    benchmarks["rank"] = 0
    
    return pd.concat([sectors.sort_values("rank"), benchmarks], ignore_index=True)


def display_rankings(df: pd.DataFrame):
    """Pretty print sector rankings."""
    print("\n" + "=" * 80)
    print(f"  SECTOR MOMENTUM RANKINGS    {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 80)
    
    if df.empty:
        print("  No data available.")
        return
    
    sectors = df[df["rank"] > 0]
    benches = df[df["rank"] == 0]
    
    # Top 3 = green, bottom 3 = red
    top_3 = set(sectors.head(3)["ticker"].values)
    bot_3 = set(sectors.tail(3)["ticker"].values)
    
    print(f"\n  {'Rank':<5} {'ETF':<6} {'Sector':<15} {'Price':>8} {'1W':>7} {'1M':>7} {'3M':>7} {'Score':>7}")
    print(f"  {'─'*70}")
    
    for _, row in sectors.iterrows():
        icon = "🟢" if row["ticker"] in top_3 else "🔴" if row["ticker"] in bot_3 else "  "
        print(f"  {icon}{int(row['rank']):>2}  {row['ticker']:<6} {row['sector']:<15} "
              f"${row['price']:>7.2f} {row.get('perf_1w',0):>+6.1f}% "
              f"{row.get('perf_1m',0):>+6.1f}% {row.get('perf_3m',0):>+6.1f}% "
              f"{row['momentum_score']:>+6.1f}")
    
    if not benches.empty:
        print(f"\n  BENCHMARKS")
        print(f"  {'─'*70}")
        for _, row in benches.iterrows():
            print(f"       {row['ticker']:<6} {row['sector']:<15} "
                  f"${row['price']:>7.2f} {row.get('perf_1w',0):>+6.1f}% "
                  f"{row.get('perf_1m',0):>+6.1f}% {row.get('perf_3m',0):>+6.1f}% "
                  f"{row['momentum_score']:>+6.1f}")
    
    # Rotation recommendation
    if not sectors.empty:
        top = sectors.iloc[0]
        bot = sectors.iloc[-1]
        print(f"\n  💡 ROTATION: Favor {top['ticker']} ({top['sector']}) | "
              f"Avoid {bot['ticker']} ({bot['sector']})")
    
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    
    cfg = load_config()
    broker = AlpacaBroker(cfg.broker)
    
    df = rank_sectors(broker)
    display_rankings(df)
    
    if args.save and not df.empty:
        os.makedirs("logs", exist_ok=True)
        fname = f"logs/sector_ranks_{datetime.now().strftime('%Y%m%d')}.csv"
        df.to_csv(fname, index=False)
        print(f"  💾 Saved: {fname}")


if __name__ == "__main__":
    main()
