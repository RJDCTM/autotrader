"""
executor.py — Main Execution Engine

The brain of the bot. Runs in a loop:
1. Check account & portfolio health
2. Monitor existing positions (stops, targets, time exits)
3. Poll for new signals
4. Run risk checks
5. Execute approved trades
6. Log everything

"The bot doesn't have fear, doesn't have ego, doesn't hold losers
hoping they'll come back, doesn't cut winners short because it's nervous.
It just runs the rules."
"""

from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .config import AutoTraderConfig, load_config
from .broker import AlpacaBroker, AccountInfo, Position, OrderResult
from .signals import TradeSignal, SignalAction, pipeline_row_to_signal
from .risk import RiskManager, RiskCheckResult


class TradeLog:
    """Simple CSV trade logger."""

    def __init__(self, log_dir: str = "logs"):
        os.makedirs(log_dir, exist_ok=True)
        self.trade_file = os.path.join(log_dir, "trades.csv")
        self.signal_file = os.path.join(log_dir, "signals.csv")
        self._init_files()

    def _init_files(self):
        if not os.path.exists(self.trade_file):
            with open(self.trade_file, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp", "ticker", "action", "qty", "price",
                    "order_type", "order_id", "status", "signal_score",
                    "structure", "stop_loss", "target_1", "notes",
                ])

        if not os.path.exists(self.signal_file):
            with open(self.signal_file, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp", "ticker", "action", "score", "structure",
                    "entry_price", "stop_loss", "target_1", "risk_reward",
                    "approved", "rejection_reason", "qty", "size_usd",
                ])

    def log_trade(self, signal: TradeSignal, order: OrderResult, notes: str = ""):
        with open(self.trade_file, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().isoformat(),
                signal.ticker,
                signal.action.value,
                order.filled_qty or order.qty,
                order.filled_price or signal.entry_price,
                order.order_type,
                order.order_id,
                order.status,
                signal.bullish_score,
                signal.structure.value,
                signal.stop_loss_price,
                signal.target_1_price,
                notes,
            ])

    def log_signal(self, signal: TradeSignal, result: RiskCheckResult):
        with open(self.signal_file, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().isoformat(),
                signal.ticker,
                signal.action.value,
                signal.bullish_score,
                signal.structure.value,
                signal.entry_price,
                signal.stop_loss_price,
                signal.target_1_price,
                signal.risk_reward_ratio,
                result.approved,
                "; ".join(result.reasons) if not result.approved else "",
                signal.qty,
                signal.position_size_usd,
            ])


