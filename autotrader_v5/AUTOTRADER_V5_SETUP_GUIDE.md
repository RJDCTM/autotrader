# Autotrader v5 — Setup & Deployment Guide
## Paper Trading Launch: Feb 17, 2026

---

## What Changed: v4 → v5

### The Problem with v4
v4 used Trend as 35% of the composite score. Backtesting revealed this **created negative correlation** with forward returns in the full universe (Spearman r = -0.116). Why? When trend is already baked into the score, you're double-counting — stocks that are already extended get the highest scores, but they're also most likely to mean-revert.

### The v5 Fix: Gate + Flow Ranking
- **Trend becomes a binary GATE** (pass/fail): Price must be above 20/50/200 EMA AND ≤10% extended from 20 EMA
- **Ranking uses only flow signals**: Options 30% + Dark Pool 25% + Volume 25% + Momentum 20%
- This isolates "who's buying" from "where price is" — the combination is what has edge

### Backtest Proof (Jan 31 → Feb 13, 472 gated stocks)

| Metric | v4 Gated | v5 Gated | Improvement |
|--------|----------|----------|-------------|
| Spearman r | +0.219 | **+0.272** | +24% |
| p-value | 1.5e-6 | **2.0e-9** | 1000× more significant |
| Q5-Q1 spread | +1.81% | **+3.26%** | +80% |
| Top 10 hit rate | 100% | **100%** | Same |
| Top 25 hit rate | 92% | **96%** | +4pp |
| Top 50 hit rate | 92% | **94%** | +2pp |

---

## Files Delivered

| File | Purpose | Lines |
|------|---------|-------|
| `scoring_engine_v5.py` | Core v5 scoring — gate, component scores, structure, flow conviction, actions | ~350 |
| `autotrader_dashboard.py` | Streamlit app — signal generation, position management, trade journal, analytics | ~650 |
| `requirements.txt` | Python dependencies | 7 |

### Architecture

```
scoring_engine_v5.py          ← Pure scoring logic (no UI, no broker)
    ↑ imported by
autotrader_dashboard.py       ← Streamlit UI + Alpaca broker + trade engine
    ↑ uses
Quickview_v5_Feb17.csv        ← Weekly scored data (from pipeline)
```

---

## Step-by-Step Setup

### Step 1: Install Python Environment

```bash
# Create virtual environment (recommended)
python3 -m venv autotrader_env
source autotrader_env/bin/activate   # macOS/Linux
# OR: autotrader_env\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
```

### Step 2: Set Up Alpaca Paper Trading Account

1. Go to https://app.alpaca.markets/signup
2. Create account (free)
3. Navigate to **Paper Trading** section
4. Generate **API Key** and **Secret Key**
5. Set environment variables:

```bash
export ALPACA_API_KEY="your_paper_key_here"
export ALPACA_API_SECRET="your_paper_secret_here"
```

Or enter them in the Streamlit sidebar when the app launches.

### Step 3: Place Files in Project Directory

```bash
mkdir -p ~/autotrader_v5
cd ~/autotrader_v5

# Copy these files into the directory:
# - scoring_engine_v5.py
# - autotrader_dashboard.py
# - requirements.txt
# - Quickview_v5_Feb17.csv (from weekly pipeline output)
```

### Step 4: Launch the Dashboard

```bash
cd ~/autotrader_v5
streamlit run autotrader_dashboard.py
```

This opens the dashboard at `http://localhost:8501`.

### Step 5: Load Data & Start Paper Trading

1. **Tab 1 (Data Upload):** Upload `Quickview_v5_Feb17.csv` — the app detects it's already scored and loads directly
2. **Tab 2 (Entry Signals):** Review top candidates with sizing recommendations
3. Click **Execute** on signals you approve (paper trades via Alpaca)
4. **Tab 3 (Exit Signals):** Monitor for exit triggers as positions develop
5. **Tab 5 (Trade Journal):** All trades logged with timestamps, scores, and P&L

---

## How It Works

### Scoring Flow

```
Raw Universe (800+ stocks)
    │
    ▼
┌────────────────────────┐
│  TREND GATE (Pass/Fail)│
│  • Above 20/50/200 EMA │
│  • ≤10% extended       │
│  • Price ≥ $5          │
│  • Avg Vol ≥ 200K      │
└────────┬───────────────┘
         │ ~60-70% pass
         ▼
┌────────────────────────┐
│  v5 COMPOSITE SCORE    │
│  Options:    30%       │
│  Dark Pool:  25%       │
│  Volume:     25%       │
│  Momentum:   20%       │
└────────┬───────────────┘
         │
         ▼
┌────────────────────────┐
│  FLOW CONVICTION       │
│  🐋 Whale (2+ strong)  │
│  📊 Moderate (2+ ok)   │
│  💧 Light              │
│  🔻 Weak/Bearish       │
└────────┬───────────────┘
         │
         ▼
┌────────────────────────┐
│  ACTION ASSIGNMENT     │
│  🟢 Strong Buy (≥40)   │
│  🟡 Buy on dip (≥30)   │
│  🔵 Accumulate (≥20)   │
│  📋 Monitor (<20)      │
└────────────────────────┘
```

