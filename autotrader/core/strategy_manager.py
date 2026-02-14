"""
strategy_manager.py — Virtual Strategy Bucketing System

Manages multiple strategies within a single Alpaca paper account.
Each strategy gets its own:
- Capital allocation ($10K each)
- Entry/exit rules (hold period, sizing, stop %)
- P&L tracking (independent win rate, total return, Sharpe)
- Position tracking (knows which trades belong to which strategy)

Think of it like running 5 separate accounts inside one.
"""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple


class StrategyID(Enum):
    SHORT_MOMENTUM = "short_momentum"
    PIPELINE_SWING = "pipeline_swing"
    MEAN_REVERSION = "mean_reversion"
    SECTOR_ETF = "sector_etf"
    SECTOR_STOCKS = "sector_stocks"


# ---------------------------------------------------------------------------
# STRATEGY DEFINITIONS
# ---------------------------------------------------------------------------

@dataclass
class StrategyProfile:
    """
    Defines the rules and personality of each strategy bucket.
    Each one trades differently — the bot enforces the rules.
    """
    strategy_id: StrategyID
    name: str
    description: str

    # Capital allocation
    starting_capital: float = 10000.0
    current_capital: float = 10000.0       # Updated as trades close

    # Position rules
    max_positions: int = 5
    max_position_pct: float = 25.0          # Max % of bucket capital per trade
    max_risk_per_trade_pct: float = 2.0     # Max loss per trade as % of bucket

    # Entry rules
    min_score: float = 60.0                 # Minimum pipeline score to enter
    use_limit_orders: bool = True
    limit_offset_pct: float = 0.15

    # Exit rules
    default_stop_pct: float = 5.0
    target_1_pct: float = 3.0
    target_2_pct: float = 6.0
    trail_stop_pct: float = 4.0
    max_hold_days: int = 5
    scale_out_at_t1_pct: float = 50.0      # Sell 50% at Target 1
    scale_out_at_t2_pct: float = 30.0      # Sell 30% at Target 2

    # Allowed structures (from pipeline)
    allowed_structures: List[str] = field(default_factory=lambda: ["Momentum", "Breakout"])

    # Universe filter
    etfs_only: bool = False
    exclude_etfs: bool = False
    sectors_filter: List[str] = field(default_factory=list)  # Empty = all sectors

    # Compounding
    reinvest_profits: bool = True           # Roll closed P&L back into capital

    # Tracking
    total_trades: int = 0
    winning_trades: int = 0
    total_realized_pnl: float = 0.0
    peak_capital: float = 10000.0
    max_drawdown: float = 0.0


# ---------------------------------------------------------------------------
# PRE-BUILT STRATEGY PROFILES
# ---------------------------------------------------------------------------

