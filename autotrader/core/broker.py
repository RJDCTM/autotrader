"""
broker.py — Alpaca API connection wrapper

Handles all communication with Alpaca: account info, order submission,
position management, market data. Designed as a clean abstraction so
the execution engine never touches raw API calls.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import alpaca_trade_api as tradeapi
from alpaca_trade_api.rest import APIError

from .config import BrokerConfig, load_config


# ---------------------------------------------------------------------------
# DATA CLASSES FOR CLEAN INTERNAL REPRESENTATION
# ---------------------------------------------------------------------------

@dataclass
class AccountInfo:
    equity: float
    cash: float
    buying_power: float
    portfolio_value: float
    daily_pnl: float
    daily_pnl_pct: float
    open_position_count: int
    is_trading_blocked: bool
    is_pattern_day_trader: bool

    def __str__(self):
        return (
            f"Account | Equity: ${self.equity:,.2f} | Cash: ${self.cash:,.2f} | "
            f"Buying Power: ${self.buying_power:,.2f} | "
            f"Daily P&L: ${self.daily_pnl:+,.2f} ({self.daily_pnl_pct:+.2f}%) | "
            f"Open Positions: {self.open_position_count}"
        )


@dataclass
class Position:
    ticker: str
    qty: float
    side: str                   # "long" or "short"
    avg_entry_price: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    cost_basis: float

    def __str__(self):
        return (
            f"{self.ticker:6s} | {self.side:5s} | Qty: {self.qty:.1f} | "
            f"Entry: ${self.avg_entry_price:.2f} | Now: ${self.current_price:.2f} | "
            f"P&L: ${self.unrealized_pnl:+,.2f} ({self.unrealized_pnl_pct:+.1f}%)"
        )


@dataclass
class OrderResult:
    order_id: str
    ticker: str
    side: str
    qty: float
    order_type: str
    status: str
    filled_price: Optional[float] = None
    filled_qty: Optional[float] = None
    submitted_at: Optional[str] = None
    error: Optional[str] = None

    @property
    def is_filled(self) -> bool:
        return self.status == "filled"

    @property
    def is_pending(self) -> bool:
        return self.status in ("new", "accepted", "pending_new", "partially_filled")

    def __str__(self):
        price_str = f"@ ${self.filled_price:.2f}" if self.filled_price else ""
        return (
            f"Order {self.order_id[:8]}... | {self.side.upper()} {self.qty} {self.ticker} "
            f"| {self.order_type} | {self.status} {price_str}"
        )


# ---------------------------------------------------------------------------
# BROKER CLASS
# ---------------------------------------------------------------------------

class AlpacaBroker:
    """
    Clean wrapper around Alpaca's REST API.

    Usage:
        broker = AlpacaBroker(config.broker)
        acct = broker.get_account()
        broker.submit_limit_buy("AAPL", qty=10, limit_price=185.50)
    """

    def __init__(self, config: BrokerConfig):
        self.config = config
        self.api = tradeapi.REST(
            key_id=config.api_key,
            secret_key=config.secret_key,
            base_url=config.base_url,
            api_version="v2",
        )
        self._validate_connection()

    def _validate_connection(self):
        """Test API connection on init."""
        try:
            acct = self.api.get_account()
            mode = "PAPER" if self.config.is_paper else "LIVE"
            print(f"[Broker] Connected to Alpaca ({mode})")
            print(f"[Broker] Account equity: ${float(acct.equity):,.2f}")
            print(f"[Broker] Buying power:   ${float(acct.buying_power):,.2f}")
        except APIError as e:
            raise ConnectionError(f"Failed to connect to Alpaca: {e}")

    # ----- ACCOUNT -----

    def get_account(self) -> AccountInfo:
        """Get current account snapshot."""
        a = self.api.get_account()
        equity = float(a.equity)
        last_equity = float(a.last_equity)
        daily_pnl = equity - last_equity
        daily_pnl_pct = (daily_pnl / last_equity * 100) if last_equity > 0 else 0.0

        positions = self.api.list_positions()

        return AccountInfo(
            equity=equity,
            cash=float(a.cash),
            buying_power=float(a.buying_power),
            portfolio_value=float(a.portfolio_value),
            daily_pnl=daily_pnl,
            daily_pnl_pct=daily_pnl_pct,
            open_position_count=len(positions),
            is_trading_blocked=a.trading_blocked,
            is_pattern_day_trader=a.pattern_day_trader,
        )

    # ----- POSITIONS -----

    def get_positions(self) -> List[Position]:
        """Get all open positions."""
        raw = self.api.list_positions()
        positions = []
        for p in raw:
            cost_basis = float(p.cost_basis)
            market_value = float(p.market_value)
            unrealized_pnl = float(p.unrealized_pl)
            unrealized_pnl_pct = float(p.unrealized_plpc) * 100

            positions.append(Position(
                ticker=p.symbol,
                qty=float(p.qty),
                side=p.side,
                avg_entry_price=float(p.avg_entry_price),
                current_price=float(p.current_price),
                market_value=market_value,
                unrealized_pnl=unrealized_pnl,
                unrealized_pnl_pct=unrealized_pnl_pct,
                cost_basis=cost_basis,
            ))
        return positions

    def get_position(self, ticker: str) -> Optional[Position]:
        """Get a single position by ticker. Returns None if not held."""
        try:
            p = self.api.get_position(ticker.upper())
            return Position(
                ticker=p.symbol,
                qty=float(p.qty),
                side=p.side,
                avg_entry_price=float(p.avg_entry_price),
                current_price=float(p.current_price),
                market_value=float(p.market_value),
                unrealized_pnl=float(p.unrealized_pl),
                unrealized_pnl_pct=float(p.unrealized_plpc) * 100,
                cost_basis=float(p.cost_basis),
            )
        except APIError:
            return None

    # ----- ORDERS -----

    def submit_market_buy(self, ticker: str, qty: float) -> OrderResult:
        """Submit a market buy order."""
        return self._submit_order(ticker, qty, "buy", "market")

    def submit_market_sell(self, ticker: str, qty: float) -> OrderResult:
        """Submit a market sell order."""
        return self._submit_order(ticker, qty, "sell", "market")

    def submit_limit_buy(self, ticker: str, qty: float, limit_price: float) -> OrderResult:
        """Submit a limit buy order."""
        return self._submit_order(ticker, qty, "buy", "limit", limit_price=limit_price)

    def submit_limit_sell(self, ticker: str, qty: float, limit_price: float) -> OrderResult:
        """Submit a limit sell order."""
        return self._submit_order(ticker, qty, "sell", "limit", limit_price=limit_price)

    def submit_bracket_buy(
        self,
        ticker: str,
        qty: float,
        limit_price: float,
        stop_loss_price: float,
        take_profit_price: float,
    ) -> OrderResult:
        """
        Submit a bracket order: limit buy entry with attached stop-loss and take-profit.
        This is the workhorse order type — entry + risk management in one shot.
        """
        try:
            order = self.api.submit_order(
                symbol=ticker.upper(),
                qty=qty,
                side="buy",
                type="limit",
                time_in_force="day",
                limit_price=str(round(limit_price, 2)),
                order_class="bracket",
                take_profit={"limit_price": str(round(take_profit_price, 2))},
                stop_loss={"stop_price": str(round(stop_loss_price, 2))},
            )
            return self._parse_order(order)
        except APIError as e:
            return OrderResult(
                order_id="FAILED", ticker=ticker, side="buy",
                qty=qty, order_type="bracket", status="rejected",
                error=str(e),
            )

    def submit_trailing_stop(
        self, ticker: str, qty: float, trail_percent: float
    ) -> OrderResult:
        """Submit a trailing stop sell order."""
        try:
            order = self.api.submit_order(
                symbol=ticker.upper(),
                qty=qty,
                side="sell",
                type="trailing_stop",
                time_in_force="gtc",
                trail_percent=str(round(trail_percent, 1)),
            )
            return self._parse_order(order)
        except APIError as e:
            return OrderResult(
                order_id="FAILED", ticker=ticker, side="sell",
                qty=qty, order_type="trailing_stop", status="rejected",
                error=str(e),
            )

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order."""
        try:
            self.api.cancel_order(order_id)
            return True
        except APIError:
            return False

    def cancel_all_orders(self) -> int:
        """Cancel all open orders. Returns count cancelled."""
        try:
            cancelled = self.api.cancel_all_orders()
            return len(cancelled) if cancelled else 0
        except APIError:
            return 0

    def get_open_orders(self, ticker: Optional[str] = None) -> List[OrderResult]:
        """Get all open/pending orders, optionally filtered by ticker."""
        raw = self.api.list_orders(status="open")
        orders = [self._parse_order(o) for o in raw]
        if ticker:
            orders = [o for o in orders if o.ticker == ticker.upper()]
        return orders

    def close_position(self, ticker: str) -> OrderResult:
        """Close an entire position at market."""
        try:
            order = self.api.close_position(ticker.upper())
            return self._parse_order(order)
        except APIError as e:
            return OrderResult(
                order_id="FAILED", ticker=ticker, side="sell",
                qty=0, order_type="market", status="rejected",
                error=str(e),
            )

    def close_all_positions(self) -> List[OrderResult]:
        """Flatten everything. Nuclear option."""
        try:
            results = self.api.close_all_positions()
            return [self._parse_order(r) for r in results]
        except APIError:
            return []

    # ----- MARKET DATA -----

    def get_latest_price(self, ticker: str) -> Optional[float]:
        """Get the latest trade price for a ticker."""
        try:
            trade = self.api.get_latest_trade(ticker.upper())
            return float(trade.price)
        except Exception:
            return None

    def get_latest_prices(self, tickers: List[str]) -> Dict[str, float]:
        """Get latest prices for multiple tickers."""
        prices = {}
        for t in tickers:
            p = self.get_latest_price(t)
            if p is not None:
                prices[t.upper()] = p
        return prices

    def is_market_open(self) -> bool:
        """Check if the market is currently open."""
        try:
            clock = self.api.get_clock()
            return clock.is_open
        except Exception:
            return False

    def get_clock(self) -> dict:
        """Get market clock info."""
        clock = self.api.get_clock()
        return {
            "is_open": clock.is_open,
            "next_open": str(clock.next_open),
            "next_close": str(clock.next_close),
            "timestamp": str(clock.timestamp),
        }

    # ----- INTERNAL -----

    def _submit_order(
        self,
        ticker: str,
        qty: float,
        side: str,
        order_type: str,
        limit_price: Optional[float] = None,
    ) -> OrderResult:
        """Generic order submission."""
        try:
            kwargs = {
                "symbol": ticker.upper(),
                "qty": qty,
                "side": side,
                "type": order_type,
                "time_in_force": "day",
            }
            if limit_price is not None:
                kwargs["limit_price"] = str(round(limit_price, 2))

            order = self.api.submit_order(**kwargs)
            return self._parse_order(order)

        except APIError as e:
            return OrderResult(
                order_id="FAILED",
                ticker=ticker,
                side=side,
                qty=qty,
                order_type=order_type,
                status="rejected",
                error=str(e),
            )

    @staticmethod
    def _parse_order(order) -> OrderResult:
        """Convert Alpaca order object to our OrderResult."""
        filled_price = None
        if hasattr(order, "filled_avg_price") and order.filled_avg_price:
            filled_price = float(order.filled_avg_price)

        filled_qty = None
        if hasattr(order, "filled_qty") and order.filled_qty:
            filled_qty = float(order.filled_qty)

        return OrderResult(
            order_id=str(order.id),
            ticker=order.symbol,
            side=order.side,
            qty=float(order.qty),
            order_type=order.type,
            status=order.status,
            filled_price=filled_price,
            filled_qty=filled_qty,
            submitted_at=str(order.submitted_at) if hasattr(order, "submitted_at") else None,
        )


# ---------------------------------------------------------------------------
# QUICK TEST
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("RD AutoTrader — Broker Connection Test")
    print("=" * 60)

    cfg = load_config()
    broker = AlpacaBroker(cfg.broker)

    # Account info
    acct = broker.get_account()
    print(f"\n{acct}")

    # Market status
    clock = broker.get_clock()
    print(f"\nMarket open: {clock['is_open']}")
    print(f"Next open:   {clock['next_open']}")
    print(f"Next close:  {clock['next_close']}")

    # Positions
    positions = broker.get_positions()
    if positions:
        print(f"\nOpen Positions ({len(positions)}):")
        for p in positions:
            print(f"  {p}")
    else:
        print("\nNo open positions.")

    # Open orders
    orders = broker.get_open_orders()
    if orders:
        print(f"\nOpen Orders ({len(orders)}):")
        for o in orders:
            print(f"  {o}")
    else:
        print("No open orders.")

    # Price check
    test_tickers = ["XLE", "GLD", "XLB", "SPY"]
    prices = broker.get_latest_prices(test_tickers)
    print(f"\nLatest Prices:")
    for t, p in prices.items():
        print(f"  {t}: ${p:.2f}")

    print("\n✅ Connection test complete.")
