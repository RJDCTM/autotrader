"""
Autotrader v5 — Fully Automated Monitor
========================================
Runs all day unattended. Handles:
  1. Mancini 0DTE:  Failed breakdown detection on SPY → auto-execute bracket orders
  2. v5 Buy Zone:   Poll top setups → auto-execute when price enters buy zone
  3. v5 Exits:      Auto-exit open positions based on score/gate/extension/stop rules

Run:
    python mancini_monitor.py

Reads:  monitor_config.json   (credentials + params)
        Quickview_v5_Feb17.csv (scored universe)
Writes: monitor_log.json      (live status for dashboard Tab 7)
"""

from __future__ import annotations
import os
import json
import time
import logging
import math
from datetime import datetime, date
from zoneinfo import ZoneInfo
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List
from pathlib import Path

import pandas as pd
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("monitor")

EST = ZoneInfo("America/New_York")

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).parent

def load_config() -> dict:
    cfg_path = BASE_DIR / "monitor_config.json"
    with open(cfg_path) as f:
        cfg = json.load(f)
    # Env vars override config file
    cfg["alpaca_api_key"]    = os.environ.get("ALPACA_API_KEY",    cfg.get("alpaca_api_key", ""))
    cfg["alpaca_api_secret"] = os.environ.get("ALPACA_API_SECRET", cfg.get("alpaca_api_secret", ""))
    return cfg


# ═══════════════════════════════════════════════════════════════
# MANCINI PARAMETERS  (from Mancini_0DTE_Framework_Complete.xlsx)
# ═══════════════════════════════════════════════════════════════

MANCINI = {
    "ticker":                    "SPY",
    "near_level_buffer":          2.00,   # Start watching within $2 of prior day low
    "fb_min_flush":               1.00,   # Minimum flush to qualify
    "fb_flush_deep_threshold":    3.00,   # >= $3 = deep FB
    "fb_max_flush":               8.00,   # > $8 = real breakdown, abort
    "acceptance_candles_shallow": 2,      # 5-min candles = 10 min
    "acceptance_candles_deep":   12,      # 5-min candles = 60 min
    "stop_buffer":                0.50,   # $0.50 below flush low
    "danger_zone_buffer":         5.00,   # Form 3: must be > $5 above flush low
    "min_reward_risk":            2.0,    # Minimum 2:1 R:R
    "tier1_exit_pct":             0.75,   # Exit 75% at first target
    "tier1_target_mult":          2.0,    # T1 = entry + 2× stop distance
    "risk_per_trade":           500.0,    # $ risk per Mancini trade
    "primary_start_hour":          8,     # 8:00 AM EST — window opens
    "primary_end_hour":           11,     # 11:00 AM EST — primary closes
    "chop_start_hour":            11,     # 11 AM–2 PM = chop, avoid
    "chop_end_hour":              14,     # 2:00 PM = secondary window opens
    "entry_cutoff_hour":          15,     # 3:00 PM = no new entries
    "force_exit_hour":            15,     # 3:50 PM = force close all
    "force_exit_minute":          50,
}


# ═══════════════════════════════════════════════════════════════
# ALPACA CLIENT WRAPPER
# ═══════════════════════════════════════════════════════════════

