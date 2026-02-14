#!/usr/bin/env python3
"""
risk_dashboard.py — Portfolio Risk Analysis
Shows exposure, concentration, sector allocation, and risk metrics.

Usage:
    python risk_dashboard.py
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.config import load_config
from core.broker import AlpacaBroker

SECTOR_MAP = {
    "XLE": "Energy", "CVX": "Energy", "XOM": "Energy", "SLB": "Energy",
    "XLF": "Financials", "JPM": "Financials", "GS": "Financials", "V": "Financials", "MA": "Financials",
    "XLK": "Technology", "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology",
    "AMD": "Technology", "AVGO": "Technology", "MU": "Technology", "QCOM": "Technology",
    "META": "Technology", "GOOGL": "Technology", "CRM": "Technology", "ORCL": "Technology",
    "XLV": "Healthcare", "LLY": "Healthcare", "UNH": "Healthcare",
    "XLI": "Industrials", "CAT": "Industrials", "DE": "Industrials", "GE": "Industrials", "BA": "Industrials",
    "XLP": "Cons Staples", "COST": "Cons Staples", "WMT": "Cons Staples",
    "XLY": "Cons Disc", "AMZN": "Cons Disc", "TSLA": "Cons Disc", "HD": "Cons Disc", "NFLX": "Cons Disc",
    "XLB": "Materials", "XLU": "Utilities", "XLRE": "Real Estate", "XLC": "Communication",
}


def analyze_risk(broker: AlpacaBroker):
    """Full risk analysis."""
    print(f"\n{'='*70}")
    print(f"  RISK DASHBOARD    {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*70}")
    
    acct = broker.get_account()
    positions = broker.get_positions()
    
    equity = acct.equity
    
    # Account-level risk
    print(f"\n  ACCOUNT RISK")
    print(f"  {'─'*55}")
    print(f"  Equity:          ${equity:>12,.2f}")
    print(f"  Open Positions:  {len(positions)}")
    print(f"  Cash Available:  ${acct.cash:>12,.2f} ({acct.cash/equity*100:.1f}%)")
    
    invested = sum(p.market_value for p in positions)
    print(f"  Invested:        ${invested:>12,.2f} ({invested/equity*100:.1f}%)")
    
    total_pnl = sum(p.unrealized_pnl for p in positions)
    print(f"  Unrealized P&L:  ${total_pnl:>+12,.2f}")
    
    # Daily P&L check
    if acct.daily_pnl_pct <= -3:
        print(f"  ⛔ CIRCUIT BREAKER ACTIVE — Daily P&L: {acct.daily_pnl_pct:+.2f}%")
    elif acct.daily_pnl_pct <= -2:
        print(f"  ⚠️  REDUCE SIZING — Daily P&L: {acct.daily_pnl_pct:+.2f}%")
    
    if not positions:
        print("\n  No positions to analyze.")
        return
    
    # Position concentration
    print(f"\n  POSITION CONCENTRATION")
    print(f"  {'─'*55}")
    print(f"  {'Ticker':<7} {'Value':>10} {'% Port':>8} {'P&L%':>8} {'Status'}")
    
    for p in sorted(positions, key=lambda x: x.market_value, reverse=True):
        pct = p.market_value / equity * 100
        status = "OK"
        if pct > 10:
            status = "⚠️ HIGH"
        elif pct > 5:
            status = "📊 WATCH"
        
        print(f"  {p.ticker:<7} ${p.market_value:>9,.2f} {pct:>7.1f}% "
              f"{p.unrealized_pnl_pct:>+7.1f}% {status}")
    
    # Sector exposure
    sector_exposure = {}
    for p in positions:
        sector = SECTOR_MAP.get(p.ticker, "Other")
        sector_exposure[sector] = sector_exposure.get(sector, 0) + p.market_value
    
    print(f"\n  SECTOR EXPOSURE")
    print(f"  {'─'*55}")
    for sector, value in sorted(sector_exposure.items(), key=lambda x: -x[1]):
        pct = value / equity * 100
        bar = "█" * int(pct / 2)
        warning = " ⚠️" if pct > 25 else ""
        print(f"  {sector:<15} ${value:>10,.2f} {pct:>6.1f}% {bar}{warning}")
    
    # Risk score
    max_position_pct = max((p.market_value / equity * 100) for p in positions) if positions else 0
    max_sector_pct = max((v / equity * 100) for v in sector_exposure.values()) if sector_exposure else 0
    
    risk_score = 0
    if max_position_pct > 10: risk_score += 30
    elif max_position_pct > 5: risk_score += 15
    if max_sector_pct > 25: risk_score += 30
    elif max_sector_pct > 20: risk_score += 15
    if len(positions) > 8: risk_score += 20
    if abs(acct.daily_pnl_pct) > 2: risk_score += 20
    
    risk_label = "🟢 LOW" if risk_score < 30 else "🟡 MODERATE" if risk_score < 60 else "🔴 HIGH"
    print(f"\n  OVERALL RISK: {risk_label} (score: {risk_score})")
    print(f"{'='*70}")


def main():
    cfg = load_config()
    broker = AlpacaBroker(cfg.broker)
    analyze_risk(broker)


if __name__ == "__main__":
    main()