### Position Sizing Logic

```
Max Position = Portfolio × 5%
Max Risk     = Portfolio × 2%
Stop Distance = ATR × 2.0

Shares from Risk = Max Risk ÷ Stop Distance
Shares from Position = Max Position ÷ Price
Final Shares = min(Risk, Position) × Score Scale × Whale Bonus

Score Scale:
  ≥50 → 100% size
  ≥40 → 75% size
  <40 → 50% size

Whale Bonus:
  🐋 flow → +25% size (capped at 100%)
```

### Exit Framework (Bot Rules v3.0)

| Trigger | Action | Urgency |
|---------|--------|---------|
| Score < 25 (min hold) | Trim signal | 🟠 2/3 |
| Failed trend gate | Full exit signal | 🔴 3/3 |
| Extension ≥ 12% above 20EMA | Trim 50% | 🟠 2/3 |
| Extension ≥ 8% above 20EMA | Trim 25% | 🟡 1/3 |
| Trailing stop hit (2×ATR) | Full exit | 🔴 3/3 |
| P&L ≤ -7% | Stop loss | 🔴 3/3 |

### Circuit Breakers

- **Daily loss ≥ $1,500** → All trading halted
- **Daily trades ≥ 8** → No new entries
- **3:50 PM** → Force close all 0DTE positions (Mancini)

---

## Daily Workflow

### Morning (Pre-Market)
1. Review overnight dark pool prints and OI changes
2. Upload fresh Quickview CSV if pipeline ran overnight
3. Check exit signals on existing positions
4. Note whale flow candidates for watchlist

### Market Open (9:30-10:00)
1. Let first 30 minutes settle (avoid opening noise)
2. Check for failed breakdowns/breakouts (Mancini signals on SPY)
3. Review entry signals — execute top 2-3 if conviction is there

### Midday (11:00-14:00)
1. Monitor positions — check extension from 20EMA
2. Manage trailing stops
3. Light scanning for additional entries if under position limit

### Close (15:00-16:00)
1. Review all exit signals
2. Close any 0DTE Mancini positions
3. Journal review — note what worked/failed
4. Download trade journal CSV for recordkeeping

### Weekly (Sunday Night)
1. Run full weekly pipeline to generate new Quickview_v5
2. Review sector rotation table
3. Adjust watchlist for the week
4. Check backtest metrics against live performance

---

## Updating the Scoring Weights

If future backtesting suggests different weights, edit `scoring_engine_v5.py`:

```python
# In scoring_engine_v5.py, line ~20
V5_WEIGHTS = {
    "options": 0.30,    # ← change these
    "darkpool": 0.25,
    "volume": 0.25,
    "momentum": 0.20,
}
```

The dashboard auto-reloads on file save (Streamlit's hot-reload).

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `ModuleNotFoundError: scoring_engine_v5` | Both .py files must be in the same directory |
| `alpaca-py not installed` | App runs in dry mode — signals still generate, no orders execute |
| `No data uploaded` | Upload Quickview CSV in Tab 1 first |
| Streamlit won't start | Check Python version ≥ 3.10, try `pip install --upgrade streamlit` |
| Scores look different from pipeline | Verify the CSV has the same column names (ticker, price, sma20_pct, etc.) |

---

## Integration with Existing Pipeline

The weekly pipeline (from our main project code) produces `Quickview_v5_Feb17.csv` which feeds directly into this dashboard. The flow is:

```
Weekly Pipeline (Sunday night)
    ├── Finviz Universe + Screener
    ├── Options OI Changes
    ├── Dark Pool EOD Reports
    ├── Hot Chains
    └── Portfolio Positions
         │
         ▼
    scoring_engine_v5.py (inside pipeline)
         │
         ▼
    Quickview_v5_Feb17.csv  ───→  autotrader_dashboard.py
                                        │
                                        ▼
                                  Alpaca Paper Trading
```

The same `scoring_engine_v5.py` is used by both the weekly pipeline and the autotrader — single source of truth for all scoring logic.