def build_default_strategies() -> Dict[StrategyID, StrategyProfile]:
    """
    Create the 5 strategy buckets with their unique rules.
    """
    strategies = {}

    # 1. SHORT-TERM MOMENTUM
    # Fast in, fast out. Ride breakouts for 1-5 days, compound quickly.
    strategies[StrategyID.SHORT_MOMENTUM] = StrategyProfile(
        strategy_id=StrategyID.SHORT_MOMENTUM,
        name="Short-Term Momentum",
        description="1-5 day breakout trades. Fast entries on strength, quick exits. Compound the gains.",
        starting_capital=10000.0,
        current_capital=10000.0,
        max_positions=4,
        max_position_pct=30.0,              # Concentrated bets — fewer positions, bigger size
        max_risk_per_trade_pct=2.0,
        min_score=65.0,
        default_stop_pct=3.5,               # Tight stops — if it's not working fast, get out
        target_1_pct=2.5,                   # Quick first target
        target_2_pct=5.0,
        trail_stop_pct=2.5,                 # Tight trail to protect gains
        max_hold_days=5,                    # 1 week max
        scale_out_at_t1_pct=50.0,
        scale_out_at_t2_pct=30.0,
        allowed_structures=["Momentum", "Breakout"],
        exclude_etfs=True,                  # Individual stocks only
        reinvest_profits=True,
    )

    # 2. PIPELINE SWING TRADES
    # Scored names from weekly pipeline. Wider stops, longer holds.
    strategies[StrategyID.PIPELINE_SWING] = StrategyProfile(
        strategy_id=StrategyID.PIPELINE_SWING,
        name="Pipeline Swing Trades",
        description="5-14 day holds on pipeline-scored names. Full scoring system drives entries.",
        starting_capital=10000.0,
        current_capital=10000.0,
        max_positions=5,
        max_position_pct=25.0,
        max_risk_per_trade_pct=1.5,
        min_score=70.0,                     # Higher bar — only the best setups
        default_stop_pct=5.0,               # Standard stop
        target_1_pct=4.0,
        target_2_pct=8.0,
        trail_stop_pct=4.0,
        max_hold_days=14,                   # 2 weeks max
        scale_out_at_t1_pct=40.0,
        scale_out_at_t2_pct=30.0,
        allowed_structures=["Momentum", "Breakout", "Reversal", "Uptrend"],
        exclude_etfs=True,
        reinvest_profits=True,
    )

    # 3. MEAN REVERSION / DIP BUYS
    # Buy oversold names bouncing off support. Quick 1-3 day holds.
    strategies[StrategyID.MEAN_REVERSION] = StrategyProfile(
        strategy_id=StrategyID.MEAN_REVERSION,
        name="Mean Reversion / Dip Buys",
        description="1-3 day bounce trades on oversold names near support. Buy the dip, sell the rip.",
        starting_capital=10000.0,
        current_capital=10000.0,
        max_positions=4,
        max_position_pct=30.0,
        max_risk_per_trade_pct=2.0,
        min_score=50.0,                     # Lower score OK — these are beaten-down names
        default_stop_pct=4.0,
        target_1_pct=2.0,                   # Quick scalp target
        target_2_pct=4.0,
        trail_stop_pct=2.0,
        max_hold_days=3,                    # Very short hold
        scale_out_at_t1_pct=60.0,           # Take more off the table early
        scale_out_at_t2_pct=30.0,
        allowed_structures=["Reversal", "Consolidation"],
        exclude_etfs=True,
        reinvest_profits=True,
    )

    # 4. SECTOR ROTATION — ETFs
    # Top sector ETFs based on momentum. Longer holds, wider stops.
    strategies[StrategyID.SECTOR_ETF] = StrategyProfile(
        strategy_id=StrategyID.SECTOR_ETF,
        name="Sector Rotation (ETFs)",
        description="2-4 week holds on top-performing sector ETFs (XLE, XLF, XLB, etc.). Ride the wave.",
        starting_capital=10000.0,
        current_capital=10000.0,
        max_positions=3,                    # Concentrated in top 2-3 sectors
        max_position_pct=40.0,              # Bigger positions in ETFs (lower vol)
        max_risk_per_trade_pct=1.5,
        min_score=60.0,
        default_stop_pct=5.0,
        target_1_pct=4.0,
        target_2_pct=8.0,
        trail_stop_pct=4.0,
        max_hold_days=28,                   # 4 weeks max
        scale_out_at_t1_pct=30.0,           # Let winners run longer
        scale_out_at_t2_pct=30.0,
        allowed_structures=["Momentum", "Breakout", "Uptrend"],
        etfs_only=True,                     # Only ETFs
        reinvest_profits=True,
    )

    # 5. SECTOR ROTATION — INDIVIDUAL STOCKS
    # Use ETF sector data to identify hot sectors, then find the best individual names.
    strategies[StrategyID.SECTOR_STOCKS] = StrategyProfile(
        strategy_id=StrategyID.SECTOR_STOCKS,
        name="Sector Rotation (Stock Picks)",
        description="Use ETF momentum to ID hot sectors, then buy top individual names within them. Best of both worlds.",
        starting_capital=10000.0,
        current_capital=10000.0,
        max_positions=5,
        max_position_pct=25.0,
        max_risk_per_trade_pct=1.5,
        min_score=65.0,
        default_stop_pct=6.0,               # Slightly wider — individual stocks are noisier
        target_1_pct=5.0,
        target_2_pct=10.0,
        trail_stop_pct=5.0,
        max_hold_days=21,                   # 3 weeks max
        scale_out_at_t1_pct=40.0,
        scale_out_at_t2_pct=30.0,
        allowed_structures=["Momentum", "Breakout", "Reversal", "Uptrend"],
        exclude_etfs=True,
        reinvest_profits=True,
    )

    return strategies


