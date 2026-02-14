# RD AUTOTRADER v2.0 — OPERATIONAL CHEAT SHEET
## 25-Tool Engine + Streamlit Web UI

---

## 🌐 STREAMLIT WEB UI

### Launch
```bash
cd autotrader
pip install -r requirements.txt
streamlit run app.py
# Opens http://localhost:8501 — works on phone, tablet, laptop
```

### Pages
| Page | What it does |
|------|-------------|
| Dashboard | Account overview, positions, P&L chart, sector allocation, equity curve |
| Scanner | Morning scan (momentum/swing/reversion scoring) + gap scanner |
| Positions | Trailing stop management with visual phase bars, alerts, new position init |
| Analysis | Market regime (SPY), sector momentum rankings, signal quality review |
| Backtest | Single-ticker backtest, parameter optimizer (~500 combos), batch playbook |
| Journal | Daily psychology journal, performance analytics, daily/weekly reports |

### Mobile Access
- Responsive out of the box — sidebar collapses to hamburger menu on phone
- Remote: `streamlit run app.py --server.address 0.0.0.0`
- Cloud: deploy free on Streamlit Community Cloud for always-on mobile access

### CLI Still Works
All 25 CLI tools still work independently. The web UI is additive.

---

## 🚀 QUICK START (First Time Setup)

```
1. Install Python 3.10+ from python.org
2. Unzip autotrader folder to desired location
3. Open terminal in the autotrader folder
4. pip install -r requirements.txt
5. Copy .env.example to .env
6. Edit .env with your Alpaca API keys:
     ALPACA_API_KEY=your_key_here
     ALPACA_SECRET_KEY=your_secret_here
     ALPACA_BASE_URL=https://paper-api.alpaca.markets
     TRADING_MODE=paper
7. python -m core.broker            # Test connection
8. python go.py                     # Launch master menu
```

---

## 📋 MASTER COMMAND: `python go.py`

| Key | Workflow | What It Does |
|-----|----------|-------------|
| `1` | Morning Routine | Gap scan → Command center → Morning scan → Alerts |
| `2` | Execute Signals | Morning scan → Route to strategies → Confirm trades |
| `3` | Monitor Mode | Continuous position checking (Ctrl+C to stop) |
| `4` | End of Day | Trailing stops → Performance → Risk → Journal → Report |
| `5` | Weekend Review | Regime → Sectors → Batch backtest → Optimize → Report |

---

## 🛠️ ALL 25 TOOLS

### Core Trading
| File | Key | Command | Purpose |
|------|-----|---------|---------|
| `go.py` | — | `python go.py` | Master menu, one command for everything |
| `core/broker.py` | — | `python -m core.broker` | Alpaca API connection & orders |
| `run.py` | — | `python run.py --ticker XLE --strategy swing` | Execute single trade |
| `core/strategy_manager.py` | — | (internal) | 5-strategy engine with routing |

### Strategy Execution
| File | Key | Command | Purpose |
|------|-----|---------|---------|
| `dashboard.py` | `d` | `python dashboard.py` | Strategy bucket overview |
| `run_strategies.py` | — | `python run_strategies.py` | Route signals → confirm → execute |
| `pipeline_connect.py` | — | `python pipeline_connect.py --file data/weekly.xlsx` | Bridge weekly pipeline to autotrader |
| `command_center.py` | `c` | `python command_center.py` | Unified dashboard: account + positions + alerts |

### Market Analysis
| File | Key | Command | Purpose |
|------|-----|---------|---------|
| `morning_scan.py` | `s` | `python morning_scan.py --save` | Scan watchlist for momentum/swing/reversion |
| `sector_ranker.py` | `k` | `python sector_ranker.py` | Rank sector ETFs by momentum |
| `regime.py` | `R` | `python regime.py --detailed` | Market regime: STRONG_BULL → CRISIS |
| `gap_scanner.py` | `P` | `python gap_scanner.py` | Pre-market gap analysis + held alerts |

### Position Management
| File | Key | Command | Purpose |
|------|-----|---------|---------|
| `monitor.py` | `m` | `python monitor.py` | Check stops, targets, time limits |
| `alerts.py` | `a` | `python alerts.py --loop` | Continuous position monitoring |
| `trailing_stop.py` | `T` | `python trailing_stop.py --update-all` | 4-phase ratcheting stop system |

