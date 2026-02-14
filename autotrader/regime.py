#!/usr/bin/env python3
"""
regime.py — Market Regime Detector
Classifies current market environment to adjust strategy behavior.
Regimes: STRONG_BULL, BULL, NEUTRAL, BEAR, CRISIS

Usage:
    python regime.py                # Quick regime check
    python regime.py --detailed     # Full analysis with breadth
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


def get_index_data(broker, ticker, days=100):
    """Fetch daily bars for regime analysis."""
    try:
        end = datetime.now()
        start = end - timedelta(days=days + 10)
        bars = broker.api.get_bars(ticker, "1Day",
                                    start=start.strftime("%Y-%m-%d"),
                                    end=end.strftime("%Y-%m-%d"), limit=days)
        closes = [b.c for b in bars]
        volumes = [b.v for b in bars]
        highs = [b.h for b in bars]
        lows = [b.l for b in bars]
        return {"close": closes, "volume": volumes, "high": highs, "low": lows}
    except:
        return None


def classify_regime(data):
    """Classify market regime from index data."""
    if not data or len(data["close"]) < 50:
        return "UNKNOWN", {}
    
    closes = np.array(data["close"])
    current = closes[-1]
    
    # Moving averages
    sma20 = np.mean(closes[-20:])
    sma50 = np.mean(closes[-50:])
    sma200 = np.mean(closes[-min(200, len(closes)):])
    
    # Performance
    perf_5d = (current - closes[-5]) / closes[-5] * 100 if len(closes) >= 5 else 0
    perf_20d = (current - closes[-20]) / closes[-20] * 100 if len(closes) >= 20 else 0
    perf_50d = (current - closes[-50]) / closes[-50] * 100 if len(closes) >= 50 else 0
    
    # Volatility (20-day realized vol, annualized)
    returns = np.diff(np.log(closes[-21:]))
    vol_20d = np.std(returns) * np.sqrt(252) * 100
    
    # Breadth proxy: days above SMA50 in last 20
    above_50 = sum(1 for c in closes[-20:] if c > np.mean(closes[-50:]))
    
    # RSI
    if len(closes) >= 15:
        deltas = np.diff(closes[-15:])
        gains = np.mean(np.where(deltas > 0, deltas, 0))
        losses = np.mean(np.where(deltas < 0, -deltas, 0))
        rsi = 100 - (100 / (1 + gains / (losses + 1e-10)))
    else:
        rsi = 50
    
    metrics = {
        "price": current, "sma20": round(sma20, 2), "sma50": round(sma50, 2),
        "sma200": round(sma200, 2),
        "perf_5d": round(perf_5d, 2), "perf_20d": round(perf_20d, 2),
        "perf_50d": round(perf_50d, 2),
        "vol_20d": round(vol_20d, 1), "rsi": round(rsi, 1),
        "above_50_ratio": above_50 / 20,
    }
    
    # Regime classification
    if current > sma20 > sma50 > sma200 and perf_20d > 3 and vol_20d < 20:
        regime = "STRONG_BULL"
    elif current > sma50 > sma200 and perf_20d > 0:
        regime = "BULL"
    elif current < sma50 and current < sma200 and perf_20d < -5:
        if vol_20d > 30:
            regime = "CRISIS"
        else:
            regime = "BEAR"
    elif current < sma50 and perf_20d < -3:
        regime = "BEAR"
    else:
        regime = "NEUTRAL"
    
    return regime, metrics


def get_regime_advice(regime):
    """Strategy adjustments for each regime."""
    advice = {
        "STRONG_BULL": {
            "icon": "🚀", "action": "Full throttle",
            "sizing": "100% normal sizing",
            "strategies": "Favor momentum_breakout, sector_etf",
            "stops": "Use trailing stops, let winners run",
        },
        "BULL": {
            "icon": "📈", "action": "Normal operations",
            "sizing": "100% normal sizing",
            "strategies": "All strategies active",
            "stops": "Standard stops and targets",
        },
        "NEUTRAL": {
            "icon": "➡️", "action": "Selective entries",
            "sizing": "75% sizing, tighter criteria",
            "strategies": "Favor swing and mean_reversion",
            "stops": "Tighter stops (-4% max)",
        },
        "BEAR": {
            "icon": "📉", "action": "Defensive",
            "sizing": "50% sizing, focus on quality",
            "strategies": "Mean reversion only, avoid momentum",
            "stops": "Very tight stops, quick exits",
        },
        "CRISIS": {
            "icon": "🔥", "action": "Capital preservation",
            "sizing": "25% sizing or CASH",
            "strategies": "No new longs, consider hedges",
            "stops": "Flatten all positions",
        },
    }
    return advice.get(regime, advice["NEUTRAL"])


def display_regime(regime, metrics, detailed=False):
    """Display regime analysis."""
    advice = get_regime_advice(regime)
    
    print(f"\n{'='*60}")
    print(f"  MARKET REGIME: {advice['icon']} {regime}")
    print(f"{'='*60}")
    
    print(f"\n  SPY Metrics:")
    print(f"  Price: ${metrics.get('price', 0):,.2f} | "
          f"SMA20: ${metrics.get('sma20', 0):,.2f} | "
          f"SMA50: ${metrics.get('sma50', 0):,.2f}")
    print(f"  5d: {metrics.get('perf_5d', 0):+.1f}% | "
          f"20d: {metrics.get('perf_20d', 0):+.1f}% | "
          f"50d: {metrics.get('perf_50d', 0):+.1f}%")
    print(f"  Vol(20d): {metrics.get('vol_20d', 0):.1f}% | "
          f"RSI: {metrics.get('rsi', 50):.1f}")
    
    print(f"\n  Strategy Adjustments:")
    print(f"  Action:     {advice['action']}")
    print(f"  Sizing:     {advice['sizing']}")
    print(f"  Strategies: {advice['strategies']}")
    print(f"  Stops:      {advice['stops']}")
    
    if detailed:
        # Also check VIX and IWM for breadth
        print(f"\n  Breadth Ratio (days above SMA50): {metrics.get('above_50_ratio', 0)*100:.0f}%")
    
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--detailed", action="store_true")
    args = parser.parse_args()
    
    cfg = load_config()
    broker = AlpacaBroker(cfg.broker)
    
    data = get_index_data(broker, "SPY")
    regime, metrics = classify_regime(data)
    display_regime(regime, metrics, detailed=args.detailed)


if __name__ == "__main__":
    main()
