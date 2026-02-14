#!/usr/bin/env python3
"""
run.py — RD AutoTrader Entry Point

Usage:
    python run.py                  # Interactive mode — run once, show status
    python run.py --loop           # Continuous loop during market hours
    python run.py --signals FILE   # Load signals from CSV and process
    python run.py --status         # Show account & position status only
    python run.py --dry-run        # Process signals without submitting orders
"""

import argparse
import sys

from core.config import load_config
from core.executor import Executor
from core.signals import TradeSignal, SignalAction, StructureType


def main():
    parser = argparse.ArgumentParser(description="RD AutoTrader")
    parser.add_argument("--loop", action="store_true", help="Run continuous loop")
    parser.add_argument("--signals", type=str, help="CSV file with signals to process")
    parser.add_argument("--status", action="store_true", help="Show status only")
    parser.add_argument("--dry-run", action="store_true", help="Don't submit real orders")
    parser.add_argument("--test-buy", type=str, help="Test buy a ticker (paper only)")
    args = parser.parse_args()

    # Load config
    config = load_config()

    if args.dry_run:
        config.dry_run = True
        print("🏜  DRY RUN MODE — no orders will be submitted\n")

    # Initialize executor
    executor = Executor(config)

    if args.status:
        # Just show current state
        executor.run_once()
        return

    if args.signals:
        # Load signals from file and process
        count = executor.load_signals_from_csv(args.signals)
        if count > 0:
            executor.run_once()
        else:
            print("No valid signals found in file.")
        return

    if args.test_buy:
        # Quick test: create a manual signal and run it through
        if not config.broker.is_paper:
            print("❌ Test buys only allowed in paper mode!")
            return

        ticker = args.test_buy.upper()
        price = executor.broker.get_latest_price(ticker)
        if not price:
            print(f"Could not get price for {ticker}")
            return

        signal = TradeSignal(
            ticker=ticker,
            action=SignalAction.BUY,
            entry_price=round(price * 0.999, 2),   # Slight discount
            entry_zone_low=round(price * 0.995, 2),
            entry_zone_high=round(price * 1.005, 2),
            stop_loss_price=round(price * 0.95, 2),
            target_1_price=round(price * 1.05, 2),
            target_2_price=round(price * 1.10, 2),
            position_size_pct=2.0,
            bullish_score=70.0,
            structure=StructureType.BREAKOUT,
            notes=f"Test buy at ${price:.2f}",
        )

        account = executor.broker.get_account()
        signal.calculate_sizing(account.equity, 5.0, 1.0)
        executor.add_manual_signal(signal)
        executor.run_once()
        return

    if args.loop:
        # Continuous trading loop
        print("Starting continuous execution loop...")
        print("Press Ctrl+C to stop.\n")
        executor.run()
    else:
        # Default: single cycle
        executor.run_once()


if __name__ == "__main__":
    main()
