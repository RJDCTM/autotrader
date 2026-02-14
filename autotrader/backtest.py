#!/usr/bin/env python3
"""
backtest.py — Historical Strategy Backtester
Tests strategies against historical data with realistic execution modeling.

Usage:
    python backtest.py --ticker XLE --strategy momentum_breakout --days 180
    python backtest.py --ticker NVDA --strategy swing --days 90
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

STRATEGIES = {
    "momentum_breakout": {"stop_atr": 1.5, "target_atr": 3.0, "trail_atr": 2.0, "max_hold": 5},
    "swing": {"stop_atr": 2.0, "target_atr": 4.0, "trail_atr": 2.5, "max_hold": 10},
    "mean_reversion": {"stop_atr": 2.5, "target_atr": 2.0, "trail_atr": 1.5, "max_hold": 5},
    "sector_etf": {"stop_atr": 2.0, "target_atr": 3.0, "trail_atr": 2.0, "max_hold": 14},
    "earnings_run": {"stop_atr": 1.0, "target_atr": 2.0, "trail_atr": 1.5, "max_hold": 3},
}


def get_historical_bars(broker, ticker, days=200):
    """Fetch historical daily bars."""
    try:
        end = datetime.now()
        start = end - timedelta(days=days + 30)
        bars = broker.api.get_bars(ticker, "1Day",
                                    start=start.strftime("%Y-%m-%d"),
                                    end=end.strftime("%Y-%m-%d"), limit=days)
        data = [{"date": b.t, "open": b.o, "high": b.h, "low": b.l,
                 "close": b.c, "volume": b.v} for b in bars]
        return pd.DataFrame(data)
    except Exception as e:
        print(f"  Error fetching {ticker}: {e}")
        return pd.DataFrame()


def compute_atr(df, period=10):
    """Compute Average True Range."""
    tr = pd.DataFrame()
    tr["hl"] = df["high"] - df["low"]
    tr["hc"] = abs(df["high"] - df["close"].shift(1))
    tr["lc"] = abs(df["low"] - df["close"].shift(1))
    tr["tr"] = tr[["hl", "hc", "lc"]].max(axis=1)
    return tr["tr"].rolling(period).mean()


def run_backtest(df, strategy_name, params=None):
    """Run backtest simulation."""
    if params is None:
        params = STRATEGIES.get(strategy_name, STRATEGIES["swing"])
    
    df = df.copy().reset_index(drop=True)
    df["atr"] = compute_atr(df)
    df["sma20"] = df["close"].rolling(20).mean()
    df["sma50"] = df["close"].rolling(50).mean()
    
    # RSI
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-10)
    df["rsi"] = 100 - (100 / (1 + rs))
    
    trades = []
    position = None
    
    for i in range(50, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        atr = row["atr"]
        
        if np.isnan(atr) or atr <= 0:
            continue
        
        # EXIT LOGIC (if in position)
        if position:
            # Check stop
            if row["low"] <= position["stop"]:
                pnl = position["stop"] - position["entry"]
                trades.append({**position, "exit": position["stop"], "exit_date": row["date"],
                              "pnl": pnl, "pnl_pct": pnl/position["entry"]*100,
                              "days_held": i - position["bar_idx"], "exit_reason": "stop"})
                position = None
                continue
            
            # Check target
            if row["high"] >= position["target"]:
                pnl = position["target"] - position["entry"]
                trades.append({**position, "exit": position["target"], "exit_date": row["date"],
                              "pnl": pnl, "pnl_pct": pnl/position["entry"]*100,
                              "days_held": i - position["bar_idx"], "exit_reason": "target"})
                position = None
                continue
            
            # Trail stop up
            new_trail = row["close"] - params["trail_atr"] * atr
            if new_trail > position["stop"]:
                position["stop"] = new_trail
            
            # Time exit
            if i - position["bar_idx"] >= params["max_hold"]:
                pnl = row["close"] - position["entry"]
                trades.append({**position, "exit": row["close"], "exit_date": row["date"],
                              "pnl": pnl, "pnl_pct": pnl/position["entry"]*100,
                              "days_held": params["max_hold"], "exit_reason": "time"})
                position = None
                continue
        
        # ENTRY LOGIC (if flat)
        if position is None:
            entry_signal = False
            
            if strategy_name == "momentum_breakout":
                entry_signal = (row["close"] > row["sma20"] > row["sma50"] and
                               row["rsi"] > 50 and row["rsi"] < 75 and
                               row["close"] > prev["high"])
            
            elif strategy_name == "swing":
                entry_signal = (row["close"] > row["sma20"] and
                               abs(row["close"] - row["sma20"]) / row["sma20"] < 0.03 and
                               row["rsi"] > 40 and row["rsi"] < 60)
            
            elif strategy_name == "mean_reversion":
                entry_signal = (row["rsi"] < 35 and
                               row["close"] < row["sma20"] and
                               row["close"] > row["sma50"] * 0.92)
            
            elif strategy_name == "sector_etf":
                entry_signal = (row["close"] > row["sma20"] and
                               row["sma20"] > row["sma50"] and
                               row["rsi"] > 45)
            
            elif strategy_name == "earnings_run":
                entry_signal = (row["close"] > prev["high"] and
                               row["volume"] > df["volume"].iloc[i-20:i].mean() * 1.5)
            
            if entry_signal:
                entry = row["close"]
                stop = entry - params["stop_atr"] * atr
                target = entry + params["target_atr"] * atr
                position = {
                    "entry": entry, "stop": stop, "target": target,
                    "entry_date": row["date"], "bar_idx": i,
                    "strategy": strategy_name
                }
    
    # Close open position at end
    if position:
        last = df.iloc[-1]
        pnl = last["close"] - position["entry"]
        trades.append({**position, "exit": last["close"], "exit_date": last["date"],
                      "pnl": pnl, "pnl_pct": pnl/position["entry"]*100,
                      "days_held": len(df) - 1 - position["bar_idx"], "exit_reason": "end"})
    
    return pd.DataFrame(trades)


def display_results(ticker, strategy, trades_df):
    """Display backtest results."""
    print(f"\n{'='*60}")
    print(f"  BACKTEST: {ticker} | {strategy.upper()}")
    print(f"{'='*60}")
    
    if trades_df.empty:
        print("  No trades generated. Strategy conditions not met.")
        return
    
    wins = trades_df[trades_df["pnl"] > 0]
    losses = trades_df[trades_df["pnl"] <= 0]
    
    win_rate = len(wins) / len(trades_df) * 100
    total_pnl_pct = trades_df["pnl_pct"].sum()
    avg_pnl = trades_df["pnl_pct"].mean()
    avg_hold = trades_df["days_held"].mean()
    
    print(f"  Trades:     {len(trades_df)}")
    print(f"  Win Rate:   {win_rate:.1f}% ({len(wins)}W / {len(losses)}L)")
    print(f"  Total P&L:  {total_pnl_pct:+.1f}%")
    print(f"  Avg P&L:    {avg_pnl:+.2f}% per trade")
    print(f"  Avg Hold:   {avg_hold:.1f} days")
    
    if not wins.empty:
        print(f"  Avg Win:    {wins['pnl_pct'].mean():+.2f}%")
    if not losses.empty:
        print(f"  Avg Loss:   {losses['pnl_pct'].mean():+.2f}%")
    
    # Exit reasons
    print(f"\n  Exit Reasons:")
    for reason, count in trades_df["exit_reason"].value_counts().items():
        print(f"    {reason}: {count}")
    
    # Best settings found
    print(f"\n  Settings Used:")
    params = STRATEGIES.get(strategy, {})
    for k, v in params.items():
        print(f"    {k}: {v}")
    
    print(f"{'='*60}")
    return trades_df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", type=str, default="XLE")
    parser.add_argument("--strategy", type=str, default="swing",
                       choices=list(STRATEGIES.keys()))
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    
    cfg = load_config()
    broker = AlpacaBroker(cfg.broker)
    
    df = get_historical_bars(broker, args.ticker, args.days)
    if df.empty:
        print(f"  No data for {args.ticker}")
        return
    
    print(f"  Loaded {len(df)} bars for {args.ticker}")
    trades = run_backtest(df, args.strategy)
    display_results(args.ticker, args.strategy, trades)
    
    if args.save and not trades.empty:
        os.makedirs("logs", exist_ok=True)
        fname = f"logs/backtest_{args.ticker}_{args.strategy}_{datetime.now().strftime('%Y%m%d')}.csv"
        trades.to_csv(fname, index=False)
        print(f"  💾 Saved: {fname}")


if __name__ == "__main__":
    main()