# ---------------------------------------------------------------------------
# TRACKED POSITION (ties a trade to a strategy)
# ---------------------------------------------------------------------------

@dataclass
class TrackedPosition:
    """An open position tracked by the strategy manager."""
    ticker: str
    strategy_id: StrategyID
    entry_price: float
    qty: int
    side: str = "long"
    entry_date: str = ""
    stop_loss: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0
    trail_pct: float = 0.0
    cost_basis: float = 0.0
    order_id: str = ""
    status: str = "open"                    # open, partial, closed
    notes: str = ""

    # Realized P&L tracking for partial exits
    realized_pnl: float = 0.0
    remaining_qty: int = 0

    def __post_init__(self):
        if not self.entry_date:
            self.entry_date = datetime.now().strftime("%Y-%m-%d")
        if self.remaining_qty == 0:
            self.remaining_qty = self.qty
        if self.cost_basis == 0:
            self.cost_basis = self.entry_price * self.qty

    @property
    def days_held(self) -> int:
        try:
            entry = datetime.strptime(self.entry_date, "%Y-%m-%d")
            return (datetime.now() - entry).days
        except ValueError:
            return 0

    def __str__(self):
        return (
            f"{self.ticker:6s} | {self.strategy_id.value:18s} | "
            f"Entry: ${self.entry_price:.2f} x {self.qty} | "
            f"Stop: ${self.stop_loss:.2f} | T1: ${self.target_1:.2f} | "
            f"Day {self.days_held}"
        )


# ---------------------------------------------------------------------------
# STRATEGY MANAGER
# ---------------------------------------------------------------------------