class Executor:
    """
    Main execution engine. Call run() to start the trading loop.

    Lifecycle:
    1. Initialize with config, broker, risk manager
    2. Load signals (from pipeline output or manual queue)
    3. Run continuous loop during market hours
    4. Shut down cleanly at EOD
    """

    def __init__(self, config: Optional[AutoTraderConfig] = None):
        self.config = config or load_config()
        self.broker = AlpacaBroker(self.config.broker)
        self.risk_mgr = RiskManager(self.config.risk)
        self.logger = TradeLog(self.config.logging.log_dir)

        # Signal queue
        self._pending_signals: List[TradeSignal] = []
        self._active_trades: Dict[str, TradeSignal] = {}  # ticker -> signal
        self._order_tracker: Dict[str, str] = {}           # order_id -> ticker

        print("[Executor] Initialized")
        print(f"  Mode:     {'PAPER' if self.config.broker.is_paper else '🔴 LIVE'}")
        print(f"  Dry run:  {self.config.dry_run}")

    # ----- SIGNAL LOADING -----

    def load_signals_from_csv(self, filepath: str) -> int:
        """
        Load signals from the pipeline's Quickview CSV or Execution List.
        Returns count of signals loaded.
        """
        import pandas as pd
        df = pd.read_csv(filepath)
        count = 0

        account = self.broker.get_account()

        for _, row in df.iterrows():
            signal = pipeline_row_to_signal(row.to_dict(), account.equity)
            if signal and signal.is_valid:
                self._pending_signals.append(signal)
                count += 1

        # Sort by priority (lower = higher priority)
        self._pending_signals.sort(key=lambda s: (s.priority, -s.bullish_score))
        print(f"[Executor] Loaded {count} valid signals from {filepath}")
        return count

    def add_manual_signal(self, signal: TradeSignal) -> bool:
        """Add a manually created signal to the queue."""
        errors = signal.validate()
        if errors:
            print(f"[Executor] Invalid signal: {errors}")
            return False
        self._pending_signals.append(signal)
        print(f"[Executor] Added manual signal: {signal}")
        return True

    # ----- MAIN LOOP -----

    def run(self):
        """
        Main execution loop. Runs until market close or manual stop.
        """
        print("\n" + "=" * 60)
        print("RD AutoTrader — Starting Execution Loop")
        print("=" * 60)

        while True:
            try:
                # Check market status
                if not self.broker.is_market_open():
                    clock = self.broker.get_clock()
                    print(f"[{self._ts()}] Market closed. Next open: {clock['next_open']}")
                    time.sleep(60)
                    continue

                # --- CYCLE START ---
                account = self.broker.get_account()
                positions = self.broker.get_positions()

                # Update risk manager
                self.risk_mgr.update_daily_pnl(account)

                if self.config.logging.verbose:
                    print(f"\n[{self._ts()}] ── Cycle ──")
                    print(f"  {account}")

                # 1. Monitor existing positions
                self._monitor_positions(account, positions)

                # 2. Process pending signals
                if not self.risk_mgr.is_halted and self._pending_signals:
                    self._process_signals(account, positions)

                # 3. Check for stale orders
                self._check_stale_orders()

                # --- CYCLE END ---
                time.sleep(self.config.check_interval_seconds)

            except KeyboardInterrupt:
                print(f"\n[{self._ts()}] Shutting down gracefully...")
                self._shutdown()
                break
            except Exception as e:
                print(f"[{self._ts()}] ERROR: {e}")
                time.sleep(10)  # Back off on errors

    def run_once(self):
        """
        Run a single cycle — useful for testing or cron-based execution.
        """
        account = self.broker.get_account()
        positions = self.broker.get_positions()

        self.risk_mgr.update_daily_pnl(account)

        print(f"\n[{self._ts()}] ── Single Cycle ──")
        print(f"  {account}")

        # Portfolio health
        health = self.risk_mgr.portfolio_health_check(account, positions)
        print(f"  Health: {'✅' if health['healthy'] else '⚠'} | "
              f"Positions: {health['open_positions']}/{health['max_positions']} | "
              f"Daily P&L: {health['daily_pnl_pct']:+.2f}%")
        for w in health["warnings"]:
            print(f"  {w}")

        # Show positions
        if positions:
            print(f"\n  Open Positions:")
            for p in sorted(positions, key=lambda x: x.unrealized_pnl_pct, reverse=True):
                print(f"    {p}")

        # Process signals
        if self._pending_signals:
            print(f"\n  Pending Signals: {len(self._pending_signals)}")
            self._process_signals(account, positions)
        else:
            print(f"\n  No pending signals.")

    # ----- POSITION MONITORING -----

    def _monitor_positions(self, account: AccountInfo, positions: List[Position]):
        """
        Check all open positions for exit conditions:
        - Hit target prices
        - Time-based exits
        - Trailing stop triggers
        """
        for pos in positions:
            if pos.ticker not in self._active_trades:
                continue

            signal = self._active_trades[pos.ticker]

            # Check time-based exit
            if signal.generated_at:
                try:
                    entry_time = datetime.fromisoformat(signal.generated_at)
                    days_held = (datetime.now() - entry_time).days
                    if days_held >= signal.max_hold_days:
                        print(f"  ⏰ {pos.ticker}: Max hold ({signal.max_hold_days}d) reached — closing")
                        if not self.config.dry_run:
                            result = self.broker.close_position(pos.ticker)
                            self.logger.log_trade(signal, result, "Time exit")
                except (ValueError, TypeError):
                    pass

    # ----- SIGNAL PROCESSING -----

    def _process_signals(self, account: AccountInfo, positions: List[Position]):
        """Process pending signals through risk checks and execute approved ones."""
        processed = []

        for signal in self._pending_signals:
            # Risk check
            result = self.risk_mgr.check_signal(signal, account, positions)
            self.logger.log_signal(signal, result)

            if result.approved:
                print(f"\n  ✅ {signal.ticker}: APPROVED")
                print(f"     {signal}")
                for adj in result.adjustments:
                    print(f"     ⚠ {adj}")

                # Execute
                if not self.config.dry_run:
                    order = self._execute_signal(signal)
                    if order and not order.error:
                        self._active_trades[signal.ticker] = signal
                        self._order_tracker[order.order_id] = signal.ticker
                        self.logger.log_trade(signal, order)
                        print(f"     📤 Order submitted: {order}")
                    else:
                        print(f"     ❌ Order failed: {order.error if order else 'Unknown'}")
                else:
                    print(f"     🏜 DRY RUN — order not submitted")

            else:
                if self.config.logging.verbose:
                    print(f"\n  ❌ {signal.ticker}: REJECTED")
                    for r in result.reasons:
                        print(f"     {r}")

            processed.append(signal)

            # Re-check account after each trade (buying power changes)
            if result.approved and not self.config.dry_run:
                account = self.broker.get_account()
                positions = self.broker.get_positions()

        # Remove processed signals
        for s in processed:
            if s in self._pending_signals:
                self._pending_signals.remove(s)

    def _execute_signal(self, signal: TradeSignal) -> Optional[OrderResult]:
        """Execute a single approved signal."""
        if signal.action in (SignalAction.BUY, SignalAction.SCALE_IN):
            if self.config.strategy.use_limit_orders:
                # Use bracket order: limit entry + stop + target
                if signal.target_1_price > 0 and signal.stop_loss_price > 0:
                    return self.broker.submit_bracket_buy(
                        ticker=signal.ticker,
                        qty=signal.qty,
                        limit_price=signal.entry_price,
                        stop_loss_price=signal.stop_loss_price,
                        take_profit_price=signal.target_1_price,
                    )
                else:
                    return self.broker.submit_limit_buy(
                        ticker=signal.ticker,
                        qty=signal.qty,
                        limit_price=signal.entry_price,
                    )
            else:
                return self.broker.submit_market_buy(
                    ticker=signal.ticker,
                    qty=signal.qty,
                )

        elif signal.action in (SignalAction.SELL, SignalAction.CLOSE):
            return self.broker.close_position(signal.ticker)

        return None

    # ----- ORDER MANAGEMENT -----

    def _check_stale_orders(self):
        """Cancel unfilled orders that have exceeded timeout."""
        open_orders = self.broker.get_open_orders()
        for order in open_orders:
            if order.submitted_at:
                try:
                    submitted = datetime.fromisoformat(
                        order.submitted_at.replace("Z", "+00:00")
                    )
                    age_minutes = (datetime.now(submitted.tzinfo) - submitted).total_seconds() / 60
                    timeout = self.config.strategy.entry_timeout_minutes

                    if age_minutes > timeout:
                        print(f"  ⏰ Cancelling stale order: {order.ticker} "
                              f"({age_minutes:.0f}min old, timeout: {timeout}min)")
                        self.broker.cancel_order(order.order_id)
                except (ValueError, TypeError):
                    pass

    # ----- SHUTDOWN -----

    def _shutdown(self):
        """Clean shutdown — cancel open orders, log final state."""
        print("\n[Executor] Shutdown sequence...")

        # Cancel all open orders
        cancelled = self.broker.cancel_all_orders()
        print(f"  Cancelled {cancelled} open orders")

        # Final account snapshot
        account = self.broker.get_account()
        print(f"  Final equity: ${account.equity:,.2f}")
        print(f"  Daily P&L:    ${account.daily_pnl:+,.2f} ({account.daily_pnl_pct:+.2f}%)")

        # Positions still open
        positions = self.broker.get_positions()
        if positions:
            print(f"  Open positions ({len(positions)}):")
            for p in positions:
                print(f"    {p}")

        print("[Executor] Shutdown complete.")

    @staticmethod
    def _ts() -> str:
        return datetime.now().strftime("%H:%M:%S")


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    executor = Executor()
    executor.run_once()