class AlpacaClient:
    """Thin wrapper around alpaca-py for trading + market data."""

    def __init__(self, api_key: str, api_secret: str, paper: bool = True):
        self.paper = paper
        self.trading = None
        self.data = None
        self._connect(api_key, api_secret, paper)

    def _connect(self, api_key, api_secret, paper):
        try:
            from alpaca.trading.client import TradingClient
            from alpaca.data.historical import StockHistoricalDataClient
            if api_key and api_secret:
                self.trading = TradingClient(api_key, api_secret, paper=paper)
                self.data    = StockHistoricalDataClient(api_key, api_secret)
                log.info("Connected to Alpaca (%s)", "PAPER" if paper else "LIVE")
            else:
                log.warning("No Alpaca credentials — DRY MODE (no orders will execute)")
        except Exception as e:
            log.error("Alpaca connect failed: %s", e)

    @property
    def dry_mode(self) -> bool:
        return self.trading is None

    # ── Market data ──────────────────────────────────────────

    def get_prior_day_levels(self, ticker: str) -> dict:
        """
        Return today's session high/low built from 1-min intraday bars.
        Falls back to latest trade price ± buffer if bars unavailable.
        """
        if self.dry_mode:
            return {"high": 600.0, "low": 592.0}
        try:
            from alpaca.data.requests import StockBarsRequest, StockLatestTradeRequest
            from alpaca.data.timeframe import TimeFrame
            from datetime import timedelta, timezone

            # Fetch today's 1-min bars (up to 390 bars = full session)
            now_utc = datetime.now(timezone.utc)
            start   = now_utc.replace(hour=13, minute=30, second=0, microsecond=0)  # 9:30 AM EST = 13:30 UTC
            if now_utc < start:
                start = start - timedelta(days=1)

            req = StockBarsRequest(
                symbol_or_symbols=ticker,
                timeframe=TimeFrame.Minute,
                start=start,
                limit=390,
            )
            bars = self.data.get_stock_bars(req)
            bar_data = getattr(bars, "data", {})
            bar_list = bar_data.get(ticker) or bar_data.get(ticker.upper()) or []

            if bar_list:
                highs  = [float(b.high)  for b in bar_list]
                lows   = [float(b.low)   for b in bar_list]
                closes = [float(b.close) for b in bar_list]
                result = {"high": max(highs), "low": min(lows), "close": closes[-1]}
                log.info("Session %s (%d bars) — Low: $%.2f | High: $%.2f",
                         ticker, len(bar_list), result["low"], result["high"])
                return result

            # Final fallback: use latest trade ± 0.5%
            req2 = StockLatestTradeRequest(symbol_or_symbols=[ticker])
            trades = self.data.get_stock_latest_trade(req2)
            trade_data = getattr(trades, "data", trades) if not isinstance(trades, dict) else trades
            trade = trade_data.get(ticker)
            if trade:
                price = float(trade.price if hasattr(trade, "price") else trade["price"])
                result = {"high": round(price * 1.005, 2), "low": round(price * 0.995, 2), "close": price}
                log.warning("No intraday bars — using estimated levels from latest price $%.2f", price)
                return result

            return {}
        except Exception as e:
            log.error("get_prior_day_levels error: %s", e)
            return {}

    def get_latest_prices(self, tickers: List[str]) -> Dict[str, float]:
        """Return latest trade price for each ticker."""
        if self.dry_mode:
            return {}
        try:
            from alpaca.data.requests import StockLatestTradeRequest
            req = StockLatestTradeRequest(symbol_or_symbols=tickers)
            trades = self.data.get_stock_latest_trade(req)
            return {sym: float(t.price) for sym, t in trades.items()}
        except Exception as e:
            log.error("get_latest_prices error: %s", e)
            return {}

    def get_latest_bar(self, ticker: str) -> Optional[dict]:
        """Return latest 5-min bar for a ticker."""
        if self.dry_mode:
            return None
        try:
            from alpaca.data.requests import StockLatestBarRequest
            req = StockLatestBarRequest(symbol_or_symbols=[ticker])
            bars = self.data.get_stock_latest_bar(req)
            b = bars[ticker]
            return {"open": float(b.open), "high": float(b.high),
                    "low": float(b.low), "close": float(b.close),
                    "volume": float(b.volume)}
        except Exception as e:
            log.error("get_latest_bar error: %s", e)
            return None

    # ── Account ───────────────────────────────────────────────

    def get_account(self) -> dict:
        if self.dry_mode:
            return {"equity": 100_000.0, "buying_power": 100_000.0, "status": "DRY"}
        try:
            a = self.trading.get_account()
            return {"equity": float(a.equity), "buying_power": float(a.buying_power),
                    "status": str(a.status)}
        except Exception as e:
            log.error("get_account error: %s", e)
            return {"equity": 100_000.0, "buying_power": 0.0, "status": "ERROR"}

    def get_positions(self) -> List[dict]:
        if self.dry_mode:
            return []
        try:
            positions = self.trading.get_all_positions()
            return [
                {
                    "ticker":         p.symbol,
                    "qty":            float(p.qty),
                    "avg_entry":      float(p.avg_entry_price),
                    "current_price":  float(p.current_price),
                    "unrealized_pnl": float(p.unrealized_pl),
                    "strategy":       getattr(p, "client_order_id", ""),
                }
                for p in positions
            ]
        except Exception as e:
            log.error("get_positions error: %s", e)
            return []

    def get_open_orders(self) -> List[dict]:
        if self.dry_mode:
            return []
        try:
            from alpaca.trading.requests import GetOrdersRequest
            from alpaca.trading.enums import QueryOrderStatus
            req = GetOrdersRequest(status=QueryOrderStatus.OPEN)
            orders = self.trading.get_orders(req)
            return [{"id": str(o.id), "ticker": o.symbol, "side": str(o.side),
                     "qty": float(o.qty), "type": str(o.order_type),
                     "limit_price": float(o.limit_price) if o.limit_price else None}
                    for o in orders]
        except Exception as e:
            log.error("get_open_orders error: %s", e)
            return []

    # ── Order submission ──────────────────────────────────────

    def market_buy(self, ticker: str, shares: int, tag: str = "") -> Optional[str]:
        if self.dry_mode:
            oid = f"DRY_BUY_{ticker}_{now_str()}"
            log.info("DRY: BUY %d %s (tag=%s)", shares, ticker, tag)
            return oid
        try:
            from alpaca.trading.requests import MarketOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce
            req = MarketOrderRequest(
                symbol=ticker, qty=shares,
                side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
            )
            order = self.trading.submit_order(req)
            log.info("BUY %d %s | order_id=%s", shares, ticker, order.id)
            return str(order.id)
        except Exception as e:
            log.error("market_buy error for %s: %s", ticker, e)
            return None

    def market_sell(self, ticker: str, shares: int, tag: str = "") -> Optional[str]:
        if self.dry_mode:
            oid = f"DRY_SELL_{ticker}_{now_str()}"
            log.info("DRY: SELL %d %s (tag=%s)", shares, ticker, tag)
            return oid
        try:
            from alpaca.trading.requests import MarketOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce
            req = MarketOrderRequest(
                symbol=ticker, qty=shares,
                side=OrderSide.SELL, time_in_force=TimeInForce.DAY,
            )
            order = self.trading.submit_order(req)
            log.info("SELL %d %s | order_id=%s", shares, ticker, order.id)
            return str(order.id)
        except Exception as e:
            log.error("market_sell error for %s: %s", ticker, e)
            return None

    def limit_sell(self, ticker: str, shares: int, limit_price: float) -> Optional[str]:
        if self.dry_mode:
            log.info("DRY: LIMIT_SELL %d %s @ %.2f", shares, ticker, limit_price)
            return f"DRY_LSELL_{ticker}_{now_str()}"
        try:
            from alpaca.trading.requests import LimitOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce
            req = LimitOrderRequest(
                symbol=ticker, qty=shares, limit_price=round(limit_price, 2),
                side=OrderSide.SELL, time_in_force=TimeInForce.DAY,
            )
            order = self.trading.submit_order(req)
            log.info("LIMIT_SELL %d %s @ %.2f | order_id=%s", shares, ticker, limit_price, order.id)
            return str(order.id)
        except Exception as e:
            log.error("limit_sell error for %s: %s", ticker, e)
            return None

    def trailing_stop_sell(self, ticker: str, shares: int, trail_price: float) -> Optional[str]:
        if self.dry_mode:
            log.info("DRY: TRAIL_SELL %d %s trail=%.2f", shares, ticker, trail_price)
            return f"DRY_TRAIL_{ticker}_{now_str()}"
        try:
            from alpaca.trading.requests import TrailingStopOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce
            req = TrailingStopOrderRequest(
                symbol=ticker, qty=shares,
                side=OrderSide.SELL,
                trail_price=round(trail_price, 2),
                time_in_force=TimeInForce.DAY,
            )
            order = self.trading.submit_order(req)
            log.info("TRAIL_SELL %d %s trail=%.2f | order_id=%s", shares, ticker, trail_price, order.id)
            return str(order.id)
        except Exception as e:
            log.error("trailing_stop_sell error for %s: %s", ticker, e)
            return None

    def cancel_order(self, order_id: str):
        if self.dry_mode:
            return
        try:
            self.trading.cancel_order_by_id(order_id)
        except Exception as e:
            log.warning("cancel_order %s: %s", order_id, e)

    def close_position(self, ticker: str):
        if self.dry_mode:
            log.info("DRY: CLOSE_POSITION %s", ticker)
            return
        try:
            self.trading.close_position(ticker)
            log.info("CLOSED position: %s", ticker)
        except Exception as e:
            log.error("close_position error for %s: %s", ticker, e)

    def is_market_open(self) -> bool:
        if self.dry_mode:
            now = datetime.now(EST)
            return now.weekday() < 5 and 9 <= now.hour < 16
        try:
            clock = self.trading.get_clock()
            return bool(clock.is_open)
        except Exception as e:
            log.error("is_market_open error: %s", e)
            return False