class StrategyManager:
    """
    Manages all strategy buckets. Central coordinator that:
    - Routes signals to the right strategy
    - Enforces per-strategy position limits and capital allocation
    - Tracks positions by strategy
    - Reports per-strategy performance
    """

    def __init__(self, strategies: Optional[Dict[StrategyID, StrategyProfile]] = None,
                 data_dir: str = "logs"):
        self.strategies = strategies or build_default_strategies()
        self.positions: List[TrackedPosition] = []
        self.closed_trades: List[TrackedPosition] = []
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

        # Load saved state if exists
        self._load_state()

    # ----- CAPITAL CHECKS -----

    def get_available_capital(self, strategy_id: StrategyID) -> float:
        """How much capital is available for new trades in this strategy."""
        profile = self.strategies[strategy_id]
        deployed = sum(
            p.cost_basis for p in self.positions
            if p.strategy_id == strategy_id and p.status == "open"
        )
        return max(0, profile.current_capital - deployed)

    def get_position_count(self, strategy_id: StrategyID) -> int:
        """How many open positions in this strategy."""
        return sum(
            1 for p in self.positions
            if p.strategy_id == strategy_id and p.status == "open"
        )

    def can_open_position(self, strategy_id: StrategyID, cost: float) -> Tuple[bool, str]:
        """Check if a new position is allowed in this strategy."""
        profile = self.strategies[strategy_id]

        # Position count limit
        current_count = self.get_position_count(strategy_id)
        if current_count >= profile.max_positions:
            return False, f"{profile.name}: max positions reached ({current_count}/{profile.max_positions})"

        # Capital limit
        available = self.get_available_capital(strategy_id)
        if cost > available:
            return False, f"{profile.name}: insufficient capital (need ${cost:,.0f}, have ${available:,.0f})"

        # Per-position size limit
        max_per_position = profile.current_capital * (profile.max_position_pct / 100)
        if cost > max_per_position:
            return False, f"{profile.name}: position too large (${cost:,.0f} > ${max_per_position:,.0f} max)"

        return True, "OK"

    # ----- POSITION MANAGEMENT -----

    def open_position(self, position: TrackedPosition) -> bool:
        """Register a new position with a strategy."""
        can_open, reason = self.can_open_position(
            position.strategy_id, position.cost_basis
        )
        if not can_open:
            print(f"[StrategyMgr] Blocked: {reason}")
            return False

        self.positions.append(position)
        self.strategies[position.strategy_id].total_trades += 1
        self._save_state()
        print(f"[StrategyMgr] Opened: {position}")
        return True

    def close_position(self, ticker: str, exit_price: float,
                       qty: Optional[int] = None) -> Optional[float]:
        """
        Close (fully or partially) a tracked position.
        Returns realized P&L or None if position not found.
        """
        pos = self._find_position(ticker)
        if not pos:
            print(f"[StrategyMgr] Position not found: {ticker}")
            return None

        close_qty = qty or pos.remaining_qty
        close_qty = min(close_qty, pos.remaining_qty)

        pnl = (exit_price - pos.entry_price) * close_qty
        pos.realized_pnl += pnl
        pos.remaining_qty -= close_qty

        profile = self.strategies[pos.strategy_id]

        if pos.remaining_qty <= 0:
            pos.status = "closed"
            self.positions.remove(pos)
            self.closed_trades.append(pos)

            # Update strategy stats
            profile.total_realized_pnl += pos.realized_pnl
            if pos.realized_pnl > 0:
                profile.winning_trades += 1

            # Compound: reinvest profits
            if profile.reinvest_profits:
                profile.current_capital += pos.realized_pnl
            else:
                # Only return original cost basis
                profile.current_capital = profile.current_capital  # no change

            # Track peak/drawdown
            if profile.current_capital > profile.peak_capital:
                profile.peak_capital = profile.current_capital
            dd = (profile.peak_capital - profile.current_capital) / profile.peak_capital * 100
            if dd > profile.max_drawdown:
                profile.max_drawdown = dd

            print(f"[StrategyMgr] Closed: {ticker} | P&L: ${pos.realized_pnl:+,.2f}")
        else:
            pos.status = "partial"
            print(f"[StrategyMgr] Partial close: {ticker} | Sold {close_qty} | "
                  f"Remaining: {pos.remaining_qty} | P&L so far: ${pos.realized_pnl:+,.2f}")

        self._save_state()
        return pnl

    def check_time_exits(self) -> List[TrackedPosition]:
        """Find positions that have exceeded their strategy's max hold period."""
        exits = []
        for pos in self.positions:
            if pos.status != "open":
                continue
            profile = self.strategies[pos.strategy_id]
            if pos.days_held >= profile.max_hold_days:
                exits.append(pos)
        return exits

    # ----- SIGNAL ROUTING -----

    def calculate_position_size(self, strategy_id: StrategyID,
                                entry_price: float, stop_price: float) -> int:
        """
        Calculate share count based on strategy rules.
        Uses the more conservative of % capital and risk-based sizing.
        """
        profile = self.strategies[strategy_id]

        # Method 1: % of bucket capital
        max_usd = profile.current_capital * (profile.max_position_pct / 100)

        # Method 2: Risk-based (max loss = X% of bucket capital)
        risk_per_share = abs(entry_price - stop_price)
        if risk_per_share > 0:
            max_loss_usd = profile.current_capital * (profile.max_risk_per_trade_pct / 100)
            risk_based_usd = (max_loss_usd / risk_per_share) * entry_price
        else:
            risk_based_usd = max_usd

        position_usd = min(max_usd, risk_based_usd)
        shares = int(position_usd / entry_price) if entry_price > 0 else 0
        return max(shares, 0)

    # ----- REPORTING -----

    def get_strategy_report(self, strategy_id: StrategyID) -> Dict:
        """Get performance summary for a single strategy."""
        profile = self.strategies[strategy_id]
        open_positions = [p for p in self.positions if p.strategy_id == strategy_id]
        closed = [p for p in self.closed_trades if p.strategy_id == strategy_id]

        win_rate = (profile.winning_trades / profile.total_trades * 100) if profile.total_trades > 0 else 0
        total_return_pct = ((profile.current_capital - profile.starting_capital) / profile.starting_capital * 100)

        return {
            "name": profile.name,
            "strategy_id": strategy_id.value,
            "starting_capital": profile.starting_capital,
            "current_capital": round(profile.current_capital, 2),
            "total_return": round(profile.current_capital - profile.starting_capital, 2),
            "total_return_pct": round(total_return_pct, 2),
            "total_trades": profile.total_trades,
            "winning_trades": profile.winning_trades,
            "win_rate": round(win_rate, 1),
            "total_realized_pnl": round(profile.total_realized_pnl, 2),
            "max_drawdown_pct": round(profile.max_drawdown, 2),
            "open_positions": len(open_positions),
            "max_positions": profile.max_positions,
            "available_capital": round(self.get_available_capital(strategy_id), 2),
        }

    def get_full_report(self) -> Dict:
        """Get performance summary for all strategies."""
        reports = {}
        total_capital = 0
        total_pnl = 0
        total_trades = 0

        for sid in self.strategies:
            report = self.get_strategy_report(sid)
            reports[sid.value] = report
            total_capital += report["current_capital"]
            total_pnl += report["total_return"]
            total_trades += report["total_trades"]

        reports["_summary"] = {
            "total_capital": round(total_capital, 2),
            "total_starting": sum(s.starting_capital for s in self.strategies.values()),
            "total_pnl": round(total_pnl, 2),
            "total_trades": total_trades,
            "dry_powder": round(100000 - sum(s.starting_capital for s in self.strategies.values()), 2),
        }

        return reports

    def print_dashboard(self):
        """Print a formatted strategy performance dashboard."""
        print("\n" + "=" * 72)
        print("  RD AutoTrader — Strategy Dashboard")
        print("=" * 72)

        full = self.get_full_report()
        summary = full["_summary"]

        print(f"\n  Total Deployed: ${summary['total_starting']:,.0f}  |  "
              f"Current Value: ${summary['total_capital']:,.0f}  |  "
              f"Total P&L: ${summary['total_pnl']:+,.2f}")
        print(f"  Dry Powder: ${summary['dry_powder']:,.0f}  |  "
              f"Total Trades: {summary['total_trades']}")
        print("-" * 72)

        for sid in self.strategies:
            r = full[sid.value]
            status_bar = self._bar(r["total_return_pct"], width=20)

            print(f"\n  {r['name']}")
            print(f"    Capital: ${r['current_capital']:>10,.2f}  "
                  f"({r['total_return_pct']:+.1f}%)  {status_bar}")
            print(f"    Trades:  {r['total_trades']:>3d}  |  "
                  f"Win Rate: {r['win_rate']:.0f}%  |  "
                  f"Max DD: {r['max_drawdown_pct']:.1f}%")
            print(f"    Open:    {r['open_positions']}/{r['max_positions']}  |  "
                  f"Available: ${r['available_capital']:,.0f}")

        # Open positions by strategy
        if self.positions:
            print("\n" + "-" * 72)
            print("  Open Positions:")
            for sid in self.strategies:
                positions = [p for p in self.positions if p.strategy_id == sid]
                if positions:
                    print(f"\n    [{self.strategies[sid].name}]")
                    for p in positions:
                        print(f"      {p}")

        print("\n" + "=" * 72)

    @staticmethod
    def _bar(pct: float, width: int = 20) -> str:
        """Simple text-based performance bar."""
        if pct >= 0:
            filled = min(int(pct / 2), width)
            return "\u2588" * filled + "\u2591" * (width - filled) + f" +{pct:.1f}%"
        else:
            filled = min(int(abs(pct) / 2), width)
            return "\u2591" * (width - filled) + "\u2588" * filled + f" {pct:.1f}%"

    # ----- PERSISTENCE -----

    def _save_state(self):
        """Save positions and strategy state to disk."""
        state = {
            "strategies": {},
            "positions": [],
            "closed_trades": [],
        }

        for sid, profile in self.strategies.items():
            state["strategies"][sid.value] = {
                "current_capital": profile.current_capital,
                "total_trades": profile.total_trades,
                "winning_trades": profile.winning_trades,
                "total_realized_pnl": profile.total_realized_pnl,
                "peak_capital": profile.peak_capital,
                "max_drawdown": profile.max_drawdown,
            }

        for p in self.positions:
            state["positions"].append({
                "ticker": p.ticker,
                "strategy_id": p.strategy_id.value,
                "entry_price": p.entry_price,
                "qty": p.qty,
                "entry_date": p.entry_date,
                "stop_loss": p.stop_loss,
                "target_1": p.target_1,
                "target_2": p.target_2,
                "trail_pct": p.trail_pct,
                "cost_basis": p.cost_basis,
                "order_id": p.order_id,
                "status": p.status,
                "realized_pnl": p.realized_pnl,
                "remaining_qty": p.remaining_qty,
            })

        for p in self.closed_trades[-100:]:  # Keep last 100
            state["closed_trades"].append({
                "ticker": p.ticker,
                "strategy_id": p.strategy_id.value,
                "entry_price": p.entry_price,
                "qty": p.qty,
                "entry_date": p.entry_date,
                "realized_pnl": p.realized_pnl,
            })

        path = os.path.join(self.data_dir, "strategy_state.json")
        with open(path, "w") as f:
            json.dump(state, f, indent=2)

    def _load_state(self):
        """Load saved state from disk."""
        path = os.path.join(self.data_dir, "strategy_state.json")
        if not os.path.exists(path):
            return

        try:
            with open(path, "r") as f:
                state = json.load(f)

            # Restore strategy stats
            for sid_str, stats in state.get("strategies", {}).items():
                try:
                    sid = StrategyID(sid_str)
                    if sid in self.strategies:
                        self.strategies[sid].current_capital = stats["current_capital"]
                        self.strategies[sid].total_trades = stats["total_trades"]
                        self.strategies[sid].winning_trades = stats["winning_trades"]
                        self.strategies[sid].total_realized_pnl = stats["total_realized_pnl"]
                        self.strategies[sid].peak_capital = stats["peak_capital"]
                        self.strategies[sid].max_drawdown = stats["max_drawdown"]
                except (ValueError, KeyError):
                    pass

            # Restore open positions
            for p_data in state.get("positions", []):
                try:
                    self.positions.append(TrackedPosition(
                        ticker=p_data["ticker"],
                        strategy_id=StrategyID(p_data["strategy_id"]),
                        entry_price=p_data["entry_price"],
                        qty=p_data["qty"],
                        entry_date=p_data.get("entry_date", ""),
                        stop_loss=p_data.get("stop_loss", 0),
                        target_1=p_data.get("target_1", 0),
                        target_2=p_data.get("target_2", 0),
                        trail_pct=p_data.get("trail_pct", 0),
                        cost_basis=p_data.get("cost_basis", 0),
                        order_id=p_data.get("order_id", ""),
                        status=p_data.get("status", "open"),
                        realized_pnl=p_data.get("realized_pnl", 0),
                        remaining_qty=p_data.get("remaining_qty", 0),
                    ))
                except (ValueError, KeyError):
                    pass

            print(f"[StrategyMgr] Loaded state: {len(self.positions)} open positions")
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[StrategyMgr] Could not load state: {e}")

    # ----- INTERNAL -----

    def _find_position(self, ticker: str) -> Optional[TrackedPosition]:
        for p in self.positions:
            if p.ticker.upper() == ticker.upper() and p.status in ("open", "partial"):
                return p
        return None


