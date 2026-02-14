"""
risk.py — Risk Management Engine

The whole point of this bot: replace emotional decision-making with rules.
This module enforces every guardrail before a trade gets submitted.

"The route to get there is designed to scare you out."
— This module doesn't get scared.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .config import RiskConfig
from .broker import AccountInfo, Position
from .signals import TradeSignal, SignalAction


@dataclass
class RiskCheckResult:
    """Result of a risk check on a proposed signal."""
    approved: bool
    signal: TradeSignal
    reasons: List[str]          # Why approved or rejected
    adjustments: List[str]      # Any modifications made (size reduction, etc.)
    original_qty: int = 0
    adjusted_qty: int = 0

    def __str__(self):
        status = "✅ APPROVED" if self.approved else "❌ REJECTED"
        lines = [f"{status}: {self.signal.action.value} {self.signal.qty} {self.signal.ticker}"]
        for r in self.reasons:
            lines.append(f"  {'✓' if self.approved else '✗'} {r}")
        for a in self.adjustments:
            lines.append(f"  ⚠ Adjusted: {a}")
        return "\n".join(lines)


class RiskManager:
    """
    Pre-trade risk checks and portfolio-level exposure management.

    Every signal passes through check_signal() before execution.
    The risk manager can:
    - Approve the signal as-is
    - Approve with reduced size
    - Reject entirely with reasons
    """

    def __init__(self, config: RiskConfig):
        self.config = config
        self._daily_pnl_cache: float = 0.0
        self._halted: bool = False
        self._halt_reason: str = ""

    # ----- MAIN CHECK -----

    def check_signal(
        self,
        signal: TradeSignal,
        account: AccountInfo,
        positions: List[Position],
    ) -> RiskCheckResult:
        """
        Run all risk checks on a proposed trade signal.
        Returns RiskCheckResult with approval/rejection and reasons.
        """
        reasons = []
        adjustments = []
        original_qty = signal.qty

        # 1. Circuit breaker check
        if self._halted:
            return RiskCheckResult(
                approved=False, signal=signal,
                reasons=[f"Trading halted: {self._halt_reason}"],
                adjustments=[], original_qty=original_qty, adjusted_qty=0,
            )

        # 2. Daily P&L circuit breaker
        halt_check = self._check_daily_pnl(account)
        if halt_check:
            return RiskCheckResult(
                approved=False, signal=signal,
                reasons=[halt_check], adjustments=[],
                original_qty=original_qty, adjusted_qty=0,
            )

        # 3. Account blocked check
        if account.is_trading_blocked:
            return RiskCheckResult(
                approved=False, signal=signal,
                reasons=["Account trading is blocked by broker"],
                adjustments=[], original_qty=original_qty, adjusted_qty=0,
            )

        # 4. Max open positions check
        if len(positions) >= self.config.max_open_positions:
            if signal.action == SignalAction.BUY:
                return RiskCheckResult(
                    approved=False, signal=signal,
                    reasons=[f"Max positions reached ({len(positions)}/{self.config.max_open_positions})"],
                    adjustments=[], original_qty=original_qty, adjusted_qty=0,
                )

        # 5. Duplicate position check
        existing = self._find_position(signal.ticker, positions)
        if existing and signal.action == SignalAction.BUY:
            # Allow SCALE_IN but not duplicate BUY
            if signal.action != SignalAction.SCALE_IN:
                reasons.append(f"Already holding {existing.qty} shares of {signal.ticker}")
                # Convert to scale-in if position is small enough
                current_exposure = existing.market_value / account.equity * 100
                if current_exposure < self.config.max_position_pct * 0.6:
                    signal.action = SignalAction.SCALE_IN
                    adjustments.append(f"Converted to SCALE_IN (current exposure: {current_exposure:.1f}%)")
                else:
                    return RiskCheckResult(
                        approved=False, signal=signal,
                        reasons=reasons + [f"Position already at {current_exposure:.1f}% — max is {self.config.max_position_pct}%"],
                        adjustments=[], original_qty=original_qty, adjusted_qty=0,
                    )

        # 6. Sector exposure check
        sector_check = self._check_sector_exposure(signal, account, positions)
        if sector_check:
            adjustments.append(sector_check)

        # 7. Position size validation
        size_check = self._validate_position_size(signal, account)
        if size_check:
            adjustments.append(size_check)

        # 8. Stop loss mandatory check
        if self.config.mandatory_stop_loss and signal.stop_loss_price <= 0:
            if signal.action in (SignalAction.BUY, SignalAction.SCALE_IN):
                # Auto-calculate stop if missing
                signal.stop_loss_price = round(
                    signal.entry_price * (1 - self.config.default_stop_pct / 100), 2
                )
                adjustments.append(
                    f"Auto-set stop loss at ${signal.stop_loss_price:.2f} "
                    f"({self.config.default_stop_pct}% below entry)"
                )

        # 9. Buying power check
        required_cash = signal.qty * signal.entry_price
        if required_cash > account.buying_power:
            # Reduce size to fit buying power
            max_shares = int(account.buying_power * 0.95 / signal.entry_price)  # 95% to leave buffer
            if max_shares > 0:
                signal.qty = max_shares
                signal.position_size_usd = max_shares * signal.entry_price
                adjustments.append(
                    f"Reduced to {max_shares} shares to fit buying power "
                    f"(${account.buying_power:,.0f} available)"
                )
            else:
                return RiskCheckResult(
                    approved=False, signal=signal,
                    reasons=["Insufficient buying power"],
                    adjustments=[], original_qty=original_qty, adjusted_qty=0,
                )

        # 10. Minimum size check
        if signal.position_size_usd < self.config.min_position_usd:
            return RiskCheckResult(
                approved=False, signal=signal,
                reasons=[f"Position too small (${signal.position_size_usd:,.0f} < ${self.config.min_position_usd:,.0f} min)"],
                adjustments=[], original_qty=original_qty, adjusted_qty=0,
            )

        # 11. Time window check
        time_check = self._check_time_window()
        if time_check:
            return RiskCheckResult(
                approved=False, signal=signal,
                reasons=[time_check], adjustments=[],
                original_qty=original_qty, adjusted_qty=0,
            )

        # All checks passed
        reasons.append("All risk checks passed")
        return RiskCheckResult(
            approved=True, signal=signal,
            reasons=reasons, adjustments=adjustments,
            original_qty=original_qty, adjusted_qty=signal.qty,
        )

    # ----- CIRCUIT BREAKERS -----

    def update_daily_pnl(self, account: AccountInfo):
        """Update daily P&L tracking. Call this on each check cycle."""
        self._daily_pnl_cache = account.daily_pnl_pct

        if account.daily_pnl_pct <= self.config.daily_loss_halt_pct:
            self._halted = True
            self._halt_reason = (
                f"Daily loss circuit breaker triggered: "
                f"{account.daily_pnl_pct:.2f}% (limit: {self.config.daily_loss_halt_pct}%)"
            )
            print(f"🚨 {self._halt_reason}")

    def reset_halt(self):
        """Manually reset the halt state (new trading day)."""
        self._halted = False
        self._halt_reason = ""

    @property
    def is_halted(self) -> bool:
        return self._halted

    # ----- INTERNAL CHECKS -----

    def _check_daily_pnl(self, account: AccountInfo) -> Optional[str]:
        """Check daily P&L against circuit breakers."""
        if account.daily_pnl_pct <= self.config.daily_loss_halt_pct:
            self._halted = True
            self._halt_reason = f"Daily loss: {account.daily_pnl_pct:.2f}%"
            return f"Daily loss halt: {account.daily_pnl_pct:.2f}% exceeds {self.config.daily_loss_halt_pct}% limit"
        return None

    def _check_sector_exposure(
        self, signal: TradeSignal, account: AccountInfo, positions: List[Position]
    ) -> Optional[str]:
        """Check sector concentration limits."""
        if not signal.sector:
            return None

        # Count positions in same sector (rough — we'd need sector mapping)
        # For now, count by ticker prefix as a proxy
        same_sector_value = sum(
            p.market_value for p in positions
            # In production, this would check actual sector tags
        )
        # Simplified: just check position count in same sector
        return None

    def _validate_position_size(self, signal: TradeSignal, account: AccountInfo) -> Optional[str]:
        """Validate and adjust position size against limits."""
        max_usd = account.equity * (self.config.max_position_pct / 100)

        if signal.position_size_usd > max_usd:
            old_size = signal.position_size_usd
            signal.position_size_usd = max_usd
            if signal.entry_price > 0:
                signal.qty = int(max_usd / signal.entry_price)
            return (
                f"Size reduced from ${old_size:,.0f} to ${max_usd:,.0f} "
                f"(max {self.config.max_position_pct}% of equity)"
            )

        if signal.position_size_usd > self.config.max_position_usd:
            signal.position_size_usd = self.config.max_position_usd
            if signal.entry_price > 0:
                signal.qty = int(self.config.max_position_usd / signal.entry_price)
            return f"Size capped at ${self.config.max_position_usd:,.0f} hard limit"

        return None

    def _check_time_window(self) -> Optional[str]:
        """Check if we're in the allowed trading window."""
        now = datetime.now()
        hour, minute = now.hour, now.minute
        current_minutes = hour * 60 + minute

        if self.config.no_entry_first_15min:
            # Market opens at 9:30 ET = 570 minutes
            if current_minutes < 585:  # Before 9:45
                return "Too early — no entries in first 15 min (before 9:45 AM ET)"

        if self.config.no_entry_last_30min:
            # Market closes at 16:00 ET = 960 minutes
            if current_minutes > 930:  # After 3:30 PM
                return "Too late — no entries in last 30 min (after 3:30 PM ET)"

        return None

    def _find_position(self, ticker: str, positions: List[Position]) -> Optional[Position]:
        """Find existing position for a ticker."""
        for p in positions:
            if p.ticker.upper() == ticker.upper():
                return p
        return None

    # ----- PORTFOLIO HEALTH -----

    def portfolio_health_check(
        self, account: AccountInfo, positions: List[Position]
    ) -> Dict[str, any]:
        """
        Run a portfolio-level health assessment.
        Returns dict with health metrics and any warnings.
        """
        warnings = []

        # Concentration check
        if positions:
            total_value = sum(p.market_value for p in positions)
            for p in positions:
                pct = (p.market_value / account.equity * 100) if account.equity > 0 else 0
                if pct > self.config.max_position_pct * 1.2:  # 20% buffer before warning
                    warnings.append(
                        f"⚠ {p.ticker} is {pct:.1f}% of equity "
                        f"(limit: {self.config.max_position_pct}%)"
                    )

        # Unrealized loss check
        big_losers = [p for p in positions if p.unrealized_pnl_pct < -10]
        for p in big_losers:
            warnings.append(
                f"🔴 {p.ticker} down {p.unrealized_pnl_pct:.1f}% — review stop loss"
            )

        # Daily P&L warning
        if account.daily_pnl_pct < self.config.daily_loss_reduce_pct:
            warnings.append(
                f"⚠ Daily P&L at {account.daily_pnl_pct:.2f}% — "
                f"approaching halt at {self.config.daily_loss_halt_pct}%"
            )

        return {
            "equity": account.equity,
            "daily_pnl_pct": account.daily_pnl_pct,
            "open_positions": len(positions),
            "max_positions": self.config.max_open_positions,
            "utilization_pct": (len(positions) / self.config.max_open_positions * 100),
            "halted": self._halted,
            "warnings": warnings,
            "healthy": len(warnings) == 0 and not self._halted,
        }


