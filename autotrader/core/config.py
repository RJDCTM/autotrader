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

        if not self.api_key or not self.secret_key:
            try:
                import streamlit as st
                self.api_key = self.api_key or st.secrets["ALPACA_API_KEY"]
                self.secret_key = self.secret_key or st.secrets["ALPACA_SECRET_KEY"]
                self.base_url = st.secrets.get("ALPACA_BASE_URL", self.base_url)
            except Exception:
                pass

        if not self.api_key or not self.secret_key:
            raise ValueError(
                "ALPACA_API_KEY and ALPACA_SECRET_KEY must be set as environment "
                "variables, in a .env file, or in Streamlit secrets."
            )

    @property
    def is_paper(self) -> bool:
        return "paper" in self.base_url.lower() or self.trading_mode == "paper"


# ---------------------------------------------------------------------------
# RISK MANAGEMENT CONFIG
# ---------------------------------------------------------------------------
@dataclass
class RiskConfig:
    max_position_pct: float = 5.0
    min_position_usd: float = 500.0
    max_position_usd: float = 25000.0
    max_open_positions: int = 10
    max_sector_exposure_pct: float = 25.0
    max_correlated_positions: int = 3
    daily_loss_halt_pct: float = -3.0
    daily_loss_reduce_pct: float = -2.0
    weekly_loss_halt_pct: float = -5.0
    max_risk_per_trade_pct: float = 1.0
    mandatory_stop_loss: bool = True
    default_stop_pct: float = 5.0
    default_trail_pct: float = 4.0
    max_hold_days: int = 14
    flatten_before_weekend: bool = False
    no_entry_last_30min: bool = True
    no_entry_first_15min: bool = True
    compound_gains: bool = True
    rebalance_frequency: str = "daily"


# ---------------------------------------------------------------------------
# STRATEGY CONFIG
# ---------------------------------------------------------------------------
@dataclass
class StrategyConfig:
    min_entry_score: float = 65.0
    min_crowding_score: float = 40.0
    max_overextended_pct: float = 12.0
    use_limit_orders: bool = True
    limit_offset_pct: float = 0.15
    entry_timeout_minutes: int = 60
    scale_out_enabled: bool = True
    target_1_pct: float = 3.0
    target_1_sell_pct: float = 50.0
    target_2_pct: float = 6.0
    target_2_sell_pct: float = 30.0
    trail_remainder: bool = True
    allowed_structures: List[str] = field(default_factory=lambda: [
        "Momentum", "Breakout", "Reversal", "Uptrend"
    ])
    blocked_structures: List[str] = field(default_factory=lambda: [
        "Range/Weak", "Unknown"
    ])
    trading_start: str = "09:45"
    trading_end: str = "15:30"
    exit_window_start: str = "15:45"
    market_close: str = "16:00"
    hold_periods: Dict[str, int] = field(default_factory=lambda: {
        "momentum_breakout": 5,
        "mean_reversion": 3,
        "earnings_catalyst": 2,
        "swing": 10,
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
    verbose: bool = True
    log_every_check: bool = False


# ---------------------------------------------------------------------------
# MASTER CONFIG
# ---------------------------------------------------------------------------
@dataclass
class AutoTraderConfig:
    broker: BrokerConfig = field(default_factory=BrokerConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    logging: LogConfig = field(default_factory=LogConfig)
    check_interval_seconds: int = 30
    signal_poll_seconds: int = 300
    dry_run: bool = False


def load_config() -> AutoTraderConfig:
    """Load config with env vars. Call this at startup."""
    return AutoTraderConfig()


if __name__ == "__main__":
    try:
        cfg = load_config()
        print(f"Config loaded successfully.")
        print(f"  Mode:           {cfg.broker.trading_mode}")
        print(f"  Paper:          {cfg.broker.is_paper}")
        print(f"  Base URL:       {cfg.broker.base_url}")
    except ValueError as e:
        print(f"Config error: {e}")
