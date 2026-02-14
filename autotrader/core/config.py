"""
config.py — Central configuration for RD AutoTrader

All tunable parameters live here. Risk limits, sizing rules, strategy params.
API keys loaded from environment variables — NEVER hardcoded.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()


# ---------------------------------------------------------------------------
# API / BROKER CONFIG
# ---------------------------------------------------------------------------
@dataclass
class BrokerConfig:
    api_key: str = ""
    secret_key: str = ""
    base_url: str = "https://paper-api.alpaca.markets"
    trading_mode: str = "paper"  # "paper" or "live"
    data_feed: str = "iex"      # "iex" (free) or "sip" (paid, more complete)

   def __post_init__(self):
        self.api_key = os.environ.get("ALPACA_API_KEY", self.api_key)
        self.secret_key = os.environ.get("ALPACA_SECRET_KEY", self.secret_key)
        self.base_url = os.environ.get("ALPACA_BASE_URL", self.base_url)
        self.trading_mode = os.environ.get("TRADING_MODE", self.trading_mode)

        # Fallback: Streamlit secrets (for Streamlit Cloud deployment)
        if not self.api_key or not self.secret_key:
            try:
                import streamlit as st
                self.api_key = self.api_key or st.secrets.get("ALPACA_API_KEY", "")
                self.secret_key = self.secret_key or st.secrets.get("ALPACA_SECRET_KEY", "")
                self.base_url = st.secrets.get("ALPACA_BASE_URL", self.base_url)
            except Exception:
                pass

        if not self.api_key or not self.secret_key:
            raise ValueError(
                "ALPACA_API_KEY and ALPACA_SECRET_KEY must be set as environment "
                "variables or in a .env file. See README.md for setup."
            )

    @property
    def is_paper(self) -> bool:
        return "paper" in self.base_url.lower() or self.trading_mode == "paper"


# ---------------------------------------------------------------------------
# RISK MANAGEMENT CONFIG
# ---------------------------------------------------------------------------
@dataclass
class RiskConfig:
    # Position sizing
    max_position_pct: float = 5.0           # Max % of equity per position
    min_position_usd: float = 500.0         # Floor — don't bother below this
    max_position_usd: float = 25000.0       # Hard cap per position regardless of equity

    # Portfolio-level limits
    max_open_positions: int = 10            # Max simultaneous positions
    max_sector_exposure_pct: float = 25.0   # Max % equity in one sector
    max_correlated_positions: int = 3       # Max positions in same sector

    # Daily circuit breakers
    daily_loss_halt_pct: float = -3.0       # If daily P&L hits this, halt all entries
    daily_loss_reduce_pct: float = -2.0     # If daily P&L hits this, reduce size 50%
    weekly_loss_halt_pct: float = -5.0      # Weekly halt threshold

    # Per-trade risk
    max_risk_per_trade_pct: float = 1.0     # Max loss per trade as % of equity
    mandatory_stop_loss: bool = True        # Every entry MUST have a stop
    default_stop_pct: float = 5.0           # Default stop loss % below entry
    default_trail_pct: float = 4.0          # Default trailing stop %

    # Time-based rules
    max_hold_days: int = 14                 # Force review/exit after N days
    flatten_before_weekend: bool = False    # Close all positions Friday EOD
    no_entry_last_30min: bool = True        # Don't enter after 3:30 PM ET
    no_entry_first_15min: bool = True       # Don't enter before 9:45 AM ET

    # Compounding
    compound_gains: bool = True             # Scale sizes with equity growth
    rebalance_frequency: str = "daily"      # How often to recalculate sizing base


# ---------------------------------------------------------------------------
# STRATEGY CONFIG
# ---------------------------------------------------------------------------
@dataclass
class StrategyConfig:
    # Signal thresholds (from our pipeline scoring)
    min_entry_score: float = 65.0           # Minimum bullish_setup_score to enter
    min_crowding_score: float = 40.0        # Minimum crowding (options+DP flow)
    max_overextended_pct: float = 12.0      # Don't enter if >12% above SMA20

    # Entry behavior
    use_limit_orders: bool = True           # Limit vs market orders
    limit_offset_pct: float = 0.15          # Limit price offset from current (tighter=more fills)
    entry_timeout_minutes: int = 60         # Cancel unfilled limit orders after N min

    # Scale-out rules
    scale_out_enabled: bool = True
    target_1_pct: float = 3.0              # First target: +3%
    target_1_sell_pct: float = 50.0        # Sell 50% at Target 1
    target_2_pct: float = 6.0             # Second target: +6%
    target_2_sell_pct: float = 30.0        # Sell 30% at Target 2
    trail_remainder: bool = True           # Trail remaining 20% with trailing stop

    # Structures we trade (from pipeline classification)
    allowed_structures: List[str] = field(default_factory=lambda: [
        "Momentum", "Breakout", "Reversal", "Uptrend"
    ])
    blocked_structures: List[str] = field(default_factory=lambda: [
        "Range/Weak", "Unknown"
    ])

    # Session windows (Eastern Time)
    trading_start: str = "09:45"           # Earliest entry time
    trading_end: str = "15:30"             # Latest entry time
    exit_window_start: str = "15:45"       # Begin EOD exit processing
    market_close: str = "16:00"

    # Holding periods by strategy type
    hold_periods: Dict[str, int] = field(default_factory=lambda: {
        "momentum_breakout": 5,     # 1 week for momentum plays
        "mean_reversion": 3,        # 3 days for dip buys
        "earnings_catalyst": 2,     # In/out around event
        "swing": 10,                # Standard swing hold
    })


# ---------------------------------------------------------------------------
# LOGGING CONFIG
# ---------------------------------------------------------------------------
@dataclass
class LogConfig:
    log_dir: str = "logs"
    trade_log: str = "trades.csv"
    daily_pnl_log: str = "daily_pnl.csv"
    signal_log: str = "signals.csv"
    error_log: str = "errors.log"
    verbose: bool = True                    # Print to console
    log_every_check: bool = False           # Log every position check cycle


# ---------------------------------------------------------------------------
# MASTER CONFIG
# ---------------------------------------------------------------------------
@dataclass
class AutoTraderConfig:
    broker: BrokerConfig = field(default_factory=BrokerConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    logging: LogConfig = field(default_factory=LogConfig)

    # Bot behavior
    check_interval_seconds: int = 30        # How often the main loop checks positions
    signal_poll_seconds: int = 300          # How often to poll for new signals (5 min)
    dry_run: bool = False                   # If True, log orders but don't submit


def load_config() -> AutoTraderConfig:
    """Load config with env vars. Call this at startup."""
    return AutoTraderConfig()


if __name__ == "__main__":
    # Quick validation
    try:
        cfg = load_config()
        print(f"Config loaded successfully.")
        print(f"  Mode:           {cfg.broker.trading_mode}")
        print(f"  Paper:          {cfg.broker.is_paper}")
        print(f"  Base URL:       {cfg.broker.base_url}")
        print(f"  Max pos size:   {cfg.risk.max_position_pct}%")
        print(f"  Max positions:  {cfg.risk.max_open_positions}")
        print(f"  Min entry score:{cfg.strategy.min_entry_score}")
        print(f"  Daily halt:     {cfg.risk.daily_loss_halt_pct}%")
    except ValueError as e:
        print(f"Config error: {e}")
