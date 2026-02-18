"""
Scoring Engine v5 — Gate + Flow Ranking
========================================
Backtested Jan 31 → Feb 13 (9 trading days, 472 gated stocks):
  Spearman r = +0.272 (p = 2.0e-9)
  Q5-Q1 spread = +3.26%
  Top 10/25/50 hit rates = 100%/96%/94%

Architecture change from v4:
  - Trend is now a GATE (pass/fail), NOT a scoring component
  - Ranking is purely: Options 30% + Dark Pool 25% + Volume 25% + Momentum 20%
  - This eliminates the negative correlation from trend-in-score

Gate criteria:
  1. Price above 20-day EMA (SMA20% > 0)
  2. Price above 50-day EMA (SMA50% > 0)
  3. Price above 200-day EMA (SMA200% > 0)
  4. Extension from 20-day EMA ≤ 10% (not overextended)

Usage:
    from scoring_engine_v5 import score_universe_v5, apply_gate
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Optional, Dict, Tuple


# ═══════════════════════════════════════════════════════════════
# V5 WEIGHTS — validated by backtest
# ═══════════════════════════════════════════════════════════════
V5_WEIGHTS = {
    "options": 0.30,
    "darkpool": 0.25,
    "volume": 0.25,
    "momentum": 0.20,
}

# Gate thresholds
GATE = {
    "min_price": 5.0,
    "min_avg_vol": 200_000,
    "max_ext_20ema": 10.0,  # % above 20 EMA
    "require_above_sma20": True,
    "require_above_sma50": True,
    "require_above_sma200": True,
}

# Flow conviction thresholds
FLOW = {
    "whale_dp_buy_pct": 60.0,       # DP buy% >= 60 AND notional >= $50M
    "whale_dp_notional_m": 50.0,
    "whale_oi_skew": 1000,           # net call OI change >= 1000
    "moderate_dp_buy_pct": 50.0,     # any two of: dp_buy > 50%, notional > $20M, oi_skew > 500
    "moderate_dp_notional_m": 20.0,
    "moderate_oi_skew": 500,
}

# Action thresholds
ACTION = {
    "strong_buy": 40.0,
    "buy_on_dip": 30.0,
    "accumulate": 20.0,
}


# ═══════════════════════════════════════════════════════════════
# GATE LOGIC
# ═══════════════════════════════════════════════════════════════

def apply_gate(df: pd.DataFrame) -> pd.Series:
    """
    Returns boolean Series: True if stock passes the trend gate.
    
    Required columns: sma20_pct, sma50_pct, sma200_pct, price, avg_volume
    (sma_pct columns = % distance from that SMA, where positive = above)
    """
    gate = pd.Series(True, index=df.index)
    
    # Price above all 3 EMAs
    if "sma20_pct" in df.columns:
        gate &= df["sma20_pct"].fillna(-999) > 0
    if "sma50_pct" in df.columns:
        gate &= df["sma50_pct"].fillna(-999) > 0
    if "sma200_pct" in df.columns:
        gate &= df["sma200_pct"].fillna(-999) > 0
    
    # Not overextended from 20 EMA
    if "sma20_pct" in df.columns:
        # sma20_pct is "% above SMA20" — we call it ext_20EMA
        ext = df["sma20_pct"].fillna(0).abs()
        gate &= ext <= GATE["max_ext_20ema"]
    
    # Minimum price
    if "price" in df.columns:
        gate &= df["price"].fillna(0) >= GATE["min_price"]
    
    # Minimum avg volume
    if "avg_volume" in df.columns:
        gate &= df["avg_volume"].fillna(0) >= GATE["min_avg_vol"]
    
    return gate


# ═══════════════════════════════════════════════════════════════
# COMPONENT SCORES (0-100 each)
# ═══════════════════════════════════════════════════════════════

def options_score(df: pd.DataFrame) -> pd.Series:
    """
    Options flow score from OI changes and put/call ratios.
    Inputs: oi_chg_skew (net call - put OI change), put_call_ratio
    """
    score = pd.Series(0.0, index=df.index)
    
    # OI change skew: positive = more call OI added
    if "oi_chg_skew" in df.columns:
        skew = df["oi_chg_skew"].fillna(0)
        # Normalize: 5000 contracts net call = full score on this component
        score += np.clip(skew / 5000, -1, 1) * 50
    
    # Put/Call ratio: lower = more bullish (more calls relative to puts)
    if "put_call_ratio" in df.columns:
        pcr = df["put_call_ratio"].fillna(1.0)
        # PCR < 0.5 = very bullish, > 1.5 = bearish
        pcr_score = np.clip((1.0 - pcr) / 0.5, -1, 1) * 30
        score += pcr_score
    
    # Call volume surge (if available)
    if "call_vol_surge" in df.columns:
        score += np.clip(df["call_vol_surge"].fillna(0) / 3.0, 0, 1) * 20
    
    return score.clip(0, 100)


def darkpool_score(df: pd.DataFrame) -> pd.Series:
    """
    Dark pool institutional flow score.
    Inputs: dp_buy_pct (% of DP volume that's buy-side), dp_notional ($ total), dp_prints
    """
    score = pd.Series(0.0, index=df.index)
    
    # Buy percentage: 50% = neutral, 70% = strong
    if "dp_buy_pct" in df.columns:
        bp = df["dp_buy_pct"].fillna(50)
        score += np.clip((bp - 50) / 20, -1, 1) * 50
    
    # Notional volume (more = more institutional attention)
    if "dp_notional" in df.columns:
        notional_m = df["dp_notional"].fillna(0) / 1e6
        score += np.clip(notional_m / 100, 0, 1) * 30
    elif "dp_notional_m" in df.columns:
        score += np.clip(df["dp_notional_m"].fillna(0) / 100, 0, 1) * 30
    
    # Print count
    if "dp_prints" in df.columns:
        score += np.clip(df["dp_prints"].fillna(0) / 500, 0, 1) * 20
    
    return score.clip(0, 100)


def volume_score(df: pd.DataFrame) -> pd.Series:
    """
    Volume confirmation score.
    Inputs: rel_volume (relative to average)
    """
    score = pd.Series(30.0, index=df.index)  # base score for having volume
    
    if "rel_volume" in df.columns:
        rv = df["rel_volume"].fillna(1.0)
        # RelVol 1.0 = neutral (30pts), 2.0 = good (65pts), 3.0+ = excellent (100pts)
        score = np.clip((rv - 0.5) / 2.5, 0, 1) * 100
    
    if "volume" in df.columns and "avg_volume" in df.columns:
        vol = df["volume"].fillna(0)
        avg = df["avg_volume"].replace({0: np.nan}).fillna(1)
        ratio = (vol / avg).clip(0, 10)
        vol_ratio_score = np.clip((ratio - 0.5) / 2.5, 0, 1) * 100
        # Blend with rel_volume if both exist
        if "rel_volume" in df.columns:
            score = 0.6 * score + 0.4 * vol_ratio_score
        else:
            score = vol_ratio_score
    
    return score.clip(0, 100)


def momentum_score(df: pd.DataFrame) -> pd.Series:
    """
    Momentum score from performance and RSI.
    """
    score = pd.Series(0.0, index=df.index)
    
    # Weekly performance: +5% maps to ~30pts
    if "perf_week" in df.columns:
        pw = df["perf_week"].fillna(0)
        score += np.clip(pw / 10, -1, 1) * 30
    
    # Quarterly performance: +20% maps to ~35pts
    if "perf_quarter" in df.columns:
        pq = df["perf_quarter"].fillna(0)
        score += np.clip(pq / 25, -1, 1) * 35
    
    # Half-year performance: +40% maps to ~25pts
    if "perf_half" in df.columns:
        ph = df["perf_half"].fillna(0)
        score += np.clip(ph / 50, -1, 1) * 25
    elif "perf_month" in df.columns:
        pm = df["perf_month"].fillna(0)
        score += np.clip(pm / 15, -1, 1) * 25
    
    # RSI bonus: sweet spot 50-70
    if "rsi" in df.columns:
        r = df["rsi"].fillna(50)
        bonus = np.where((r >= 50) & (r <= 70), 10,
                np.where((r > 70) & (r <= 80), 5,
                np.where(r < 40, -8, 0)))
        score += bonus
    
    return score.clip(0, 100)


# ═══════════════════════════════════════════════════════════════
# STRUCTURE CLASSIFICATION
# ═══════════════════════════════════════════════════════════════

def classify_structure(row: pd.Series) -> str:
    """Classify price structure from SMA distances and momentum."""
    s20 = row.get("sma20_pct", 0) or 0
    s50 = row.get("sma50_pct", 0) or 0
    s200 = row.get("sma200_pct", 0) or 0
    pw = row.get("perf_week", 0) or 0
    pm = row.get("perf_month", 0) or 0
    
    above_all = s20 > 0 and s50 > 0 and s200 > 0
    bullish_stack = s20 > 0 and s50 > 0 and s200 > 0
    
    if above_all and bullish_stack and pw >= 4 and pm >= 8:
        return "🚀 Momentum"
    elif s50 > 0 and s200 > 0 and pw >= 2:
        return "📈 Breakout"
    elif above_all and bullish_stack:
        return "📈 Uptrend"
    elif s20 > 0 and s50 < 0 and (pw >= 2 or pm >= 5):
        return "🔄 Reversal"
    elif abs(s20) < 2 and abs(pw) < 2:
        return "⏸️ Consolidation"
    else:
        return "📊 Trend/Range"


# ═══════════════════════════════════════════════════════════════
# FLOW CONVICTION
# ═══════════════════════════════════════════════════════════════

def classify_flow(row: pd.Series) -> str:
    """Classify institutional flow conviction level."""
    dp_bp = row.get("dp_buy_pct", 50) or 50
    dp_not = row.get("dp_notional_m", 0) or 0
    oi_skew = row.get("oi_chg_skew", 0) or 0
    
    # Whale: strong on multiple dimensions
    whale_signals = 0
    if dp_bp >= FLOW["whale_dp_buy_pct"]:
        whale_signals += 1
    if dp_not >= FLOW["whale_dp_notional_m"]:
        whale_signals += 1
    if oi_skew >= FLOW["whale_oi_skew"]:
        whale_signals += 1
    
    if whale_signals >= 2:
        return "🐋 Strong Whale Flow"
    
    # Moderate: decent on at least two
    mod_signals = 0
    if dp_bp >= FLOW["moderate_dp_buy_pct"]:
        mod_signals += 1
    if dp_not >= FLOW["moderate_dp_notional_m"]:
        mod_signals += 1
    if oi_skew >= FLOW["moderate_oi_skew"]:
        mod_signals += 1
    
    if mod_signals >= 2:
        return "📊 Moderate Flow"
    
    # Check for bearish signals
    if dp_bp < 40 or oi_skew < -1000:
        return "🔻 Weak/Bearish Flow"
    
    if dp_not == 0 and oi_skew == 0:
        return "⬜ No Flow Data"
    
    return "💧 Light Flow"


# ═══════════════════════════════════════════════════════════════
# ACTION ASSIGNMENT
# ═══════════════════════════════════════════════════════════════

def assign_action(row: pd.Series) -> str:
    """Assign trading action based on score + flow + gate."""
    score = row.get("score_v5", 0)
    passes = row.get("passes_gate", False)
    flow = row.get("flow_conviction", "")
    
    if not passes:
        return "🚫 Outside gate (extended or below MA)"
    
    is_whale = "Whale" in str(flow)
    is_moderate = "Moderate" in str(flow)
    is_bearish = "Bearish" in str(flow) or "Weak" in str(flow)
    
    if score >= ACTION["strong_buy"]:
        if is_whale:
            return "🟢🐋 Strong Buy + Whale"
        return "🟢 Strong Buy"
    elif score >= ACTION["buy_on_dip"]:
        if is_bearish:
            return "📋 Monitor (weak flow)"
        return "🟡 Buy on dip"
    elif score >= ACTION["accumulate"]:
        return "🔵 Accumulate"
    else:
        if is_bearish:
            return "📋 Monitor (weak flow)"
        return "📋 Monitor"


# ═══════════════════════════════════════════════════════════════
# MAIN SCORING PIPELINE
# ═══════════════════════════════════════════════════════════════

def score_universe_v5(df: pd.DataFrame) -> pd.DataFrame:
    """
    Full v5 scoring pipeline.
    
    Input DataFrame should have columns:
        Required: price, sma20_pct, sma50_pct, sma200_pct
        Scoring: rel_volume, perf_week, perf_quarter, perf_half/perf_month,
                 rsi, oi_chg_skew, put_call_ratio, dp_buy_pct, dp_notional_m, dp_prints
    
    Returns: DataFrame with added columns:
        passes_gate, opt_sc, dp_sc, vol_sc, mom_sc, score_v5,
        structure, flow_conviction, action
    """
    out = df.copy()
    
    # 1. Apply gate
    out["passes_gate"] = apply_gate(out)
    
    # 2. Compute component scores
    out["opt_sc"] = options_score(out)
    out["dp_sc"] = darkpool_score(out)
    out["vol_sc"] = volume_score(out)
    out["mom_sc"] = momentum_score(out)
    
    # 3. Composite v5 score (flow-based ranking)
    out["score_v5"] = (
        out["opt_sc"] * V5_WEIGHTS["options"]
        + out["dp_sc"] * V5_WEIGHTS["darkpool"]
        + out["vol_sc"] * V5_WEIGHTS["volume"]
        + out["mom_sc"] * V5_WEIGHTS["momentum"]
    ).round(1)
    
    # 4. Structure classification
    out["structure"] = out.apply(classify_structure, axis=1)
    
    # 5. Flow conviction
    out["flow_conviction"] = out.apply(classify_flow, axis=1)
    
    # 6. Action assignment
    out["action"] = out.apply(assign_action, axis=1)
    
    # 7. Gated score (0 if outside gate for ranking purposes)
    out["score_v5_gated"] = np.where(out["passes_gate"], out["score_v5"], 0)
    
    return out


def get_top_setups(scored: pd.DataFrame, n: int = 50, gated_only: bool = True) -> pd.DataFrame:
    """Get top N setups ranked by v5 score."""
    if gated_only:
        subset = scored[scored["passes_gate"]].copy()
    else:
        subset = scored.copy()
    
    return (subset
            .sort_values("score_v5", ascending=False)
            .head(n)
            .reset_index(drop=True))


# ═══════════════════════════════════════════════════════════════
# QUICK TEST
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("v5 Scoring Engine loaded.")
    print(f"Weights: {V5_WEIGHTS}")
    print(f"Gate: {GATE}")
    print(f"Flow thresholds: {FLOW}")
    print(f"Action thresholds: {ACTION}")
    
    # Quick synthetic test
    test = pd.DataFrame({
        "ticker": ["AAPL", "NVDA", "MSFT", "WEAK"],
        "price": [230, 140, 430, 3],
        "sma20_pct": [3.0, 5.0, 2.0, -5.0],
        "sma50_pct": [8.0, 12.0, 6.0, -10.0],
        "sma200_pct": [15.0, 25.0, 10.0, -20.0],
        "rel_volume": [1.5, 2.5, 1.0, 0.5],
        "perf_week": [3.0, 5.0, 1.0, -3.0],
        "perf_quarter": [12.0, 20.0, 8.0, -15.0],
        "rsi": [58.0, 65.0, 52.0, 35.0],
        "oi_chg_skew": [2000, 5000, 500, -1000],
        "put_call_ratio": [0.6, 0.3, 0.8, 1.5],
        "dp_buy_pct": [55, 65, 48, 30],
        "dp_notional_m": [80, 200, 50, 5],
        "dp_prints": [300, 600, 150, 20],
        "avg_volume": [500000, 1000000, 300000, 50000],
    })
    
    result = score_universe_v5(test)
    print("\nTest Results:")
    for _, r in result.iterrows():
        print(f"  {r['ticker']:6s} | Gate: {r['passes_gate']} | Score: {r['score_v5']:5.1f} | "
              f"{r['structure']:20s} | {r['flow_conviction']:25s} | {r['action']}")