# ---------------------------------------------------------------------------
# SECTOR ROTATION LOGIC (for Strategy 5)
# ---------------------------------------------------------------------------

# Sector ETF mapping
SECTOR_ETFS = {
    "XLE": "Energy",
    "XLF": "Financials",
    "XLK": "Technology",
    "XLV": "Health Care",
    "XLI": "Industrials",
    "XLP": "Consumer Staples",
    "XLY": "Consumer Discretionary",
    "XLB": "Materials",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
}

def rank_sectors_by_momentum(etf_data: Dict[str, Dict]) -> List[Tuple[str, str, float]]:
    """
    Rank sectors by momentum using ETF performance data.

    Args:
        etf_data: Dict of {ticker: {perf_week, perf_month, perf_quarter, ...}}

    Returns:
        List of (etf_ticker, sector_name, momentum_score) sorted best to worst
    """
    rankings = []
    for etf, sector in SECTOR_ETFS.items():
        if etf not in etf_data:
            continue
        d = etf_data[etf]
        # Weighted momentum: recent performance matters more
        pw = float(d.get("perf_week", 0) or 0)
        pm = float(d.get("perf_month", 0) or 0)
        pq = float(d.get("perf_quarter", 0) or 0)
        score = (pw * 0.50) + (pm * 0.35) + (pq * 0.15)
        rankings.append((etf, sector, round(score, 2)))

    rankings.sort(key=lambda x: x[2], reverse=True)
    return rankings


