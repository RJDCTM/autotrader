"""
Mancini + v5 Scoring Autotrader — Streamlit Dashboard
======================================================
Paper trading dashboard integrating:
  1. v5 Scoring Engine (Gate + Flow Ranking)
  2. Mancini 0-1 DTE SPY Framework
  3. Position management, risk controls, trade journal

Launch:
    streamlit run autotrader_dashboard.py

Requirements:
    pip install streamlit pandas numpy plotly alpaca-py
"""

from __future__ import annotations
import os
import json
import time
import logging
from datetime import datetime, timedelta, date
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Tuple
from enum import Enum
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import streamlit as st
    HAS_STREAMLIT = True
except ImportError:
    HAS_STREAMLIT = False

try:
    import plotly.graph_objects as go
    import plotly.express as px
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

# Import our v5 scoring engine
from scoring_engine_v5 import (
    score_universe_v5, get_top_setups, apply_gate,
    V5_WEIGHTS, GATE, FLOW, ACTION,
    classify_structure, classify_flow, assign_action,
)


# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

@dataclass
class BotConfig:
    """Master configuration for the autotrader."""
    # Trading mode
    mode: str = "paper"  # "paper", "live", "dry"
    
    # Risk management
    max_position_pct: float = 5.0        # max % of portfolio per position
    max_portfolio_risk_pct: float = 2.0  # max % portfolio risk per trade
    max_daily_loss: float = 1500.0       # $ daily loss circuit breaker
    max_daily_trades: int = 8            # max trades per day
    max_open_positions: int = 15         # max concurrent positions
    
    # v5 Entry criteria
    min_score_entry: float = 40.0        # minimum v5 score to enter
    min_score_hold: float = 25.0         # below this → trim signal
    require_gate: bool = True            # must pass trend gate
    prefer_whale_flow: bool = True       # prioritize whale flow signals
    
    # Exit rules (Bot Rules v3.0)
    ema20_extension_tier1: float = 8.0   # % above EMA20 → trim 25%
    ema20_extension_tier2: float = 12.0  # % above EMA20 → trim 50%
    trailing_stop_atr_mult: float = 2.0  # ATR multiplier for trailing stop
    partial_exit_pct: float = 0.75       # 75% exit at S/R
    
    # Mancini 0DTE settings
    mancini_enabled: bool = True
    mancini_risk_per_trade: float = 500.0
    mancini_max_daily_trades: int = 5
    mancini_dte: int = 0
    
    # Scan interval
    scan_interval_sec: int = 300  # 5 minutes
    
    # Alpaca API
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"


@dataclass
class TradeRecord:
    """Single trade record for the journal."""
    timestamp: str
    ticker: str
    side: str          # "BUY" or "SELL"
    quantity: float
    price: float
    strategy: str      # "v5_swing", "mancini_0dte", "exit_trim", etc.
    score_at_entry: float = 0.0
    structure: str = ""
    flow_conviction: str = ""
    reason: str = ""
    pnl: float = 0.0
    status: str = "open"  # "open", "closed", "cancelled"
    
    def to_dict(self):
        return asdict(self)


@dataclass 
class Position:
    """Open position tracker."""
    ticker: str
    entry_price: float
    quantity: float
    entry_date: str
    strategy: str
    score_at_entry: float = 0.0
    trailing_stop: float = 0.0
    highest_price: float = 0.0
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    
    def update(self, current_price: float):
        self.current_price = current_price
        self.highest_price = max(self.highest_price, current_price)
        self.unrealized_pnl = (current_price - self.entry_price) * self.quantity


# ═══════════════════════════════════════════════════════════════
# TRADE JOURNAL
# ═══════════════════════════════════════════════════════════════

