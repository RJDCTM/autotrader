#!/usr/bin/env python3
"""
go.py — RD AutoTrader Master Menu
One command to rule them all: python go.py
"""

import os
import sys
import time

BANNER = """
╔══════════════════════════════════════════════════════════════════╗
║                  RD AUTOTRADER v1.0                             ║
║              Systematic Execution Engine                        ║
╚══════════════════════════════════════════════════════════════════╝
"""

def clear():
    os.system('cls' if os.name == 'nt' else 'clear')

def run_module(label, cmd):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    os.system(cmd)

def morning_routine():
    """Workflow 1: Pre-market → Morning scan → Alerts"""
    print("\n  🌅 MORNING ROUTINE")
    print("  " + "="*50)
    run_module('GAP SCANNER', 'python gap_scanner.py')
    input('\n  Press Enter to continue to Command Center...')
    run_module('COMMAND CENTER', 'python command_center.py')
    input('\n  Press Enter to run Morning Scanner...')
    run_module('MORNING SCANNER', 'python morning_scan.py --save')
    input('\n  Press Enter to check Alerts...')
    run_module('ALERTS CHECK', 'python alerts.py')
    print("\n  ✅ Morning routine complete.")

def execute_signals():
    """Workflow 2: Scan → Route → Confirm → Execute"""
    print("\n  ⚡ EXECUTE SIGNALS")
    print("  " + "="*50)
    run_module('MORNING SCANNER', 'python morning_scan.py --save')
    input('\n  Press Enter to route signals...')
    run_module('SIGNAL ROUTER', 'python run_strategies.py')
    print("\n  ✅ Signal execution complete.")

def monitor_mode():
    """Workflow 3: Continuous position monitoring"""
    print("\n  👁️  MONITOR MODE (Ctrl+C to exit)")
    print("  " + "="*50)
    run_module('CONTINUOUS ALERTS', 'python alerts.py --loop')

def end_of_day():
    """Workflow 4: EOD review"""
    print("\n  🌙 END OF DAY")
    print("  " + "="*50)
    run_module('TRAILING STOPS', 'python trailing_stop.py --update-all')
    run_module('PERFORMANCE', 'python performance.py --snapshot')
    run_module('RISK CHECK', 'python risk_dashboard.py')
    input('\n  Press Enter for journal entry...')
    run_module('JOURNAL', 'python journal.py --add')
    run_module('DAILY REPORT', 'python report.py --daily --save')
    print("\n  ✅ End of day complete.")

def weekend_review():
    """Workflow 5: Full weekend analysis"""
    print("\n  📊 WEEKEND REVIEW")
    print("  " + "="*50)
    run_module('MARKET REGIME', 'python regime.py --detailed')
    run_module('SECTOR RANKER', 'python sector_ranker.py')
    run_module('BATCH BACKTEST', 'python batch_backtest.py --include-etfs --save')
    input('\n  Press Enter to apply optimized settings...')
    run_module('APPLY SETTINGS', 'python apply_settings.py --apply-all-playbook')
    run_module('SIGNAL QUALITY', 'python signal_quality.py')
    run_module('JOURNAL INSIGHTS', 'python journal.py --insights')
    run_module('WEEKLY REPORT', 'python report.py --weekly --save --csv')
    print("\n  ✅ Weekend review complete.")

def main_menu():
    clear()
    print(BANNER)
    print("  WORKFLOWS")
    print("  " + "-"*50)
    print("  1  Morning Routine     (gaps → scan → alerts)")
    print("  2  Execute Signals     (scan → route → trade)")
    print("  3  Monitor Mode        (continuous alerts)")
    print("  4  End of Day          (perf → journal → report)")
    print("  5  Weekend Review      (regime → backtest → optimize)")
    print()
    print("  INDIVIDUAL TOOLS")
    print("  " + "-"*50)
    print("  c  Command Center     p  Performance")
    print("  s  Morning Scanner    j  Trade Journal")
    print("  m  Position Monitor   r  Risk Dashboard")
    print("  a  Alerts             w  Watchlist")
    print("  k  Sector Ranker      b  Backtest")
    print("  o  Optimizer          t  Apply Settings")
    print("  d  Dashboard          x  Batch Backtest")
    print("  g  Daily Report       G  Weekly Report")
    print("  R  Market Regime      T  Trailing Stops")
    print("  S  Signal Quality     P  Gap Scanner")
    print()
    print("  q  Quit")
    print()

    workflows = {
        '1': morning_routine,
        '2': execute_signals,
        '3': monitor_mode,
        '4': end_of_day,
        '5': weekend_review,
    }

    tools = {
        'c': lambda: os.system('python command_center.py'),
        's': lambda: os.system('python morning_scan.py --save'),
        'm': lambda: os.system('python monitor.py'),
        'a': lambda: os.system('python alerts.py'),
        'k': lambda: os.system('python sector_ranker.py'),
        'o': lambda: os.system('python optimizer.py'),
        'd': lambda: os.system('python dashboard.py'),
        'p': lambda: os.system('python performance.py'),
        'j': lambda: os.system('python journal.py'),
        'r': lambda: os.system('python risk_dashboard.py'),
        'w': lambda: os.system('python watchlist.py'),
        'b': lambda: os.system('python backtest.py'),
        't': lambda: os.system('python apply_settings.py'),
        'x': lambda: os.system('python batch_backtest.py --include-etfs'),
        'g': lambda: os.system('python report.py --daily --save'),
        'G': lambda: os.system('python report.py --weekly --save --csv'),
        'R': lambda: os.system('python regime.py --detailed'),
        'T': lambda: os.system('python trailing_stop.py'),
        'S': lambda: os.system('python signal_quality.py'),
        'P': lambda: os.system('python gap_scanner.py'),
    }

    choice = input("  > ").strip()

    if choice == 'q':
        print("\n  👋 See you next session.\n")
        sys.exit(0)
    elif choice in workflows:
        workflows[choice]()
    elif choice in tools:
        tools[choice]()
    else:
        print(f"\n  Unknown command: {choice}")

    input('\n  Press Enter to return to menu...')
    main_menu()

if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        print("\n\n  👋 Exiting.\n")
