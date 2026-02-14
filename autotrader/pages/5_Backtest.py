"""
5_Backtest.py — Backtesting & Optimization
Test strategies on historical data, optimize parameters, generate playbooks.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import os, sys, json
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import check_connection

SETTINGS_DIR = "settings"
PLAYBOOK_FILE = "data/playbook.json"

STRATEGIES = ["momentum_breakout", "swing", "mean_reversion", "sector_etf", "earnings_run"]

# Default strategy parameter ranges for optimizer
PARAM_GRID = {
    "stop_atr": [1.0, 1.5, 2.0, 2.5, 3.0],
    "target_atr": [2.0, 3.0, 4.0, 5.0],
    "trail_atr": [1.5, 2.0, 2.5, 3.0],
    "max_hold": [3, 5, 7, 10, 14],
}

st.title("🧪 Backtest & Optimize")

broker = check_connection()

tab_single, tab_optimize, tab_batch = st.tabs(["📊 Single Backtest", "⚙️ Optimizer", "📋 Batch Playbook"])


def run_backtest(ticker, strategy, bars_data, stop_atr=2.0, target_atr=3.0,
                 trail_atr=2.0, max_hold=7):
    """Run backtest on historical bars. Returns list of trade dicts."""
    if len(bars_data) < 30:
        return []

    closes = [b["c"] for b in bars_data]
    highs = [b["h"] for b in bars_data]
    lows = [b["l"] for b in bars_data]
    volumes = [b["v"] for b in bars_data]
    dates = [b["t"] for b in bars_data]

    trades = []
    in_trade = False
    entry_price = 0
    entry_idx = 0
    stop_price = 0
    target_price = 0
    trail_stop = 0
    highest_since_entry = 0

    for i in range(20, len(closes)):
        sma20 = np.mean(closes[i-20:i])
        sma50 = np.mean(closes[max(0,i-50):i]) if i >= 50 else sma20

        # ATR
        tr_vals = []
        for j in range(max(1, i-10), i):
            tr_vals.append(max(highs[j]-lows[j],
                              abs(highs[j]-closes[j-1]),
                              abs(lows[j]-closes[j-1])))
        atr = np.mean(tr_vals) if tr_vals else 1

        # RSI
        if i >= 14:
            deltas = np.diff(closes[i-14:i+1])
            g = np.mean(np.where(deltas > 0, deltas, 0))
            l_val = np.mean(np.where(deltas < 0, -deltas, 0))
            rsi = 100 - (100 / (1 + g / (l_val + 1e-10)))
        else:
            rsi = 50

        vol_ratio = volumes[i] / np.mean(volumes[max(0,i-20):i]) if i >= 20 else 1

        if in_trade:
            # Update highest
            if closes[i] > highest_since_entry:
                highest_since_entry = closes[i]
                # Trail stop
                new_trail = highest_since_entry - trail_atr * atr
                trail_stop = max(trail_stop, new_trail)

            # Check exits
            exit_reason = None
            exit_price = closes[i]

            if lows[i] <= stop_price:
                exit_reason = "Stop"
                exit_price = stop_price
            elif lows[i] <= trail_stop and trail_stop > stop_price:
                exit_reason = "Trail"
                exit_price = trail_stop
            elif highs[i] >= target_price:
                exit_reason = "Target"
                exit_price = target_price
            elif (i - entry_idx) >= max_hold:
                exit_reason = "Time"

            if exit_reason:
                pnl_pct = (exit_price - entry_price) / entry_price * 100
                trades.append({
                    "entry_date": str(dates[entry_idx])[:10],
                    "exit_date": str(dates[i])[:10],
                    "entry": round(entry_price, 2),
                    "exit": round(exit_price, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "hold_days": i - entry_idx,
                    "exit_reason": exit_reason,
                })
                in_trade = False
            continue

        # Entry signals by strategy
        signal = False

        if strategy == "momentum_breakout":
            if closes[i] > sma20 and sma20 > sma50 and rsi > 55 and vol_ratio > 1.1:
                signal = True

        elif strategy == "swing":
            if abs(closes[i] - sma20) / sma20 < 0.02 and 45 < rsi < 60 and closes[i] > sma50:
                signal = True

        elif strategy == "mean_reversion":
            dist = (closes[i] - sma20) / sma20 * 100
            if dist < -3 and rsi < 35:
                signal = True

        elif strategy == "sector_etf":
            if closes[i] > sma20 and closes[i] > sma50 and vol_ratio > 0.9:
                signal = True

        elif strategy == "earnings_run":
            if closes[i] > sma20 and rsi > 50 and vol_ratio > 1.3:
                signal = True

        if signal:
            entry_price = closes[i]
            entry_idx = i
            stop_price = entry_price - stop_atr * atr
            target_price = entry_price + target_atr * atr
            trail_stop = stop_price
            highest_since_entry = entry_price
            in_trade = True

    return trades


def fetch_bars(ticker, days=180):
    """Fetch historical bars for backtesting."""
    end = datetime.now()
    start = end - timedelta(days=days + 30)
    bars = broker.api.get_bars(ticker, "1Day",
                               start=start.strftime("%Y-%m-%d"),
                               end=end.strftime("%Y-%m-%d"), limit=days)
    return [{"o": b.o, "h": b.h, "l": b.l, "c": b.c, "v": b.v, "t": b.t} for b in bars]


# ═══════════════════════════════════════════════════════════════════════
# SINGLE BACKTEST
# ═══════════════════════════════════════════════════════════════════════
with tab_single:
    c1, c2, c3 = st.columns(3)
    with c1:
        bt_ticker = st.text_input("Ticker", "XLE", key="bt_ticker").upper()
    with c2:
        bt_strat = st.selectbox("Strategy", STRATEGIES, key="bt_strat")
    with c3:
        bt_days = st.number_input("Lookback (days)", 60, 365, 180, key="bt_days")

    c4, c5, c6, c7 = st.columns(4)
    with c4:
        bt_stop = st.number_input("Stop ATR", 0.5, 5.0, 2.0, 0.5, key="bt_stop")
    with c5:
        bt_target = st.number_input("Target ATR", 1.0, 8.0, 3.0, 0.5, key="bt_target")
    with c6:
        bt_trail = st.number_input("Trail ATR", 0.5, 5.0, 2.0, 0.5, key="bt_trail")
    with c7:
        bt_hold = st.number_input("Max Hold (days)", 1, 30, 7, key="bt_hold")

    if st.button("🚀 Run Backtest", use_container_width=True, type="primary", key="bt_run"):
        with st.spinner(f"Backtesting {bt_ticker} / {bt_strat}..."):
            try:
                bars = fetch_bars(bt_ticker, bt_days)
                trades = run_backtest(bt_ticker, bt_strat, bars,
                                      bt_stop, bt_target, bt_trail, bt_hold)

                if not trades:
                    st.warning("No trades generated. Try a different strategy or longer lookback.")
                else:
                    df = pd.DataFrame(trades)
                    wins = df[df["pnl_pct"] > 0]
                    losses = df[df["pnl_pct"] <= 0]
                    win_rate = len(wins) / len(df) * 100

                    # Metrics
                    m1, m2, m3, m4, m5 = st.columns(5)
                    m1.metric("Trades", len(df))
                    m2.metric("Win Rate", f"{win_rate:.0f}%")
                    m3.metric("Total P&L", f"{df['pnl_pct'].sum():+.1f}%")
                    m4.metric("Avg Win", f"{wins['pnl_pct'].mean():+.1f}%" if len(wins) else "—")
                    m5.metric("Avg Loss", f"{losses['pnl_pct'].mean():+.1f}%" if len(losses) else "—")

                    # Profit factor
                    gross_win = wins["pnl_pct"].sum() if len(wins) else 0
                    gross_loss = abs(losses["pnl_pct"].sum()) if len(losses) else 1
                    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
                    avg_hold = df["hold_days"].mean()

                    m6, m7, m8 = st.columns(3)
                    m6.metric("Profit Factor", f"{pf:.2f}")
                    m7.metric("Avg Hold (days)", f"{avg_hold:.1f}")
                    m8.metric("Expectancy", f"{df['pnl_pct'].mean():+.2f}% / trade")

                    # Equity curve
                    equity = [100]
                    for t in trades:
                        equity.append(equity[-1] * (1 + t["pnl_pct"] / 100))

                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        y=equity, mode="lines+markers",
                        line=dict(color="#3b82f6", width=2),
                        fill="tozeroy", fillcolor="rgba(59,130,246,0.1)",
                    ))
                    fig.add_hline(y=100, line_dash="dash", line_color="#6b7280")
                    fig.update_layout(title="Equity Curve ($100 start)", height=300,
                                     template="plotly_dark",
                                     margin=dict(l=20, r=20, t=40, b=20),
                                     yaxis_title="Equity ($)")
                    st.plotly_chart(fig, use_container_width=True)

                    # Exit reason breakdown
                    exit_counts = df["exit_reason"].value_counts()
                    fig2 = go.Figure(go.Pie(
                        labels=exit_counts.index, values=exit_counts.values,
                        hole=0.3,
                    ))
                    fig2.update_layout(title="Exit Reasons", height=250,
                                      template="plotly_dark")
                    st.plotly_chart(fig2, use_container_width=True)

                    # Trade table
                    st.subheader("Trade Log")
                    def pnl_color(val):
                        if isinstance(val, (int, float)):
                            return "color: #22c55e" if val > 0 else "color: #ef4444" if val < 0 else ""
                        return ""

                    styled = df.style.format({
                        "entry": "${:.2f}", "exit": "${:.2f}", "pnl_pct": "{:+.2f}%",
                    }).map(pnl_color, subset=["pnl_pct"])
                    st.dataframe(styled, use_container_width=True, hide_index=True)

                    # Save button
                    if st.button("💾 Save Backtest Results"):
                        os.makedirs("logs", exist_ok=True)
                        fname = f"logs/backtest_{bt_ticker}_{bt_strat}_{datetime.now().strftime('%Y%m%d')}.csv"
                        df.to_csv(fname, index=False)
                        st.success(f"Saved: {fname}")

            except Exception as e:
                st.error(f"Backtest error: {e}")


# ═══════════════════════════════════════════════════════════════════════
# OPTIMIZER
# ═══════════════════════════════════════════════════════════════════════
with tab_optimize:
    c1, c2 = st.columns(2)
    with c1:
        opt_ticker = st.text_input("Ticker", "XLE", key="opt_ticker").upper()
    with c2:
        opt_strat = st.selectbox("Strategy", STRATEGIES, key="opt_strat")

    opt_days = st.slider("Lookback (days)", 60, 365, 180, key="opt_days")

    if st.button("⚙️ Run Optimizer", use_container_width=True, type="primary", key="opt_run"):
        with st.spinner(f"Optimizing {opt_ticker} / {opt_strat}... (testing ~500 combinations)"):
            try:
                bars = fetch_bars(opt_ticker, opt_days)

                results = []
                total = (len(PARAM_GRID["stop_atr"]) * len(PARAM_GRID["target_atr"]) *
                         len(PARAM_GRID["trail_atr"]) * len(PARAM_GRID["max_hold"]))

                progress = st.progress(0, text="Testing parameter combinations...")
                count = 0

                for sa in PARAM_GRID["stop_atr"]:
                    for ta in PARAM_GRID["target_atr"]:
                        for tra in PARAM_GRID["trail_atr"]:
                            for mh in PARAM_GRID["max_hold"]:
                                count += 1
                                if count % 25 == 0:
                                    progress.progress(count / total,
                                                     text=f"Testing {count}/{total}...")

                                trades = run_backtest(opt_ticker, opt_strat, bars,
                                                      sa, ta, tra, mh)
                                if not trades:
                                    continue

                                df_t = pd.DataFrame(trades)
                                wr = len(df_t[df_t["pnl_pct"] > 0]) / len(df_t) * 100
                                total_pnl = df_t["pnl_pct"].sum()
                                n_trades = len(df_t)

                                fitness = 0.3 * wr + 0.4 * max(total_pnl, 0) + 0.3 * min(n_trades, 20)

                                results.append({
                                    "stop_atr": sa, "target_atr": ta,
                                    "trail_atr": tra, "max_hold": mh,
                                    "trades": n_trades, "win_rate": round(wr, 1),
                                    "total_pnl": round(total_pnl, 2),
                                    "fitness": round(fitness, 2),
                                })

                progress.empty()

                if results:
                    df = pd.DataFrame(results).sort_values("fitness", ascending=False)
                    st.success(f"Tested {count} combinations, {len(df)} produced trades")

                    # Top 5
                    st.subheader("Top 5 Parameter Sets")
                    top5 = df.head(5)
                    st.dataframe(top5.style.format({
                        "win_rate": "{:.1f}%", "total_pnl": "{:+.2f}%", "fitness": "{:.1f}"
                    }), use_container_width=True, hide_index=True)

                    # Best result detail
                    best = df.iloc[0]
                    st.info(f"**Best:** Stop ATR={best['stop_atr']}, Target ATR={best['target_atr']}, "
                            f"Trail ATR={best['trail_atr']}, Max Hold={best['max_hold']}d → "
                            f"Win Rate: {best['win_rate']:.0f}%, Total P&L: {best['total_pnl']:+.1f}%")

                    # Save settings
                    if st.button("💾 Save Best Settings", key="opt_save"):
                        os.makedirs(SETTINGS_DIR, exist_ok=True)
                        # Convert ATR to % (approximate with last price)
                        last_price = bars[-1]["c"] if bars else 100
                        tr_vals = []
                        for j in range(max(1, len(bars)-10), len(bars)):
                            tr_vals.append(max(bars[j]["h"]-bars[j]["l"],
                                              abs(bars[j]["h"]-bars[j-1]["c"]),
                                              abs(bars[j]["l"]-bars[j-1]["c"])))
                        avg_atr = np.mean(tr_vals) if tr_vals else 1

                        settings = {
                            "strategy": opt_strat,
                            "stop_pct": round(best["stop_atr"] * avg_atr / last_price * 100, 2),
                            "target1_pct": round(best["target_atr"] * avg_atr / last_price * 100, 2),
                            "target2_pct": round(best["target_atr"] * 1.6 * avg_atr / last_price * 100, 2),
                            "trail_pct": round(best["trail_atr"] * avg_atr / last_price * 100, 2),
                            "max_hold_days": int(best["max_hold"]),
                            "optimized_at": datetime.now().isoformat(),
                            "fitness": best["fitness"],
                            "win_rate": best["win_rate"],
                        }

                        spath = os.path.join(SETTINGS_DIR, f"{opt_ticker}.json")
                        with open(spath, "w") as f:
                            json.dump(settings, f, indent=2)
                        st.success(f"Saved to {spath}")
                else:
                    st.warning("No parameter combinations produced trades.")

            except Exception as e:
                st.error(f"Optimizer error: {e}")


# ═══════════════════════════════════════════════════════════════════════
# BATCH PLAYBOOK
# ═══════════════════════════════════════════════════════════════════════
with tab_batch:
    st.subheader("Batch Playbook Generator")
    st.caption("Tests every watchlist ticker across all strategies. Picks the best fit for each.")

    watchlist_tickers = [
        "NVDA", "AMD", "META", "GOOGL", "AAPL", "MSFT", "AMZN", "TSLA",
        "JPM", "GS", "CVX", "XOM", "LLY", "UNH", "CAT", "DE", "GE", "BA",
        "V", "MA", "COST", "HD", "CRM", "ORCL", "AVGO", "NFLX",
    ]

    include_etfs = st.checkbox("Include Sector ETFs", value=True)
    if include_etfs:
        watchlist_tickers += list(["XLE", "XLF", "XLK", "XLV", "XLI", "XLP",
                                   "XLY", "XLB", "XLU", "XLRE", "XLC"])

    batch_days = st.slider("Lookback (days)", 60, 365, 120, key="batch_days")

    if st.button("🚀 Generate Playbook", use_container_width=True, type="primary", key="batch_run"):
        results = []
        progress = st.progress(0, text="Generating playbook...")
        total = len(watchlist_tickers) * len(STRATEGIES)
        count = 0

        for ticker in watchlist_tickers:
            try:
                bars = fetch_bars(ticker, batch_days)
                if len(bars) < 30:
                    count += len(STRATEGIES)
                    continue

                best_fitness = -1
                best_strat = "swing"
                best_wr = 0
                best_pnl = 0
                best_trades = 0

                for strat in STRATEGIES:
                    count += 1
                    if count % 10 == 0:
                        progress.progress(min(count / total, 1.0),
                                         text=f"Testing {ticker} / {strat}...")

                    trades = run_backtest(ticker, strat, bars)
                    if not trades:
                        continue

                    df_t = pd.DataFrame(trades)
                    wr = len(df_t[df_t["pnl_pct"] > 0]) / len(df_t) * 100
                    total_pnl = df_t["pnl_pct"].sum()
                    n = len(df_t)

                    fitness = 0.3 * wr + 0.4 * max(total_pnl, 0) + 0.3 * min(n, 20)

                    if fitness > best_fitness:
                        best_fitness = fitness
                        best_strat = strat
                        best_wr = wr
                        best_pnl = total_pnl
                        best_trades = n

                tier = 1 if best_fitness >= 40 else 2 if best_fitness >= 20 else 3

                results.append({
                    "Ticker": ticker,
                    "Strategy": best_strat,
                    "Tier": tier,
                    "Win Rate": round(best_wr, 1),
                    "Total P&L": round(best_pnl, 2),
                    "Trades": best_trades,
                    "Fitness": round(best_fitness, 1),
                })
            except Exception:
                count += len(STRATEGIES)
                continue

        progress.empty()

        if results:
            df = pd.DataFrame(results).sort_values("Fitness", ascending=False)

            # Summary
            t1 = len(df[df["Tier"] == 1])
            t2 = len(df[df["Tier"] == 2])
            t3 = len(df[df["Tier"] == 3])

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Tickers", len(df))
            c2.metric("Tier 1 ⭐", t1)
            c3.metric("Tier 2 🔵", t2)
            c4.metric("Tier 3 ⚪", t3)

            # Color tier
            def tier_color(val):
                if val == 1: return "background-color: rgba(34,197,94,0.3)"
                if val == 2: return "background-color: rgba(59,130,246,0.2)"
                return "background-color: rgba(107,114,128,0.2)"

            def pnl_color(val):
                if isinstance(val, (int, float)):
                    return "color: #22c55e" if val > 0 else "color: #ef4444" if val < 0 else ""
                return ""

            styled = df.style.format({
                "Win Rate": "{:.0f}%", "Total P&L": "{:+.1f}%", "Fitness": "{:.1f}",
            }).map(tier_color, subset=["Tier"]).map(pnl_color, subset=["Total P&L"])

            st.dataframe(styled, use_container_width=True, hide_index=True, height=500)

            # Save playbook
            if st.button("💾 Save Playbook", key="batch_save"):
                os.makedirs("data", exist_ok=True)
                playbook = {}
                for _, row in df.iterrows():
                    playbook[row["Ticker"]] = {
                        "strategy": row["Strategy"],
                        "tier": int(row["Tier"]),
                        "win_rate": row["Win Rate"],
                        "fitness": row["Fitness"],
                    }
                with open(PLAYBOOK_FILE, "w") as f:
                    json.dump(playbook, f, indent=2)
                st.success(f"Saved playbook: {PLAYBOOK_FILE}")

                # Also save CSV
                fname = f"logs/playbook_{datetime.now().strftime('%Y%m%d')}.csv"
                df.to_csv(fname, index=False)
                st.success(f"CSV backup: {fname}")
        else:
            st.warning("No results generated. Check API connection.")