# ═══════════════════════════════════════════════════════════════
# MANCINI STATE MACHINE
# ═══════════════════════════════════════════════════════════════

@dataclass
class ManciniState:
    state: str = "IDLE"          # IDLE, NEAR_LEVEL, FLUSH_DETECTED, ACCEPTANCE_WAIT, ENTERED, TIER1_HIT, EXITED
    prior_day_low: float = 0.0
    prior_day_high: float = 0.0
    flush_low: float = 0.0
    flush_size: float = 0.0
    flush_type: str = ""          # "shallow" or "deep"
    acceptance_candles_elapsed: int = 0
    acceptance_candles_needed: int = 0
    entry_price: Optional[float] = None
    stop_price: Optional[float] = None
    target1: Optional[float] = None
    shares_entered: int = 0
    tier1_order_id: Optional[str] = None
    runner_order_id: Optional[str] = None
    trades_today: int = 0
    last_candle_time: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


class ManciniEngine:
    """Implements Mancini 0DTE failed breakdown state machine."""

    def __init__(self, alpaca: AlpacaClient, cfg: dict):
        self.alpaca = alpaca
        self.cfg = cfg
        self.state = ManciniState()
        self.events: List[str] = []

    def log_event(self, msg: str):
        ts = datetime.now(EST).strftime("%H:%M:%S")
        entry = f"{ts} - {msg}"
        log.info("[MANCINI] %s", msg)
        self.events.append(entry)
        if len(self.events) > 50:
            self.events = self.events[-50:]

    def is_trading_allowed(self) -> bool:
        now = datetime.now(EST)
        h, m = now.hour, now.minute
        if now.weekday() >= 5:
            return False
        if h < MANCINI["primary_start_hour"]:
            return False
        if h >= MANCINI["entry_cutoff_hour"]:
            return False
        if MANCINI["chop_start_hour"] <= h < MANCINI["chop_end_hour"]:
            return False
        if self.state.trades_today >= self.cfg.get("max_daily_trades_mancini", 5):
            return False
        return True

    def is_force_exit_time(self) -> bool:
        now = datetime.now(EST)
        return (now.hour == MANCINI["force_exit_hour"] and
                now.minute >= MANCINI["force_exit_minute"])

    def run_cycle(self, spy_price: float):
        """Called every poll cycle with latest SPY price."""

        # Force exit check
        if self.is_force_exit_time():
            if self.state.state in ("ENTERED", "TIER1_HIT"):
                self.log_event(f"3:50 PM force close — SELL all SPY")
                self.alpaca.close_position("SPY")
                self.state.state = "EXITED"
            return

        if not self.is_trading_allowed():
            return

        s = self.state

        if s.state == "IDLE" or s.state == "EXITED":
            # Reset after exit, watch for new setup
            if s.state == "EXITED":
                s.state = "IDLE"
                s.flush_low = 0.0
                s.entry_price = None
                s.tier1_order_id = None
                s.runner_order_id = None
            # Check proximity to prior day low
            if s.prior_day_low > 0:
                distance = spy_price - s.prior_day_low
                if distance <= MANCINI["near_level_buffer"]:
                    s.state = "NEAR_LEVEL"
                    self.log_event(f"SPY near prior day low {s.prior_day_low:.2f} — distance ${distance:.2f}")

        elif s.state == "NEAR_LEVEL":
            flush = s.prior_day_low - spy_price
            if flush >= MANCINI["fb_min_flush"]:
                if flush > MANCINI["fb_max_flush"]:
                    self.log_event(f"Flush ${flush:.2f} exceeds max ${MANCINI['fb_max_flush']} — real breakdown, reset")
                    s.state = "IDLE"
                    return
                s.flush_low = spy_price
                s.flush_size = flush
                s.flush_type = "deep" if flush >= MANCINI["fb_flush_deep_threshold"] else "shallow"
                s.acceptance_candles_needed = (
                    MANCINI["acceptance_candles_deep"] if s.flush_type == "deep"
                    else MANCINI["acceptance_candles_shallow"]
                )
                s.acceptance_candles_elapsed = 0
                s.state = "FLUSH_DETECTED"
                self.log_event(
                    f"FLUSH DETECTED: SPY broke {s.prior_day_low:.2f} by ${flush:.2f} "
                    f"({s.flush_type}) — low={spy_price:.2f}"
                )

        elif s.state == "FLUSH_DETECTED":
            # Brief transition — immediately start acceptance wait
            s.state = "ACCEPTANCE_WAIT"

        elif s.state == "ACCEPTANCE_WAIT":
            # Count candles since flush (each poll ~30s, 10 polls ≈ 5 min candle)
            # We approximate: each 5-min candle = 10 poll cycles
            # For simplicity, track wall-clock minutes elapsed instead
            recovered = spy_price > s.prior_day_low

            # Form 3: Non-acceptance — price rips > $5 above flush low without pausing
            if spy_price > s.flush_low + MANCINI["danger_zone_buffer"]:
                self.log_event(
                    f"Form 3 detected: SPY ${spy_price - s.flush_low:.2f} above flush low "
                    f"— entering above danger zone"
                )
                self._execute_entry(spy_price)
                return

            if recovered:
                s.acceptance_candles_elapsed += 1
                if s.acceptance_candles_elapsed >= s.acceptance_candles_needed:
                    self.log_event(
                        f"Acceptance complete ({s.acceptance_candles_elapsed}/{s.acceptance_candles_needed} candles) "
                        f"— ENTERING"
                    )
                    self._execute_entry(spy_price)
            else:
                # Still below prior day low — if flush grows beyond max, abort
                current_flush = s.prior_day_low - spy_price
                if current_flush > MANCINI["fb_max_flush"]:
                    self.log_event(f"Flush extended to ${current_flush:.2f} — real breakdown, abort")
                    s.state = "IDLE"

        elif s.state == "ENTERED":
            # Monitor for stop hit (price fell back below stop)
            if spy_price <= s.stop_price:
                self.log_event(f"STOP HIT at ${spy_price:.2f} (stop={s.stop_price:.2f}) — exiting")
                self.alpaca.market_sell("SPY", s.shares_entered, tag="mancini_stop")
                if s.tier1_order_id:
                    self.alpaca.cancel_order(s.tier1_order_id)
                s.state = "EXITED"
                s.trades_today += 1

            # Check if tier1 limit order filled (polled via open orders)
            elif s.tier1_order_id:
                open_order_ids = [o["id"] for o in self.alpaca.get_open_orders()]
                if s.tier1_order_id not in open_order_ids:
                    # Tier 1 filled
                    runner_shares = max(1, int(s.shares_entered * (1 - MANCINI["tier1_exit_pct"])))
                    self.log_event(
                        f"Tier 1 target ${s.target1:.2f} HIT — "
                        f"sold {s.shares_entered - runner_shares} shares, "
                        f"running {runner_shares} shares with trail"
                    )
                    runner_oid = self.alpaca.trailing_stop_sell(
                        "SPY", runner_shares, MANCINI["stop_buffer"]
                    )
                    s.runner_order_id = runner_oid
                    s.tier1_order_id = None
                    s.state = "TIER1_HIT"

        elif s.state == "TIER1_HIT":
            # Monitor runner — check if trailing stop filled
            if s.runner_order_id:
                open_order_ids = [o["id"] for o in self.alpaca.get_open_orders()]
                if s.runner_order_id not in open_order_ids:
                    self.log_event("Runner trailing stop filled — trade complete")
                    s.state = "EXITED"
                    s.trades_today += 1

    def _execute_entry(self, price: float):
        s = self.state
        stop = s.flush_low - MANCINI["stop_buffer"]
        stop_dist = price - stop
        if stop_dist <= 0:
            self.log_event("Stop distance <= 0, skipping entry")
            s.state = "IDLE"
            return

        target1 = price + (stop_dist * MANCINI["tier1_target_mult"])
        rr = (target1 - price) / stop_dist
        if rr < MANCINI["min_reward_risk"]:
            self.log_event(f"R:R {rr:.2f} below minimum {MANCINI['min_reward_risk']} — skip")
            s.state = "IDLE"
            return

        shares = max(1, int(MANCINI["risk_per_trade"] / stop_dist))
        tier1_shares = max(1, int(shares * MANCINI["tier1_exit_pct"]))

        buy_id = self.alpaca.market_buy("SPY", shares, tag="mancini_fb")
        if not buy_id:
            self.log_event("Entry order failed")
            s.state = "IDLE"
            return

        t1_id = self.alpaca.limit_sell("SPY", tier1_shares, target1)

        s.entry_price = price
        s.stop_price  = round(stop, 2)
        s.target1     = round(target1, 2)
        s.shares_entered = shares
        s.tier1_order_id = t1_id
        s.state = "ENTERED"

        self.log_event(
            f"MANCINI BUY {shares} SPY @ ${price:.2f} | "
            f"stop=${stop:.2f} | T1=${target1:.2f} | R:R={rr:.1f}"
        )