def filter_stocks_by_sector(stocks_df, top_sectors: List[str],
                            min_score: float = 65.0) -> list:
    """
    Filter pipeline-scored stocks to only those in top-ranked sectors.

    Args:
        stocks_df: DataFrame with 'ticker', 'sector', 'bullish_setup_score'
        top_sectors: List of sector names to include
        min_score: Minimum bullish score

    Returns:
        List of qualifying ticker dicts sorted by score
    """
    import pandas as pd

    mask = (
        stocks_df["sector"].isin(top_sectors) &
        (stocks_df["bullish_setup_score"] >= min_score)
    )
    filtered = stocks_df[mask].sort_values("bullish_setup_score", ascending=False)
    return filtered.to_dict("records")


# ---------------------------------------------------------------------------
# QUICK TEST
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mgr = StrategyManager()

    # Show the dashboard with starting state
    mgr.print_dashboard()

    # Show sector rankings with sample data
    print("\n\nSector Momentum Rankings (sample data):")
    print("-" * 50)
    sample_etf_data = {
        "XLE": {"perf_week": 3.2, "perf_month": 7.1, "perf_quarter": 12.5},
        "XLF": {"perf_week": 1.5, "perf_month": 4.2, "perf_quarter": 8.0},
        "XLK": {"perf_week": -0.5, "perf_month": 2.1, "perf_quarter": 5.3},
        "XLV": {"perf_week": 0.8, "perf_month": 1.5, "perf_quarter": 3.2},
        "XLI": {"perf_week": 2.1, "perf_month": 5.5, "perf_quarter": 9.1},
        "XLB": {"perf_week": 2.8, "perf_month": 6.0, "perf_quarter": 10.2},
        "XLU": {"perf_week": 1.2, "perf_month": 3.8, "perf_quarter": 6.5},
        "XLY": {"perf_week": -1.0, "perf_month": 0.5, "perf_quarter": 2.1},
        "XLP": {"perf_week": 0.3, "perf_month": 1.0, "perf_quarter": 2.8},
        "XLC": {"perf_week": -0.2, "perf_month": 1.8, "perf_quarter": 4.0},
        "XLRE": {"perf_week": 0.5, "perf_month": 2.0, "perf_quarter": 3.5},
    }

    rankings = rank_sectors_by_momentum(sample_etf_data)
    for i, (etf, sector, score) in enumerate(rankings, 1):
        marker = " <-- TOP 3" if i <= 3 else ""
        print(f"  {i:2d}. {etf:5s} ({sector:25s})  Score: {score:+6.2f}{marker}")