class TradeJournal:
    """Persistent trade journal with CSV storage."""
    
    def __init__(self, filepath: str = "trade_journal.csv"):
        self.filepath = filepath
        self.trades: List[TradeRecord] = []
        self._load()
    
    def _load(self):
        if os.path.exists(self.filepath):
            try:
                df = pd.read_csv(self.filepath)
                for _, row in df.iterrows():
                    self.trades.append(TradeRecord(**row.to_dict()))
            except Exception:
                pass
    
    def save(self):
        if self.trades:
            df = pd.DataFrame([t.to_dict() for t in self.trades])
            df.to_csv(self.filepath, index=False)
    
    def add_trade(self, trade: TradeRecord):
        self.trades.append(trade)
        self.save()
    
    def get_daily_trades(self, dt: Optional[date] = None) -> List[TradeRecord]:
        dt = dt or date.today()
        return [t for t in self.trades if t.timestamp[:10] == str(dt)]
    
    def daily_pnl(self, dt: Optional[date] = None) -> float:
        return sum(t.pnl for t in self.get_daily_trades(dt))
    
    def daily_trade_count(self, dt: Optional[date] = None) -> int:
        return len(self.get_daily_trades(dt))
    
    def to_dataframe(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame()
        return pd.DataFrame([t.to_dict() for t in self.trades])


# ═══════════════════════════════════════════════════════════════
# SIGNAL GENERATOR
# ═══════════════════════════════════════════════════════════════

class SignalGenerator:
    """Generates entry/exit signals from v5 scored universe."""
    
    def __init__(self, config: BotConfig):
        self.config = config
    
    def generate_entry_signals(self, scored: pd.DataFrame, 
                                positions: Dict[str, Position]) -> pd.DataFrame:
        """
        Filter scored universe for actionable entry signals.
        Returns DataFrame of candidates ranked by priority.
        """
        # Must pass gate
        candidates = scored[scored["passes_gate"]].copy()
        
        # Minimum score
        candidates = candidates[candidates["score_v5"] >= self.config.min_score_entry]
        
        # Not already in position
        held_tickers = set(positions.keys())
        candidates = candidates[~candidates["ticker"].isin(held_tickers)]
        
        # Prioritize whale flow
        if self.config.prefer_whale_flow:
            candidates["priority"] = 0
            whale_mask = candidates["flow_conviction"].str.contains("Whale", na=False)
            candidates.loc[whale_mask, "priority"] = 2
            moderate_mask = candidates["flow_conviction"].str.contains("Moderate", na=False)
            candidates.loc[moderate_mask, "priority"] = 1
            
            candidates = candidates.sort_values(
                ["priority", "score_v5"], ascending=[False, False]
            )
        else:
            candidates = candidates.sort_values("score_v5", ascending=False)
        
        return candidates.reset_index(drop=True)
    
    def generate_exit_signals(self, positions: Dict[str, Position],
                               scored: pd.DataFrame) -> List[Dict]:
        """
        Check positions for exit signals.
        Returns list of exit signal dicts.
        """
        exits = []
        scored_lookup = scored.set_index("ticker") if "ticker" in scored.columns else pd.DataFrame()
        
        for ticker, pos in positions.items():
            reasons = []
            urgency = 0  # 0=monitor, 1=consider, 2=trim, 3=exit
            
            # Check if still in scored universe
            if ticker in scored_lookup.index:
                row = scored_lookup.loc[ticker]
                current_score = row.get("score_v5", 0)
                passes_gate = row.get("passes_gate", False)
                ext_20 = row.get("sma20_pct", 0) or 0
                
                # Score degradation
                if current_score < self.config.min_score_hold:
                    reasons.append(f"Score dropped to {current_score:.1f} (min hold: {self.config.min_score_hold})")
                    urgency = max(urgency, 2)
                
                # Gate failure
                if not passes_gate:
                    reasons.append("Failed trend gate (below key MAs)")
                    urgency = max(urgency, 3)
                
                # Extension tiers
                if ext_20 >= self.config.ema20_extension_tier2:
                    reasons.append(f"Extended {ext_20:.1f}% above 20EMA (Tier 2)")
                    urgency = max(urgency, 2)
                elif ext_20 >= self.config.ema20_extension_tier1:
                    reasons.append(f"Extended {ext_20:.1f}% above 20EMA (Tier 1)")
                    urgency = max(urgency, 1)
            
            # Trailing stop check
            if pos.trailing_stop > 0 and pos.current_price <= pos.trailing_stop:
                reasons.append(f"Trailing stop hit at ${pos.trailing_stop:.2f}")
                urgency = max(urgency, 3)
            
            # P&L based exits
            pnl_pct = ((pos.current_price - pos.entry_price) / pos.entry_price) * 100
            if pnl_pct <= -7:
                reasons.append(f"Stop loss: {pnl_pct:.1f}% drawdown")
                urgency = max(urgency, 3)
            
            if reasons:
                exits.append({
                    "ticker": ticker,
                    "reasons": reasons,
                    "urgency": urgency,
                    "pnl_pct": pnl_pct,
                    "current_score": scored_lookup.loc[ticker].get("score_v5", 0) if ticker in scored_lookup.index else None,
                })
        
        return sorted(exits, key=lambda x: -x["urgency"])


# ═══════════════════════════════════════════════════════════════
# POSITION SIZER
# ═══════════════════════════════════════════════════════════════

class PositionSizer:
    """Calculate position sizes based on risk rules."""
    
    def __init__(self, config: BotConfig):
        self.config = config
    
    def calculate_size(self, ticker: str, price: float, atr: float,
                       portfolio_value: float, score: float,
                       flow_conviction: str) -> Dict:
        """
        Calculate position size respecting risk limits.
        Returns dict with shares, dollar_amount, risk_amount, stop_price.
        """
        # Max position by portfolio %
        max_position_dollars = portfolio_value * (self.config.max_position_pct / 100)
        
        # Risk per trade
        max_risk = portfolio_value * (self.config.max_portfolio_risk_pct / 100)
        
        # Stop distance (2 × ATR)
        stop_distance = atr * self.config.trailing_stop_atr_mult
        stop_price = price - stop_distance
        
        # Size from risk
        if stop_distance > 0:
            shares_from_risk = max_risk / stop_distance
        else:
            shares_from_risk = max_position_dollars / price
        
        # Size from max position
        shares_from_position = max_position_dollars / price
        
        # Take the smaller
        shares = min(shares_from_risk, shares_from_position)
        
        # Score-based scaling: higher score = fuller size
        if score >= 50:
            scale = 1.0
        elif score >= 40:
            scale = 0.75
        else:
            scale = 0.5
        
        # Whale flow bonus: +25% size
        if "Whale" in str(flow_conviction):
            scale = min(scale * 1.25, 1.0)
        
        shares = int(shares * scale)
        dollar_amount = shares * price
        risk_amount = shares * stop_distance
        
        return {
            "shares": shares,
            "dollar_amount": round(dollar_amount, 2),
            "risk_amount": round(risk_amount, 2),
            "stop_price": round(stop_price, 2),
            "stop_distance": round(stop_distance, 2),
            "scale_factor": scale,
        }


# ═══════════════════════════════════════════════════════════════
# ALPACA INTEGRATION
# ═══════════════════════════════════════════════════════════════

class AlpacaBroker:
    """Alpaca API wrapper for order execution."""
    
    def __init__(self, config: BotConfig):
        self.config = config
        self.client = None
        self._connect()
    
    def _connect(self):
        """Try to connect to Alpaca API."""
        try:
            from alpaca.trading.client import TradingClient
            from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce
            
            api_key = self.config.alpaca_api_key or os.environ.get("ALPACA_API_KEY", "")
            api_secret = self.config.alpaca_api_secret or os.environ.get("ALPACA_API_SECRET", "")
            
            if api_key and api_secret:
                self.client = TradingClient(api_key, api_secret, paper=("paper" in self.config.alpaca_base_url))
                logging.info("Connected to Alpaca API")
            else:
                logging.warning("No Alpaca credentials — running in dry mode")
        except ImportError:
            logging.warning("alpaca-py not installed — running in dry mode")
    
    def get_account(self) -> Optional[Dict]:
        if not self.client:
            return {"equity": 100000, "buying_power": 100000, "cash": 100000, "status": "DRY_MODE"}
        try:
            acct = self.client.get_account()
            return {
                "equity": float(acct.equity),
                "buying_power": float(acct.buying_power),
                "cash": float(acct.cash),
                "status": acct.status,
            }
        except Exception as e:
            logging.error(f"Account fetch error: {e}")
            return None
    
    def submit_order(self, ticker: str, shares: int, side: str, 
                      order_type: str = "market") -> Optional[str]:
        """Submit order, returns order_id or None."""
        if not self.client:
            logging.info(f"DRY: {side} {shares} {ticker}")
            return f"DRY_{ticker}_{datetime.now().strftime('%H%M%S')}"
        
        try:
            from alpaca.trading.requests import MarketOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce
            
            req = MarketOrderRequest(
                symbol=ticker,
                qty=shares,
                side=OrderSide.BUY if side.upper() == "BUY" else OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            )
            order = self.client.submit_order(req)
            return str(order.id)
        except Exception as e:
            logging.error(f"Order error for {ticker}: {e}")
            return None
    
    def get_positions(self) -> List[Dict]:
        if not self.client:
            return []
        try:
            positions = self.client.get_all_positions()
            return [{"ticker": p.symbol, "qty": float(p.qty), "avg_entry": float(p.avg_entry_price),
                     "current_price": float(p.current_price), "unrealized_pnl": float(p.unrealized_pl)}
                    for p in positions]
        except Exception as e:
            logging.error(f"Position fetch error: {e}")
            return []


# ═══════════════════════════════════════════════════════════════
# AUTOTRADER ENGINE
# ═══════════════════════════════════════════════════════════════

class AutotraderEngine:
    """Core engine orchestrating signals, sizing, and execution."""
    
    def __init__(self, config: BotConfig):
        self.config = config
        self.signal_gen = SignalGenerator(config)
        self.sizer = PositionSizer(config)
        self.broker = AlpacaBroker(config)
        self.journal = TradeJournal()
        self.positions: Dict[str, Position] = {}
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.circuit_breaker_active = False
    
    def load_and_score(self, data_path: str) -> pd.DataFrame:
        """Load universe data and apply v5 scoring."""
        df = pd.read_csv(data_path) if data_path.endswith(".csv") else pd.read_excel(data_path)
        scored = score_universe_v5(df)
        return scored
    
    def run_cycle(self, scored: pd.DataFrame) -> Dict:
        """
        Run one scan cycle:
        1. Check circuit breakers
        2. Generate exit signals for open positions
        3. Generate entry signals for new positions
        4. Return signals (dashboard decides whether to execute)
        """
        result = {
            "timestamp": datetime.now().isoformat(),
            "circuit_breaker": False,
            "exit_signals": [],
            "entry_signals": [],
            "portfolio_summary": {},
        }
        
        # Circuit breaker check
        if abs(self.daily_pnl) >= self.config.max_daily_loss:
            self.circuit_breaker_active = True
            result["circuit_breaker"] = True
            return result
        
        if self.daily_trades >= self.config.max_daily_trades:
            result["circuit_breaker"] = True
            return result
        
        # Exit signals
        result["exit_signals"] = self.signal_gen.generate_exit_signals(
            self.positions, scored
        )
        
        # Entry signals (only if room for more positions)
        if len(self.positions) < self.config.max_open_positions:
            entries = self.signal_gen.generate_entry_signals(scored, self.positions)
            
            # Get account for sizing
            acct = self.broker.get_account()
            portfolio_value = acct.get("equity", 100000) if acct else 100000
            
            # Size top candidates
            sized_entries = []
            for _, row in entries.head(10).iterrows():
                atr = row.get("atr", row.get("price", 100) * 0.02)  # fallback ATR
                sizing = self.sizer.calculate_size(
                    ticker=row["ticker"],
                    price=row["price"],
                    atr=atr,
                    portfolio_value=portfolio_value,
                    score=row["score_v5"],
                    flow_conviction=row.get("flow_conviction", ""),
                )
                sized_entries.append({
                    "ticker": row["ticker"],
                    "price": row["price"],
                    "score": row["score_v5"],
                    "structure": row.get("structure", ""),
                    "flow": row.get("flow_conviction", ""),
                    "action": row.get("action", ""),
                    "sector": row.get("sector", ""),
                    **sizing,
                })
            
            result["entry_signals"] = sized_entries
        
        # Portfolio summary
        total_value = sum(p.current_price * p.quantity for p in self.positions.values())
        total_pnl = sum(p.unrealized_pnl for p in self.positions.values())
        result["portfolio_summary"] = {
            "open_positions": len(self.positions),
            "total_value": round(total_value, 2),
            "unrealized_pnl": round(total_pnl, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "daily_trades": self.daily_trades,
        }
        
        return result
    
    def execute_entry(self, ticker: str, shares: int, price: float,
                       score: float, strategy: str = "v5_swing",
                       stop_price: float = 0, structure: str = "",
                       flow: str = "") -> bool:
        """Execute an entry trade."""
        order_id = self.broker.submit_order(ticker, shares, "BUY")
        if order_id:
            self.positions[ticker] = Position(
                ticker=ticker,
                entry_price=price,
                quantity=shares,
                entry_date=datetime.now().strftime("%Y-%m-%d"),
                strategy=strategy,
                score_at_entry=score,
                trailing_stop=stop_price,
                highest_price=price,
                current_price=price,
            )
            self.journal.add_trade(TradeRecord(
                timestamp=datetime.now().isoformat(),
                ticker=ticker, side="BUY", quantity=shares, price=price,
                strategy=strategy, score_at_entry=score,
                structure=structure, flow_conviction=flow,
                reason=f"v5 entry: score={score:.1f}",
            ))
            self.daily_trades += 1
            return True
        return False
    
    def execute_exit(self, ticker: str, shares: int, price: float,
                      reason: str = "") -> bool:
        """Execute an exit trade."""
        order_id = self.broker.submit_order(ticker, shares, "SELL")
        if order_id:
            pos = self.positions.get(ticker)
            pnl = (price - pos.entry_price) * shares if pos else 0
            self.daily_pnl += pnl
            
            self.journal.add_trade(TradeRecord(
                timestamp=datetime.now().isoformat(),
                ticker=ticker, side="SELL", quantity=shares, price=price,
                strategy=pos.strategy if pos else "manual",
                reason=reason, pnl=pnl, status="closed",
            ))
            
            if pos and shares >= pos.quantity:
                del self.positions[ticker]
            elif pos:
                pos.quantity -= shares
            
            self.daily_trades += 1
            return True
        return False


# ═══════════════════════════════════════════════════════════════
# STREAMLIT DASHBOARD
# ═══════════════════════════════════════════════════════════════

def run_dashboard():
    """Main Streamlit dashboard."""
    st.set_page_config(
        page_title="Autotrader v5 Dashboard",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    
    st.title("🤖 Autotrader v5 — Gate + Flow Ranking")
    st.caption("Paper Trading Dashboard | v5 Scoring Engine | Mancini 0DTE Integration")
    
    # ─── Sidebar: Configuration ───────────────────────────────
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        mode = st.selectbox("Trading Mode", ["dry", "paper", "live"], index=0)
        
        st.subheader("🔑 Alpaca API")
        api_key = st.text_input("API Key", type="password", 
                                 value=os.environ.get("ALPACA_API_KEY", ""))
        api_secret = st.text_input("API Secret", type="password",
                                    value=os.environ.get("ALPACA_API_SECRET", ""))
        
        st.subheader("📊 v5 Scoring")
        min_score = st.slider("Min Entry Score", 20, 80, 40)
        min_hold = st.slider("Min Hold Score", 10, 50, 25)
        require_gate = st.checkbox("Require Trend Gate", value=True)
        whale_priority = st.checkbox("Prioritize Whale Flow", value=True)
        
        st.subheader("💰 Risk Management")
        max_pos_pct = st.slider("Max Position %", 1, 15, 5)
        max_risk_pct = st.slider("Max Risk %/Trade", 0.5, 5.0, 2.0, 0.5)
        max_daily_loss = st.number_input("Daily Loss Limit ($)", 500, 10000, 1500)
        max_trades = st.slider("Max Daily Trades", 1, 20, 8)
        max_positions = st.slider("Max Open Positions", 5, 30, 15)
        
        st.subheader("📉 Exit Rules")
        ext_tier1 = st.slider("Extension Tier 1 (%)", 5, 15, 8)
        ext_tier2 = st.slider("Extension Tier 2 (%)", 8, 20, 12)
        atr_mult = st.slider("Trailing Stop ATR×", 1.0, 4.0, 2.0, 0.5)
    
    # Build config from sidebar
    config = BotConfig(
        mode=mode,
        alpaca_api_key=api_key,
        alpaca_api_secret=api_secret,
        min_score_entry=min_score,
        min_score_hold=min_hold,
        require_gate=require_gate,
        prefer_whale_flow=whale_priority,
        max_position_pct=max_pos_pct,
        max_portfolio_risk_pct=max_risk_pct,
        max_daily_loss=max_daily_loss,
        max_daily_trades=max_trades,
        max_open_positions=max_positions,
        ema20_extension_tier1=ext_tier1,
        ema20_extension_tier2=ext_tier2,
        trailing_stop_atr_mult=atr_mult,
    )
    
    # Initialize engine in session state
    if "engine" not in st.session_state:
        st.session_state.engine = AutotraderEngine(config)
    if "scored_data" not in st.session_state:
        st.session_state.scored_data = None
    if "last_scan" not in st.session_state:
        st.session_state.last_scan = None
    
    engine = st.session_state.engine
    engine.config = config  # Update config on each run
    
    # ─── Tab Layout ───────────────────────────────────────────
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "📤 Data Upload & Score", "🎯 Entry Signals", "🚪 Exit Signals",
        "📋 Open Positions", "📓 Trade Journal", "📊 Analytics", "🤖 Monitor"
    ])
    
    # ─── Tab 1: Data Upload ───────────────────────────────────
    with tab1:
        st.header("📤 Upload & Score Universe")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Upload Scored Data")
            uploaded = st.file_uploader(
                "Upload Quickview CSV or scored Excel",
                type=["csv", "xlsx"],
                help="Upload the Quickview_v5 CSV from the weekly pipeline, or any scored universe file"
            )
            
            if uploaded:
                if uploaded.name.endswith(".csv"):
                    df = pd.read_csv(uploaded)
                else:
                    df = pd.read_excel(uploaded)
                
                st.success(f"Loaded {len(df)} rows from {uploaded.name}")
                
                # Check if already scored or needs scoring
                # Normalize common column name variants
                df = df.rename(columns={"Ticker": "ticker", "Sector": "sector",
                                        "rel_vol": "rel_volume", "ext_20EMA": "sma20_pct",
                                        "ext_50EMA": "sma50_pct"})
                if "score_v5" in df.columns:
                    st.info("✅ Data already has v5 scores — using as-is")
                    scored = df.copy()
                    if "passes_gate" not in scored.columns:
                        scored["passes_gate"] = True
                else:
                    st.info("🔄 Applying v5 scoring engine...")
                    scored = score_universe_v5(df)
                
                st.session_state.scored_data = scored
                st.session_state.last_scan = datetime.now()
        
        with col2:
            st.subheader("v5 Model Summary")
            st.markdown(f"""
            **Weights:** Options {V5_WEIGHTS['options']*100:.0f}% | 
            Dark Pool {V5_WEIGHTS['darkpool']*100:.0f}% | 
            Volume {V5_WEIGHTS['volume']*100:.0f}% | 
            Momentum {V5_WEIGHTS['momentum']*100:.0f}%
            
            **Gate:** Above 20/50/200 EMA + ≤{GATE['max_ext_20ema']:.0f}% extension
            
            **Backtest (Jan31→Feb13):**  
            Spearman r = +0.272 (p = 2e-9)  
            Q5-Q1 spread = +3.26%  
            Top 10 hit rate = 100%
            """)
        
        # Show scored data summary
        if st.session_state.scored_data is not None:
            scored = st.session_state.scored_data
            
            st.divider()
            
            # Metrics row
            m1, m2, m3, m4, m5 = st.columns(5)
            gated = scored[scored["passes_gate"]] if "passes_gate" in scored.columns else scored
            m1.metric("Total Scanned", len(scored))
            m2.metric("Pass Gate", len(gated))
            m3.metric("Strong Buys (≥40)", len(gated[gated["score_v5"] >= 40]) if "score_v5" in gated.columns else 0)
            m4.metric("Whale Flow", len(scored[scored.get("flow_conviction", pd.Series()).str.contains("Whale", na=False)]) if "flow_conviction" in scored.columns else 0)
            m5.metric("Last Scan", st.session_state.last_scan.strftime("%H:%M") if st.session_state.last_scan else "—")
            
            # Top 20 preview
            st.subheader("Top 20 Setups")
            display_cols = [c for c in ["ticker", "Ticker", "price", "score_v5", "opt_sc", "dp_sc", 
                                         "vol_sc", "mom_sc", "structure", "flow_conviction", "action",
                                         "ext_20EMA", "sma20_pct", "rsi", "sector", "Sector"] if c in scored.columns]
            
            top20 = gated.nlargest(20, "score_v5") if "score_v5" in gated.columns else gated.head(20)
            st.dataframe(top20[display_cols] if display_cols else top20, use_container_width=True)
    
    # ─── Tab 2: Entry Signals ─────────────────────────────────
    with tab2:
        st.header("🎯 Entry Signals")
        
        if st.session_state.scored_data is None:
            st.warning("Upload and score data first (Tab 1)")
        else:
            scored = st.session_state.scored_data
            entries = engine.signal_gen.generate_entry_signals(scored, engine.positions)
            
            if entries.empty:
                st.info("No entry signals meeting criteria")
            else:
                st.success(f"**{len(entries)} candidates** meeting entry criteria (score ≥ {config.min_score_entry})")
                
                # Get account for sizing
                acct = engine.broker.get_account()
                portfolio_value = acct.get("equity", 100000) if acct else 100000
                st.caption(f"Portfolio value: ${portfolio_value:,.0f} | Mode: {config.mode.upper()}")
                
                for i, (_, row) in enumerate(entries.head(10).iterrows()):
                    ticker = row.get("ticker", row.get("Ticker", "???"))
                    price = row.get("price", 0)
                    score = row.get("score_v5", 0)
                    structure = row.get("structure", "")
                    flow = row.get("flow_conviction", "")
                    action = row.get("action", "")
                    atr = row.get("atr", price * 0.02)
                    
                    sizing = engine.sizer.calculate_size(
                        ticker=ticker, price=price, atr=atr,
                        portfolio_value=portfolio_value, score=score,
                        flow_conviction=flow,
                    )
                    
                    with st.expander(f"{'🟢' if score >= 50 else '🟡'} {ticker} — Score: {score:.1f} | {structure} | {flow}", expanded=(i < 3)):
                        c1, c2, c3 = st.columns([2, 2, 1])
                        
                        with c1:
                            st.markdown(f"""
                            **Price:** ${price:.2f}  
                            **Score:** {score:.1f}  
                            **Structure:** {structure}  
                            **Flow:** {flow}  
                            **Action:** {action}
                            """)
                        
                        with c2:
                            st.markdown(f"""
                            **Shares:** {sizing['shares']}  
                            **Dollar Amount:** ${sizing['dollar_amount']:,.0f}  
                            **Risk Amount:** ${sizing['risk_amount']:,.0f}  
                            **Stop Price:** ${sizing['stop_price']:.2f}  
                            **Scale:** {sizing['scale_factor']:.0%}
                            """)
                        
                        with c3:
                            if st.button(f"▶️ Execute", key=f"buy_{ticker}_{i}"):
                                success = engine.execute_entry(
                                    ticker=ticker, shares=sizing["shares"],
                                    price=price, score=score,
                                    stop_price=sizing["stop_price"],
                                    structure=structure, flow=flow,
                                )
                                if success:
                                    st.success(f"✅ Bought {sizing['shares']} {ticker} @ ${price:.2f}")
                                    st.rerun()
                                else:
                                    st.error("❌ Order failed")
    
    # ─── Tab 3: Exit Signals ──────────────────────────────────
    with tab3:
        st.header("🚪 Exit Signals")
        
        if not engine.positions:
            st.info("No open positions to check")
        elif st.session_state.scored_data is None:
            st.warning("Upload scored data to check exit signals")
        else:
            exits = engine.signal_gen.generate_exit_signals(
                engine.positions, st.session_state.scored_data
            )
            
            if not exits:
                st.success("✅ All positions healthy — no exit signals")
            else:
                for ex in exits:
                    urgency_emoji = {0: "🟢", 1: "🟡", 2: "🟠", 3: "🔴"}
                    u = ex["urgency"]
                    
                    with st.expander(
                        f"{urgency_emoji.get(u, '⚪')} {ex['ticker']} — "
                        f"P&L: {ex['pnl_pct']:+.1f}% | Urgency: {u}/3",
                        expanded=(u >= 2)
                    ):
                        for reason in ex["reasons"]:
                            st.markdown(f"- {reason}")
                        
                        if ex.get("current_score") is not None:
                            st.markdown(f"**Current v5 Score:** {ex['current_score']:.1f}")
                        
                        pos = engine.positions.get(ex["ticker"])
                        if pos:
                            c1, c2 = st.columns(2)
                            with c1:
                                sell_pct = st.select_slider(
                                    "Exit %", [25, 50, 75, 100], value=75,
                                    key=f"exit_pct_{ex['ticker']}"
                                )
                            with c2:
                                shares_to_sell = int(pos.quantity * sell_pct / 100)
                                if st.button(f"Sell {shares_to_sell} shares", key=f"sell_{ex['ticker']}"):
                                    success = engine.execute_exit(
                                        ex["ticker"], shares_to_sell,
                                        pos.current_price,
                                        reason="; ".join(ex["reasons"]),
                                    )
                                    if success:
                                        st.success(f"✅ Sold {shares_to_sell} {ex['ticker']}")
                                        st.rerun()
    
    # ─── Tab 4: Open Positions ────────────────────────────────
    with tab4:
        st.header("📋 Open Positions")
        
        if not engine.positions:
            st.info("No open positions")
        else:
            pos_data = []
            for ticker, pos in engine.positions.items():
                pnl_pct = ((pos.current_price - pos.entry_price) / pos.entry_price * 100) if pos.entry_price else 0
                pos_data.append({
                    "Ticker": ticker,
                    "Entry": f"${pos.entry_price:.2f}",
                    "Current": f"${pos.current_price:.2f}",
                    "Shares": pos.quantity,
                    "P&L %": f"{pnl_pct:+.1f}%",
                    "Unrealized $": f"${pos.unrealized_pnl:,.0f}",
                    "Stop": f"${pos.trailing_stop:.2f}",
                    "Strategy": pos.strategy,
                    "Entry Date": pos.entry_date,
                })
            
            st.dataframe(pd.DataFrame(pos_data), use_container_width=True)
            
            # Summary metrics
            total_value = sum(p.current_price * p.quantity for p in engine.positions.values())
            total_pnl = sum(p.unrealized_pnl for p in engine.positions.values())
            
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Positions", len(engine.positions))
            c2.metric("Total Value", f"${total_value:,.0f}")
            c3.metric("Unrealized P&L", f"${total_pnl:,.0f}")
            c4.metric("Daily P&L", f"${engine.daily_pnl:,.0f}")
    
    # ─── Tab 5: Trade Journal ─────────────────────────────────
    with tab5:
        st.header("📓 Trade Journal")
        
        journal_df = engine.journal.to_dataframe()
        if journal_df.empty:
            st.info("No trades recorded yet")
        else:
            st.dataframe(journal_df.sort_values("timestamp", ascending=False), 
                         use_container_width=True)
            
            # Download button
            csv = journal_df.to_csv(index=False)
            st.download_button("📥 Download Journal CSV", csv, "trade_journal.csv")
    
    # ─── Tab 6: Analytics ─────────────────────────────────────
    with tab6:
        st.header("📊 Analytics")
        
        journal_df = engine.journal.to_dataframe()
        
        if journal_df.empty:
            st.info("Need trades to show analytics")
        else:
            # Basic stats
            closed = journal_df[journal_df["status"] == "closed"]
            if not closed.empty:
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Total Trades", len(closed))
                c2.metric("Win Rate", f"{(closed['pnl'] > 0).mean()*100:.1f}%")
                c3.metric("Total P&L", f"${closed['pnl'].sum():,.0f}")
                c4.metric("Avg P&L/Trade", f"${closed['pnl'].mean():,.0f}")
                
                # P&L by strategy
                if HAS_PLOTLY:
                    fig = px.bar(
                        closed.groupby("strategy")["pnl"].agg(["sum", "count", "mean"]).reset_index(),
                        x="strategy", y="sum", title="P&L by Strategy",
                        labels={"sum": "Total P&L ($)", "strategy": "Strategy"},
                    )
                    st.plotly_chart(fig, use_container_width=True)
                
                # Cumulative P&L
                if HAS_PLOTLY:
                    closed_sorted = closed.sort_values("timestamp")
                    closed_sorted["cum_pnl"] = closed_sorted["pnl"].cumsum()
                    fig2 = px.line(closed_sorted, x="timestamp", y="cum_pnl",
                                   title="Cumulative P&L")
                    st.plotly_chart(fig2, use_container_width=True)
        
        # Score distribution of universe
        if st.session_state.scored_data is not None and "score_v5" in st.session_state.scored_data.columns:
            scored = st.session_state.scored_data
            if HAS_PLOTLY:
                fig3 = px.histogram(scored[scored["passes_gate"]], x="score_v5", nbins=30,
                                     title="v5 Score Distribution (Gated Universe)")
                st.plotly_chart(fig3, use_container_width=True)

    # ─── Tab 7: Monitor Status ────────────────────────────────
    with tab7:
        st.header("🤖 Monitor Status")
        st.caption("Live feed from mancini_monitor.py — auto-refreshes every 30s")

        log_path = Path(__file__).parent / "monitor_log.json"

        if not log_path.exists():
            st.warning("monitor_log.json not found. Start the monitor first:")
            st.code("python mancini_monitor.py", language="bash")
        else:
            try:
                with open(log_path) as f:
                    mlog = json.load(f)

                updated = mlog.get("last_updated", "—")
                cb      = mlog.get("circuit_breaker", False)
                dpnl    = mlog.get("daily_pnl", 0.0)
                dtrades = mlog.get("daily_trades", 0)

                # Status bar
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Last Update", updated[11:19] if len(updated) > 10 else updated)
                c2.metric("Daily P&L", f"${dpnl:+,.0f}")
                c3.metric("Daily Trades", dtrades)
                c4.metric("Circuit Breaker", "🔴 ACTIVE" if cb else "🟢 Clear")

                if cb:
                    st.error("⚠️ Circuit breaker active — all trading halted")

                st.divider()

                # Mancini state
                m = mlog.get("mancini", {})
                st.subheader("📈 Mancini 0DTE — SPY")
                state = m.get("state", "IDLE")
                state_colors = {
                    "IDLE": "🔵", "NEAR_LEVEL": "🟡", "FLUSH_DETECTED": "🟠",
                    "ACCEPTANCE_WAIT": "🟠", "ENTERED": "🟢", "TIER1_HIT": "🟢", "EXITED": "⚫",
                }
                emoji = state_colors.get(state, "⚪")
                st.markdown(f"**State:** {emoji} {state}")

                mc1, mc2, mc3 = st.columns(3)
                mc1.metric("Prior Day Low", f"${m.get('prior_day_low', 0):.2f}")
                mc2.metric("Flush Low",     f"${m.get('flush_low', 0):.2f}" if m.get("flush_low") else "—")
                mc3.metric("Flush Size",    f"${m.get('flush_size', 0):.2f}" if m.get("flush_size") else "—")

                if state == "ACCEPTANCE_WAIT":
                    elapsed = m.get("acceptance_candles_elapsed", 0)
                    needed  = m.get("acceptance_candles_needed", 2)
                    st.progress(min(elapsed / max(needed, 1), 1.0),
                                text=f"Acceptance: {elapsed}/{needed} candles ({m.get('flush_type','').title()} FB)")

                if state in ("ENTERED", "TIER1_HIT"):
                    ec1, ec2, ec3 = st.columns(3)
                    ec1.metric("Entry",  f"${m.get('entry_price', 0):.2f}" if m.get('entry_price') else "—")
                    ec2.metric("Stop",   f"${m.get('stop_price', 0):.2f}"  if m.get('stop_price')  else "—")
                    ec3.metric("Target", f"${m.get('target1', 0):.2f}"     if m.get('target1')     else "—")

                st.divider()

                # v5 Watchlist
                st.subheader("🎯 v5 Buy Zone Watchlist")
                wl = mlog.get("v5_watchlist", [])
                if wl:
                    wl_df = pd.DataFrame(wl)
                    wl_df = wl_df.rename(columns={
                        "ticker": "Ticker", "score": "Score", "flow": "Flow",
                        "buy_zone_low": "Zone Low", "buy_zone_high": "Zone High",
                        "live_price": "Live Price", "status": "Status",
                    })
                    st.dataframe(wl_df, use_container_width=True)
                else:
                    st.info("No watchlist data yet")

                st.divider()

                # Events log
                st.subheader("📋 Recent Events")
                events = mlog.get("recent_events", [])
                if events:
                    for ev in reversed(events):
                        st.text(ev)
                else:
                    st.info("No events yet")

            except Exception as e:
                st.error(f"Error reading monitor_log.json: {e}")

        # Auto-refresh every 30 seconds
        time.sleep(30)
        st.rerun()


# ═══════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if HAS_STREAMLIT:
        run_dashboard()
    else:
        print("Streamlit not installed. Install with: pip install streamlit")
        print("Then run: streamlit run autotrader_dashboard.py")
        
        # Quick CLI test
        print("\nRunning quick engine test...")
        config = BotConfig(mode="dry")
        engine = AutotraderEngine(config)
        
        # Create test data
        test = pd.DataFrame({
            "ticker": ["AMAT", "VRTX", "NET", "WEAK"],
            "price": [354.91, 491.47, 195.85, 3.50],
            "sma20_pct": [8.9, 5.1, 8.9, -5.0],
            "sma50_pct": [20.5, 6.8, 2.7, -10.0],
            "sma200_pct": [63.5, 12.8, 0.7, -20.0],
            "rel_volume": [2.02, 2.03, 1.76, 0.3],
            "perf_week": [10.05, 2.84, 13.07, -5.0],
            "perf_quarter": [53.82, 13.19, -13.22, -30.0],
            "rsi": [64.66, 62.63, 57.19, 28.0],
            "oi_chg_skew": [-3807, 1013, -1012, -500],
            "put_call_ratio": [0.79, 0.61, 0.28, 1.8],
            "dp_buy_pct": [45.7, 62.1, 61.2, 20.0],
            "dp_notional_m": [1107.9, 282.9, 184.1, 2.0],
            "dp_prints": [200, 100, 150, 5],
            "avg_volume": [5000000, 2000000, 3000000, 10000],
            "atr": [17.44, 14.11, 12.49, 0.50],
        })
        
        scored = score_universe_v5(test)
        result = engine.run_cycle(scored)
        
        print(f"\nEntry signals: {len(result['entry_signals'])}")
        for sig in result["entry_signals"]:
            print(f"  {sig['ticker']:6s} | Score: {sig['score']:5.1f} | "
                  f"Shares: {sig['shares']:4d} | ${sig['dollar_amount']:,.0f} | "
                  f"Stop: ${sig['stop_price']:.2f}")