# ═══════════════════════════════════════════════════════════════
# V5 ENTRY MODULE
# ═══════════════════════════════════════════════════════════════

class V5EntryEngine:
    """Auto-executes v5 setups when price enters the buy zone."""

    def __init__(self, alpaca: AlpacaClient, cfg: dict, universe: pd.DataFrame):
        self.alpaca = alpaca
        self.cfg    = cfg
        self.universe = universe
        self.watchlist = self._build_watchlist()
        self.events: List[str] = []

    def _build_watchlist(self) -> pd.DataFrame:
        df = self.universe.copy()
        min_score = self.cfg.get("v5_min_score", 40)
        n = self.cfg.get("v5_max_watchlist", 5)

        if "passes_gate" not in df.columns:
            df["passes_gate"] = True
        if "ticker" not in df.columns and "Ticker" in df.columns:
            df = df.rename(columns={"Ticker": "ticker"})

        candidates = df[df["passes_gate"] & (df["score_v5"] >= min_score)].copy()

        # Prioritize whale flow
        candidates["_whale"] = candidates["flow_conviction"].str.contains("Whale", na=False).astype(int)
        candidates = candidates.sort_values(["_whale", "score_v5"], ascending=[False, False])

        # Calculate buy zone
        pct_col = "sma20_pct" if "sma20_pct" in candidates.columns else "ext_20EMA"
        if pct_col in candidates.columns:
            candidates["ema20_price"]    = candidates["price"] / (1 + candidates[pct_col] / 100)
        else:
            candidates["ema20_price"]    = candidates["price"] * 0.91  # fallback: assume ~9% extended

        zone_pct = self.cfg.get("v5_buy_zone_pct", 3.0) / 100
        candidates["buy_zone_low"]  = candidates["ema20_price"]
        candidates["buy_zone_high"] = candidates["ema20_price"] * (1 + zone_pct)

        result = candidates.head(n).reset_index(drop=True)
        log.info("v5 watchlist: %s", list(result["ticker"]))
        return result

    def log_event(self, msg: str):
        ts = datetime.now(EST).strftime("%H:%M:%S")
        entry = f"{ts} - {msg}"
        log.info("[V5] %s", msg)
        self.events.append(entry)
        if len(self.events) > 50:
            self.events = self.events[-50:]

    def run_cycle(self, live_prices: Dict[str, float], portfolio_value: float,
                  held_tickers: set, daily_trades: int, daily_pnl: float) -> List[dict]:
        """Check watchlist for buy zone entries. Returns list of executed trade records."""
        executed = []

        if not self.cfg.get("v5_enabled", True):
            return executed

        # Circuit breaker
        if abs(daily_pnl) >= self.cfg.get("max_daily_loss", 1500):
            return executed

        for _, row in self.watchlist.iterrows():
            ticker = row["ticker"]
            if ticker in held_tickers:
                continue
            if ticker not in live_prices:
                continue

            live_price = live_prices[ticker]
            in_zone = row["buy_zone_low"] <= live_price <= row["buy_zone_high"]

            if in_zone:
                score = row["score_v5"]
                flow  = row.get("flow_conviction", "")
                atr   = row.get("atr", live_price * 0.02)

                max_pos_dollars  = portfolio_value * 0.05
                max_risk_dollars = portfolio_value * 0.02
                stop_dist        = atr * 2.0
                stop_price       = live_price - stop_dist

                if stop_dist <= 0:
                    continue

                shares_from_risk = max_risk_dollars / stop_dist
                shares_from_pos  = max_pos_dollars / live_price
                shares = int(min(shares_from_risk, shares_from_pos))

                # Score scaling
                if score >= 50:
                    scale = 1.0
                elif score >= 40:
                    scale = 0.75
                else:
                    scale = 0.5
                if "Whale" in str(flow):
                    scale = min(scale * 1.25, 1.0)

                shares = max(1, int(shares * scale))

                buy_id = self.alpaca.market_buy(ticker, shares, tag="v5_swing")
                if buy_id:
                    self.log_event(
                        f"v5 BUY {shares} {ticker} @ ${live_price:.2f} "
                        f"| score={score:.1f} | stop=${stop_price:.2f} | zone=[{row['buy_zone_low']:.2f}-{row['buy_zone_high']:.2f}]"
                    )
                    executed.append({
                        "ticker": ticker, "shares": shares,
                        "price": live_price, "stop": round(stop_price, 2),
                        "score": score, "strategy": "v5_swing",
                    })

        return executed