# ---------------------------------------------------------------------------
# TEST
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from .config import RiskConfig
    from .signals import TradeSignal, SignalAction, StructureType

    risk_mgr = RiskManager(RiskConfig())

    # Mock account
    account = AccountInfo(
        equity=100000, cash=50000, buying_power=50000,
        portfolio_value=100000, daily_pnl=-500, daily_pnl_pct=-0.5,
        open_position_count=3, is_trading_blocked=False,
        is_pattern_day_trader=False,
    )

    # Mock positions
    positions = [
        Position("XLE", 100, "long", 52.0, 54.0, 5400, 200, 3.85, 5200),
        Position("GLD", 20, "long", 440.0, 450.0, 9000, 200, 2.27, 8800),
        Position("NVDA", 30, "long", 180.0, 187.0, 5610, 210, 3.89, 5400),
    ]

    # Test signal
    signal = TradeSignal(
        ticker="XLB",
        action=SignalAction.BUY,
        entry_price=52.00,
        entry_zone_low=51.50,
        entry_zone_high=52.50,
        stop_loss_price=49.50,
        target_1_price=55.00,
        target_2_price=58.00,
        position_size_pct=3.0,
        bullish_score=72.0,
        structure=StructureType.BREAKOUT,
        sector="Materials",
    )
    signal.calculate_sizing(account.equity, 5.0, 1.0)

    result = risk_mgr.check_signal(signal, account, positions)
    print(result)

    # Portfolio health
    health = risk_mgr.portfolio_health_check(account, positions)
    print(f"\nPortfolio Health: {'✅ Healthy' if health['healthy'] else '⚠ Issues'}")
    for w in health["warnings"]:
        print(f"  {w}")
