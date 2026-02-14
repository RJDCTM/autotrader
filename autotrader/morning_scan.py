#!/usr/bin/env python3
"""
morning_scan.py — Live Stock Scanner
Scans watchlist for momentum, swing, and mean reversion setups.
Scores and ranks tickers, routes to strategies.

Usage:
    python morning_scan.py              # Print scan results
    python morning_scan.py --save       # Save to logs/morning_scan_YYYYMMDD.csv
    python morning_scan.py --top 10     # Show top 10 only
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# Add parent dir for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.config import load_config
from core.broker import AlpacaBroker

WATCHLIST_FILE = "data/watchlist.csv"
DEFAULT_TICKERS = [
    "NVDA", "AMD", "META", "GOOGL", "AAPL", "MSFT", "AMZN", "TSLA",
    "JPM", "GS", "CVX", "XOM", "SLB", "LLY", "UNH", "CAT", "DE",
    "GE", "BA", "V", "MA", "COST", "WMT", "HD", "CRM", "ORCL",
    "AVGO", "MU", "QCOM", "NFLX", "XLE", "XLF", "XLK", "XLV",
    "XLI", "XLP", "XLY", "XLB", "XLU", "XLRE", "XLC", "SPY", "QQQ", "IWM"
]


def load_watchlist() -> List[str]:
    """Load watchlist from file or use defaults."""
    if os.path.exists(WATCHLIST_FILE):
        df = pd.read_csv(WATCHLIST_FILE)
        col = df.columns[0]
        tickers = df[col].dropna().str.strip().str.upper().tolist()
        if tickers:
            return tickers
    return DEFAULT_TICKERS


def get_bars(broker: AlpacaBroker, ticker: str, days: int = 30) -> Optional[pd.DataFrame]:
    """Fetch daily bars from Alpaca."""
    try:
        end = datetime.now()
        start = end - timedelta(days=days + 10)  # extra buffer for weekends
        bars = broker.api.get_bars(
            ticker,
            "1Day",
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            limit=days,
        )
        if not bars:
            return None
        data = [{"date": b.t, "open": b.o, "high": b.h, "low": b.l,
                 "close": b.c, "volume": b.v} for b in bars]
        df = pd.DataFrame(data)
        if len(df) < 5:
            return None
        return df
    except Exception:
        return None


def compute_indicators(df: pd.DataFrame) -> Dict:
    """Compute technical indicators from daily bars."""
    close = df["close"].values
    volume = df["volume"].values
    high = df["high"].values
    low = df["low"].values
    
    current = close[-1]
    prev = close[-2] if len(close) > 1 else current
    
    # Moving averages
    sma5 = np.mean(close[-5:]) if len(close) >= 5 else current
    sma10 = np.mean(close[-10:]) if len(close) >= 10 else current
    sma20 = np.mean(close[-20:]) if len(close) >= 20 else current
    
    # ATR (10-day)
    tr = []
    for i in range(1, min(11, len(close))):
        tr.append(max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1])))
    atr = np.mean(tr) if tr else (high[-1] - low[-1])
    
    # RSI (14-day)
    if len(close) >= 15:
        deltas = np.diff(close[-15:])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains) if len(gains) > 0 else 0
        avg_loss = np.mean(losses) if len(losses) > 0 else 0.001
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
    else:
        rsi = 50
    
    # Volume ratio
    avg_vol = np.mean(volume[-20:]) if len(volume) >= 20 else np.mean(volume)
    vol_ratio = volume[-1] / avg_vol if avg_vol > 0 else 1.0
    
    # Performance
    perf_1d = ((current - prev) / prev * 100) if prev > 0 else 0
    perf_5d = ((current - close[-5]) / close[-5] * 100) if len(close) >= 5 else 0
    perf_20d = ((current - close[0]) / close[0] * 100) if len(close) >= 20 else perf_5d
    
    # Distance from MAs
    dist_sma5 = ((current - sma5) / sma5 * 100)
    dist_sma20 = ((current - sma20) / sma20 * 100)
    
    return {
        "price": round(current, 2),
        "change_pct": round(perf_1d, 2),
        "perf_5d": round(perf_5d, 2),
        "perf_20d": round(perf_20d, 2),
        "sma5": round(sma5, 2),
        "sma10": round(sma10, 2),
        "sma20": round(sma20, 2),
        "atr": round(atr, 2),
        "rsi": round(rsi, 1),
        "vol_ratio": round(vol_ratio, 2),
        "dist_sma5": round(dist_sma5, 2),
        "dist_sma20": round(dist_sma20, 2),
    }


def score_momentum(ind: Dict) -> float:
    """Score for momentum strategy (0-100)."""
    score = 0
    if ind["price"] > ind["sma5"] > ind["sma20"]:
        score += 30
    if ind["perf_5d"] > 2:
        score += min(20, ind["perf_5d"] * 4)
    if ind["rsi"] > 50 and ind["rsi"] < 75:
        score += 20
    if ind["vol_ratio"] > 1.2:
        score += min(15, (ind["vol_ratio"] - 1) * 15)
    if ind["change_pct"] > 0.5:
        score += min(15, ind["change_pct"] * 5)
    return min(100, max(0, score))


def score_swing(ind: Dict) -> float:
    """Score for swing trade (0-100)."""
    score = 0
    if ind["price"] > ind["sma20"]:
        score += 25
    if abs(ind["dist_sma20"]) < 3:
        score += 20  # near SMA20 = good swing entry
    if ind["rsi"] > 40 and ind["rsi"] < 60:
        score += 25  # not overbought or oversold
    if ind["perf_5d"] > 0 and ind["perf_5d"] < 5:
        score += 15
    if ind["vol_ratio"] > 0.8:
        score += 15
    return min(100, max(0, score))


def score_reversion(ind: Dict) -> float:
    """Score for mean reversion (0-100)."""
    score = 0
    if ind["dist_sma20"] < -3:
        score += min(30, abs(ind["dist_sma20"]) * 5)
    if ind["rsi"] < 35:
        score += 25
    elif ind["rsi"] < 45:
        score += 15
    if ind["change_pct"] < -1:
        score += min(20, abs(ind["change_pct"]) * 5)
    if ind["vol_ratio"] > 1.5:
        score += 15  # selling climax
    if ind["perf_5d"] < -5:
        score += 10
    return min(100, max(0, score))


def route_to_strategy(scores: Dict) -> str:
    """Pick best strategy based on scores."""
    best = max(scores, key=scores.get)
    return best


def scan(broker: AlpacaBroker, tickers: List[str], top_n: int = 50) -> pd.DataFrame:
    """Run full scan on watchlist."""
    results = []
    total = len(tickers)
    
    for i, ticker in enumerate(tickers):
        if (i + 1) % 10 == 0:
            print(f"  Scanning... {i+1}/{total}", end='\r')
        
        bars = get_bars(broker, ticker)
        if bars is None:
            continue
        
        ind = compute_indicators(bars)
        
        m_score = score_momentum(ind)
        s_score = score_swing(ind)
        r_score = score_reversion(ind)
        
        scores = {"momentum": m_score, "swing": s_score, "reversion": r_score}
        best_strategy = route_to_strategy(scores)
        best_score = scores[best_strategy]
        
        results.append({
            "ticker": ticker,
            "price": ind["price"],
            "change_pct": ind["change_pct"],
            "perf_5d": ind["perf_5d"],
            "rsi": ind["rsi"],
            "vol_ratio": ind["vol_ratio"],
            "dist_sma20": ind["dist_sma20"],
            "atr": ind["atr"],
            "momentum_score": round(m_score, 1),
            "swing_score": round(s_score, 1),
            "reversion_score": round(r_score, 1),
            "best_score": round(best_score, 1),
            "routed_to": best_strategy,
        })
    
    print(f"  Scanned {len(results)}/{total} tickers" + " " * 20)
    
    df = pd.DataFrame(results)
    if not df.empty:
        df = df.sort_values("best_score", ascending=False).reset_index(drop=True)
        if top_n:
            df = df.head(top_n)
    
    return df


def print_results(df: pd.DataFrame):
    """Pretty print scan results."""
    print()
    print("=" * 90)
    print(f"  RD AUTOTRADER MORNING SCAN    {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 90)
    
    if df.empty:
        print("  No results. Market may be closed.")
        return
    
    # Group by strategy
    for strategy in ["momentum", "swing", "reversion"]:
        subset = df[df["routed_to"] == strategy].head(10)
        if subset.empty:
            continue
        
        label = {"momentum": "⚡ MOMENTUM", "swing": "🔄 SWING", "reversion": "📉 MEAN REVERSION"}
        print(f"\n  {label.get(strategy, strategy.upper())} ({len(subset)} signals)")
        print(f"  {'Ticker':<8} {'Price':>8} {'Chg%':>7} {'5d%':>7} {'RSI':>6} {'VolR':>6} {'Score':>7}")
        print(f"  {'-'*55}")
        
        for _, row in subset.iterrows():
            chg_icon = "▲" if row["change_pct"] > 0 else "▼" if row["change_pct"] < 0 else "─"
            print(f"  {row['ticker']:<8} ${row['price']:>7.2f} {chg_icon}{row['change_pct']:>+5.1f}% "
                  f"{row['perf_5d']:>+5.1f}% {row['rsi']:>5.1f} {row['vol_ratio']:>5.2f} "
                  f"{row['best_score']:>6.1f}")
    
    print(f"\n  Total: {len(df)} signals | "
          f"Momentum: {len(df[df['routed_to']=='momentum'])} | "
          f"Swing: {len(df[df['routed_to']=='swing'])} | "
          f"Reversion: {len(df[df['routed_to']=='reversion'])}")
    print("=" * 90)


def main():
    parser = argparse.ArgumentParser(description="RD AutoTrader Morning Scanner")
    parser.add_argument("--save", action="store_true", help="Save results to CSV")
    parser.add_argument("--top", type=int, default=50, help="Show top N results")
    args = parser.parse_args()
    
    cfg = load_config()
    broker = AlpacaBroker(cfg.broker)
    
    tickers = load_watchlist()
    print(f"\n  Scanning {len(tickers)} tickers...")
    
    df = scan(broker, tickers, top_n=args.top)
    print_results(df)
    
    if args.save and not df.empty:
        os.makedirs("logs", exist_ok=True)
        fname = f"logs/morning_scan_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        df.to_csv(fname, index=False)
        print(f"\n  💾 Saved: {fname}")


if __name__ == "__main__":
    main()