# ═══════════════════════════════════════════════════════════════
# V5 EXIT MODULE
# ═══════════════════════════════════════════════════════════════

class V5ExitEngine:
    """Checks open positions against v5 exit rules and auto-exits."""

    def __init__(self, alpaca: AlpacaClient, universe: pd.DataFrame):
        self.alpaca   = alpaca
        self.universe = universe
        self.events: List[str] = []

        # Build lookup for quick access to scoring data
        df = universe.copy()
        if "ticker" not in df.columns and "Ticker" in df.columns:
            df = df.rename(columns={"Ticker": "ticker"})
        self.lookup = df.set_index("ticker") if "ticker" in df.columns else pd.DataFrame()

    def log_event(self, msg: str):
        ts = datetime.now(EST).strftime("%H:%M:%S")
        entry = f"{ts} - {msg}"
        log.info("[V5-EXIT] %s", msg)
        self.events.append(entry)
        if len(self.events) > 50:
            self.events = self.events[-50:]

    def run_cycle(self, positions: List[dict]) -> List[dict]:
        """Evaluate each position against exit rules. Returns list of exit actions taken."""
        exits = []
        for pos in positions:
            ticker       = pos["ticker"]
            qty          = int(pos["qty"])
            entry_price  = pos["avg_entry"]
            current_price = pos["current_price"]
            pnl_pct      = ((current_price - entry_price) / entry_price) * 100 if entry_price else 0

            # Only manage v5 positions (skip SPY which belongs to Mancini)
            if ticker == "SPY":
                continue

            # P&L stop loss — universal
            if pnl_pct <= -7.0:
                self.log_event(f"STOP LOSS {ticker}: {pnl_pct:.1f}% — selling all {qty}")
                self.alpaca.market_sell(ticker, qty, tag="v5_stop")
                exits.append({"ticker": ticker, "action": "exit_all", "reason": f"Stop loss {pnl_pct:.1f}%"})
                continue

            if ticker not in self.lookup.index:
                continue

            row = self.lookup.loc[ticker]
            score      = float(row.get("score_v5", 50))
            passes_gate = bool(row.get("passes_gate", True))
            pct_col    = "sma20_pct" if "sma20_pct" in row.index else "ext_20EMA"
            ext_20     = float(row.get(pct_col, 0) or 0)

            # Gate failure → full exit
            if not passes_gate:
                self.log_event(f"GATE FAIL {ticker} — selling all {qty}")
                self.alpaca.market_sell(ticker, qty, tag="v5_gate_exit")
                exits.append({"ticker": ticker, "action": "exit_all", "reason": "Failed trend gate"})
                continue

            # Score below hold threshold → trim
            if score < 25:
                trim = int(qty * 0.5)
                if trim >= 1:
                    self.log_event(f"SCORE TRIM {ticker}: score={score:.1f} < 25 — selling {trim}")
                    self.alpaca.market_sell(ticker, trim, tag="v5_score_trim")
                    exits.append({"ticker": ticker, "action": "trim", "reason": f"Score {score:.1f} < 25"})
                continue

            # Extension tier 2 → trim 50%
            if ext_20 >= 12:
                trim = int(qty * 0.50)
                if trim >= 1:
                    self.log_event(f"EXT TRIM-50 {ticker}: {ext_20:.1f}% above 20EMA — selling {trim}")
                    self.alpaca.market_sell(ticker, trim, tag="v5_ext_trim")
                    exits.append({"ticker": ticker, "action": "trim_50", "reason": f"Extended {ext_20:.1f}%"})
                continue

            # Extension tier 1 → trim 25%
            if ext_20 >= 8:
                trim = int(qty * 0.25)
                if trim >= 1:
                    self.log_event(f"EXT TRIM-25 {ticker}: {ext_20:.1f}% above 20EMA — selling {trim}")
                    self.alpaca.market_sell(ticker, trim, tag="v5_ext_trim")
                    exits.append({"ticker": ticker, "action": "trim_25", "reason": f"Extended {ext_20:.1f}%"})

        return exits