### Analytics & Optimization
| File | Key | Command | Purpose |
|------|-----|---------|---------|
| `backtest.py` | `b` | `python backtest.py --ticker XLE --strategy swing` | Historical strategy testing |
| `optimizer.py` | `o` | `python optimizer.py --ticker XLE --save` | Grid search for optimal settings |
| `batch_backtest.py` | `x` | `python batch_backtest.py --include-etfs --save` | Multi-ticker playbook generator |
| `apply_settings.py` | `t` | `python apply_settings.py --apply-all-playbook` | Push optimized settings to tickers |
| `signal_quality.py` | `S` | `python signal_quality.py` | Signal-to-trade conversion analytics |

### Risk & Reporting
| File | Key | Command | Purpose |
|------|-----|---------|---------|
| `risk_dashboard.py` | `r` | `python risk_dashboard.py` | Exposure, concentration, sector heat |
| `performance.py` | `p` | `python performance.py --snapshot` | Win rate, P&L, equity curve |
| `report.py` | `g/G` | `python report.py --weekly --save --csv` | Daily & weekly reports |

### Organization
| File | Key | Command | Purpose |
|------|-----|---------|---------|
| `watchlist.py` | `w` | `python watchlist.py --add NVDA AMD` | Manage scanner watchlist |
| `journal.py` | `j` | `python journal.py --add` | Trade psychology tracking |

---

## 📅 DAILY WORKFLOWS

### Monday Morning (Pre-Market, ~9:00 AM ET)
```bash
python gap_scanner.py --save           # Check overnight gaps
python regime.py                        # What kind of market today?
python trailing_stop.py --update-all   # Update stops on held positions
python command_center.py               # Full dashboard view
python morning_scan.py --save          # Find today's setups
python run_strategies.py               # Route & confirm trades
```

### During Trading (9:45 AM - 3:30 PM ET)
```bash
python alerts.py --loop                # Continuous monitoring
python trailing_stop.py --update-all   # Every 30 minutes
```

### End of Day (~3:45 PM ET)
```bash
python trailing_stop.py --update-all   # Final stop update
python performance.py --snapshot       # Log equity
python risk_dashboard.py               # Check exposure
python journal.py --add                # Log emotions & lessons
python report.py --daily --save        # Generate report
```

### Weekend Review
```bash
python regime.py --detailed            # Full market analysis
python sector_ranker.py                # Best/worst sectors
python batch_backtest.py --include-etfs --save   # Regenerate playbook
python apply_settings.py --apply-all-playbook    # Push new settings
python signal_quality.py               # How accurate were signals?
python report.py --weekly --save --csv # Weekly summary
python journal.py --insights           # Pattern analysis
```

---

## 🔄 TRAILING STOP PHASES

```
INITIAL → T1_HIT → T2_HIT → RUNAWAY

Phase       Stop Level                  What Happens
─────────   ──────────────────────      ─────────────────────
INITIAL     Entry - stop_pct%           Normal stop loss
T1_HIT      Entry + 0.2% (breakeven)   Lock in breakeven
T2_HIT      Entry + 50% of gains       Trail 50% of max gain
RUNAWAY     Entry + 70% of gains       Lock in 70% of max gain
```

### Example: XLE entry at $54.33
```
INITIAL:  Stop = $51.62 (5% below entry)
T1 @ $56.50: Stop → $54.44 (breakeven + 0.2%)
T2 @ $58.70: Stop → $56.52 (entry + 50% of $4.37 gain)
RUNAWAY @ $63.03: Stop → $60.42 (entry + 70% of $8.70 gain)
```

### Commands:
```bash
python trailing_stop.py --init XLE 54.33 sector_etf    # New position
python trailing_stop.py --update-all                     # Update with live prices
python trailing_stop.py --status XLE                     # Check single ticker
python trailing_stop.py                                  # Show all tracked
```

---

## 📊 STRATEGY SETTINGS (per-ticker)

Settings are stored in `settings/TICKER.json`:
```json
{
  "ticker": "XLE",
  "strategy": "sector_etf",
  "tier": 1,
  "stop_pct": 5.0,
  "target1_pct": 4.0,
  "target2_pct": 8.0,
  "trail_pct": 3.5,
  "max_hold_days": 14
}
```