# ═══════════════════════════════════════════════════════════════
# MONITOR LOG
# ═══════════════════════════════════════════════════════════════

def write_log(path: Path, mancini: ManciniEngine, v5_entry: V5EntryEngine,
              v5_exit: V5ExitEngine, watchlist_status: List[dict],
              daily_pnl: float, daily_trades: int, circuit_breaker: bool):
    data = {
        "last_updated": datetime.now(EST).isoformat(),
        "circuit_breaker": circuit_breaker,
        "daily_pnl": round(daily_pnl, 2),
        "daily_trades": daily_trades,
        "mancini": mancini.state.to_dict(),
        "v5_watchlist": watchlist_status,
        "recent_events": (
            mancini.events[-10:] + v5_entry.events[-5:] + v5_exit.events[-5:]
        )[-20:],
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def now_str() -> str:
    return datetime.now(EST).strftime("%H%M%S")


def load_universe(cfg: dict) -> pd.DataFrame:
    csv_name = cfg.get("quickview_csv", "Quickview_v5_Feb17.csv")
    csv_path = BASE_DIR / csv_name
    if not csv_path.exists():
        # Try to find latest Quickview file
        files = sorted(BASE_DIR.glob("Quickview*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            csv_path = files[0]
            log.info("Auto-detected CSV: %s", csv_path.name)
        else:
            raise FileNotFoundError(f"No Quickview CSV found in {BASE_DIR}")

    df = pd.read_csv(csv_path)
    # Normalize column names
    df = df.rename(columns={
        "Ticker": "ticker", "Sector": "sector",
        "rel_vol": "rel_volume", "ext_20EMA": "sma20_pct", "ext_50EMA": "sma50_pct",
    })
    if "passes_gate" not in df.columns:
        df["passes_gate"] = True
    log.info("Loaded %d rows from %s", len(df), csv_path.name)
    return df


# ═══════════════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════════════

def main():
    log.info("=" * 60)
    log.info("Autotrader v5 Monitor — Starting")
    log.info("=" * 60)

    cfg = load_config()
    log_path = BASE_DIR / "monitor_log.json"
    interval = cfg.get("poll_interval_seconds", 30)

    # Connect to Alpaca
    alpaca = AlpacaClient(
        api_key    = cfg["alpaca_api_key"],
        api_secret = cfg["alpaca_api_secret"],
        paper      = cfg.get("paper_mode", True),
    )

    # Load scored universe
    universe = load_universe(cfg)

    # Initialize engines
    mancini_engine = ManciniEngine(alpaca, cfg)
    v5_entry_engine = V5EntryEngine(alpaca, cfg, universe)
    v5_exit_engine  = V5ExitEngine(alpaca, universe)

    # Fetch prior day SPY levels
    spy_levels = alpaca.get_prior_day_levels("SPY")
    if spy_levels:
        mancini_engine.state.prior_day_low  = spy_levels.get("low",  0.0)
        mancini_engine.state.prior_day_high = spy_levels.get("high", 0.0)
        log.info("Prior day SPY — Low: $%.2f | High: $%.2f",
                 mancini_engine.state.prior_day_low,
                 mancini_engine.state.prior_day_high)
    else:
        log.warning("Could not fetch prior day SPY levels")

    # Print watchlist
    wl = v5_entry_engine.watchlist
    log.info("v5 Watchlist (%d setups):", len(wl))
    for _, row in wl.iterrows():
        log.info("  %-6s score=%.1f zone=[%.2f–%.2f]",
                 row["ticker"], row["score_v5"],
                 row["buy_zone_low"], row["buy_zone_high"])

    # Daily tracking
    daily_pnl    = 0.0
    daily_trades = 0

    log.info("Entering main loop (poll every %ds) — Ctrl+C to stop", interval)
    log.info("Mancini: %s | v5 Entries: %s",
             "ON" if cfg.get("mancini_enabled", True) else "OFF",
             "ON" if cfg.get("v5_enabled", True) else "OFF")

    while True:
        try:
            now = datetime.now(EST)

            # ── Circuit breaker ───────────────────────────────
            circuit_breaker = abs(daily_pnl) >= cfg.get("max_daily_loss", 1500)
            if circuit_breaker:
                log.warning("CIRCUIT BREAKER ACTIVE — daily P&L $%.0f", daily_pnl)

            # ── Get current account + positions ───────────────
            account   = alpaca.get_account()
            positions = alpaca.get_positions()
            held_tickers = {p["ticker"] for p in positions}
            portfolio_value = account.get("equity", 100_000.0)

            # ── Get live prices ───────────────────────────────
            watchlist_tickers = list(v5_entry_engine.watchlist["ticker"])
            all_tickers = (["SPY"] + watchlist_tickers) if cfg.get("mancini_enabled") else watchlist_tickers
            live_prices = alpaca.get_latest_prices(all_tickers)
            spy_price = live_prices.get("SPY", 0.0)

            # ── Mancini module ────────────────────────────────
            if cfg.get("mancini_enabled", True) and not circuit_breaker and spy_price > 0:
                mancini_engine.run_cycle(spy_price)

            # ── v5 Exit module ────────────────────────────────
            if not circuit_breaker and positions:
                exit_actions = v5_exit_engine.run_cycle(positions)
                daily_trades += len(exit_actions)

            # ── v5 Entry module ───────────────────────────────
            if not circuit_breaker and alpaca.is_market_open():
                entries = v5_entry_engine.run_cycle(
                    live_prices=live_prices,
                    portfolio_value=portfolio_value,
                    held_tickers=held_tickers,
                    daily_trades=daily_trades,
                    daily_pnl=daily_pnl,
                )
                daily_trades += len(entries)

            # ── Build watchlist status for log ────────────────
            watchlist_status = []
            for _, row in v5_entry_engine.watchlist.iterrows():
                ticker = row["ticker"]
                lp = live_prices.get(ticker, None)
                if lp is not None:
                    in_zone = row["buy_zone_low"] <= lp <= row["buy_zone_high"]
                    status = "🟢 IN ZONE" if in_zone else (
                        "Above zone" if lp > row["buy_zone_high"] else "Below zone"
                    )
                else:
                    status = "No price"
                    lp = 0.0
                watchlist_status.append({
                    "ticker":        ticker,
                    "score":         round(row["score_v5"], 1),
                    "flow":          row.get("flow_conviction", ""),
                    "buy_zone_low":  round(row["buy_zone_low"], 2),
                    "buy_zone_high": round(row["buy_zone_high"], 2),
                    "live_price":    round(lp, 2),
                    "status":        status,
                })

            # ── Write log ─────────────────────────────────────
            write_log(
                log_path, mancini_engine, v5_entry_engine, v5_exit_engine,
                watchlist_status, daily_pnl, daily_trades, circuit_breaker
            )

            # ── Reset at midnight ─────────────────────────────
            if now.hour == 0 and now.minute == 0:
                daily_pnl    = 0.0
                daily_trades = 0
                mancini_engine.state.trades_today = 0
                # Refresh prior day levels
                spy_levels = alpaca.get_prior_day_levels("SPY")
                if spy_levels:
                    mancini_engine.state.prior_day_low  = spy_levels["low"]
                    mancini_engine.state.prior_day_high = spy_levels["high"]
                    log.info("Daily reset — new SPY levels: Low=%.2f High=%.2f",
                             spy_levels["low"], spy_levels["high"])

        except KeyboardInterrupt:
            log.info("Shutting down monitor")
            break
        except Exception as e:
            log.error("Poll cycle error: %s", e, exc_info=True)

        time.sleep(interval)


if __name__ == "__main__":
    main()