### 5 Strategy Buckets:
| Strategy | Stop ATR | Target ATR | Hold | Best For |
|----------|----------|-----------|------|----------|
| momentum_breakout | 1.5x | 3.0x | 5d | Strong trend + volume |
| swing | 2.0x | 4.0x | 10d | Range-bound with direction |
| mean_reversion | 2.5x | 2.0x | 5d | Oversold bounces |
| sector_etf | 2.0x | 3.0x | 14d | Sector rotation plays |
| earnings_run | 1.0x | 2.0x | 3d | Pre-earnings momentum |

---

## 🗂️ DIRECTORY STRUCTURE

```
autotrader/
├── go.py                    ← START HERE
├── .env                     ← Your API keys (create from .env.example)
├── core/
│   ├── config.py            ← All settings & risk params
│   ├── broker.py            ← Alpaca API wrapper
│   ├── signals.py           ← Trade signal objects
│   ├── risk.py              ← Circuit breakers & sizing
│   ├── executor.py          ← Order execution engine
│   └── strategy_manager.py  ← 5-strategy router
├── morning_scan.py          ← Daily scanner
├── command_center.py        ← Unified dashboard
├── monitor.py               ← Position checker
├── alerts.py                ← Continuous alerts
├── trailing_stop.py         ← Ratcheting stops
├── sector_ranker.py         ← Sector momentum
├── regime.py                ← Market regime
├── gap_scanner.py           ← Pre-market gaps
├── backtest.py              ← Historical testing
├── optimizer.py             ← Parameter search
├── batch_backtest.py        ← Multi-ticker playbook
├── apply_settings.py        ← Settings automation
├── run_strategies.py        ← Signal router
├── pipeline_connect.py      ← Weekly pipeline bridge
├── performance.py           ← Win rate & P&L
├── risk_dashboard.py        ← Exposure analysis
├── report.py                ← Daily/weekly reports
├── signal_quality.py        ← Signal effectiveness
├── watchlist.py             ← Ticker management
├── journal.py               ← Psychology tracking
├── dashboard.py             ← Strategy buckets
├── run.py                   ← Single trade execution
├── data/
│   ├── watchlist.csv        ← Scanner watchlist
│   └── playbook.json        ← Batch backtest results
├── settings/
│   └── XLE.json             ← Per-ticker optimized settings
└── logs/
    ├── trade_log.csv        ← All trade records
    ├── equity_snapshots.csv ← Daily equity tracking
    ├── trailing_stops.json  ← Active stop positions
    ├── journal.csv          ← Psychology entries
    ├── morning_scan_*.csv   ← Historical scan results
    └── gap_scan_*.csv       ← Gap analysis records
```

---

## ⚙️ RISK GUARDRAILS (config.py)

| Parameter | Default | Description |
|-----------|---------|-------------|
| max_position_pct | 5% | Max % of equity per position |
| max_open_positions | 10 | Max simultaneous positions |
| max_sector_exposure_pct | 25% | Max in one sector |
| daily_loss_halt_pct | -3% | Circuit breaker: halt all entries |
| daily_loss_reduce_pct | -2% | Reduce sizing 50% |
| max_risk_per_trade_pct | 1% | Max loss per trade |
| mandatory_stop_loss | True | Every entry needs a stop |
| no_entry_first_15min | True | Wait until 9:45 AM |
| no_entry_last_30min | True | No entries after 3:30 PM |

---

## 🔧 TROUBLESHOOTING

| Issue | Fix |
|-------|-----|
| "ALPACA_API_KEY must be set" | Create .env file with keys |
| "No module named 'alpaca_trade_api'" | `pip install alpaca-trade-api` |
| "No data available" | Market is closed, or ticker invalid |
| Scanner shows 0 results | Check watchlist.csv exists in data/ |
| Trailing stop not updating | Run `--init` first to track position |
| Settings not applied | Run `batch_backtest.py --save` then `apply_settings.py --apply-all-playbook` |

---

## 📝 IMPORTANT NOTES

1. **Paper trading first.** Always test with TRADING_MODE=paper before going live.
2. **API keys stay local.** Never commit .env to git or share in chat.
3. **Logs accumulate.** Signal quality improves with more scan + trade data over weeks.
4. **Settings are per-ticker.** Optimizer finds what works for each stock individually.
5. **Trailing stops are local.** They don't submit orders to Alpaca — you execute manually or integrate later.
6. **Weekend work:** Batch backtest → Apply settings → Review signal quality. This tunes the system.

---

*Built Feb 2026. Philosophy: You set the thesis. The bot executes without flinching.*
