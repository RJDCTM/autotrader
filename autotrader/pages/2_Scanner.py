"""
2_Scanner.py — Morning Scanner + Gap Scanner
Scan watchlist for setups, detect gaps, filter and sort interactively.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import os, sys, json
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import check_connection

WATCHLIST_FILE = "data/watchlist.csv"
STOPS_FILE = "logs/trailing_stops.json"

DEFAULT_TICKERS = [
    "NVDA", "AMD", "META", "GOOGL", "AAPL", "MSFT", "AMZN", "TSLA",
    "JPM", "GS", "CVX", "XOM", "SLB", "LLY", "UNH", "CAT", "DE",
    "GE", "BA", "V", "MA", "COST", "WMT", "HD", "CRM", "ORCL",
    "AVGO", "MU", "QCOM", "NFLX",
]
ETF_TICKERS = [
    "XLE", "XLF", "XLK", "XLV", "XLI", "XLP", "XLY", "XLB",
    "XLU", "XLRE", "XLC", "SPY", "QQQ", "IWM",
]

st.title("🔍 Scanner")

broker = check_connection()

# ── Scan Controls ────────────────────────────────────────────────────────
tab_morning, tab_gap = st.tabs(["⚡ Morning Scanner", "📊 Gap Scanner"])

# ═══════════════════════════════════════════════════════════════════════
# MORNING SCANNER
# ═══════════════════════════════════════════════════════════════════════
with tab_morning:
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        scan_scope = st.radio("Scan scope", ["Watchlist", "Watchlist + ETFs", "ETFs Only", "Custom"],
                              horizontal=True, key="ms_scope")
    with col2:
        min_score = st.slider("Min Score", 0, 100, 50, key="ms_min")
    with col3:
        top_n = st.number_input("Show top N", 5, 100, 30, key="ms_top")

    custom_tickers = ""
    if scan_scope == "Custom":
        custom_tickers = st.text_input("Tickers (comma-separated)", "NVDA, AMD, META, XLE")

    run_scan = st.button("🚀 Run Morning Scan", use_container_width=True, type="primary", key="ms_run")

    if run_scan:
        # Build ticker list
        if scan_scope == "Custom":
            tickers = [t.strip().upper() for t in custom_tickers.split(",") if t.strip()]
        elif scan_scope == "ETFs Only":
            tickers = ETF_TICKERS
        elif scan_scope == "Watchlist + ETFs":
            tickers = DEFAULT_TICKERS + ETF_TICKERS
        else:
            if os.path.exists(WATCHLIST_FILE):
                wl = pd.read_csv(WATCHLIST_FILE)
                tickers = wl.iloc[:, 0].dropna().str.strip().str.upper().tolist()
            else:
                tickers = DEFAULT_TICKERS

        tickers = list(set(tickers))
        progress = st.progress(0, text="Scanning...")
        results = []

        for i, ticker in enumerate(tickers):
            progress.progress((i + 1) / len(tickers), text=f"Scanning {ticker}...")
            try:
                end = datetime.now()
                start = end - timedelta(days=40)
                bars = broker.api.get_bars(ticker, "1Day",
                                           start=start.strftime("%Y-%m-%d"),
                                           end=end.strftime("%Y-%m-%d"), limit=30)
                if not bars or len(bars) < 5:
                    continue

                closes = [b.c for b in bars]
                volumes = [b.v for b in bars]
                highs = [b.h for b in bars]
                lows = [b.l for b in bars]

                current = closes[-1]
                prev = closes[-2] if len(closes) > 1 else current
                sma5 = np.mean(closes[-5:]) if len(closes) >= 5 else current
                sma20 = np.mean(closes[-20:]) if len(closes) >= 20 else current

                # ATR
                tr = []
                for j in range(1, min(11, len(closes))):
                    tr.append(max(highs[j] - lows[j],
                                  abs(highs[j] - closes[j-1]),
                                  abs(lows[j] - closes[j-1])))
                atr = np.mean(tr) if tr else 1

                # RSI
                if len(closes) >= 15:
                    deltas = np.diff(closes[-15:])
                    gains = np.mean(np.where(deltas > 0, deltas, 0))
                    losses_val = np.mean(np.where(deltas < 0, -deltas, 0))
                    rsi = 100 - (100 / (1 + gains / (losses_val + 1e-10)))
                else:
                    rsi = 50

                vol_ratio = volumes[-1] / np.mean(volumes[-20:]) if len(volumes) >= 20 else 1.0
                change = (current - prev) / prev * 100
                perf_5d = (current - closes[-5]) / closes[-5] * 100 if len(closes) >= 5 else 0
                dist_sma20 = (current - sma20) / sma20 * 100

                # Score momentum
                m_score = 0
                if current > sma5 > sma20: m_score += 30
                if perf_5d > 2: m_score += min(20, perf_5d * 4)
                if 50 < rsi < 75: m_score += 20
                if vol_ratio > 1.2: m_score += min(15, (vol_ratio - 1) * 15)
                if change > 0.5: m_score += min(15, change * 5)
                m_score = min(100, max(0, m_score))

                # Score swing
                s_score = 0
                if current > sma20: s_score += 25
                if abs(dist_sma20) < 3: s_score += 20
                if 40 < rsi < 60: s_score += 25
                if 0 < perf_5d < 5: s_score += 15
                if vol_ratio > 0.8: s_score += 15
                s_score = min(100, max(0, s_score))

                # Score reversion
                r_score = 0
                if dist_sma20 < -3: r_score += min(30, abs(dist_sma20) * 5)
                if rsi < 35: r_score += 25
                elif rsi < 45: r_score += 15
                if change < -1: r_score += min(20, abs(change) * 5)
                if vol_ratio > 1.5: r_score += 15
                if perf_5d < -5: r_score += 10
                r_score = min(100, max(0, r_score))

                scores = {"momentum": m_score, "swing": s_score, "reversion": r_score}
                best_strat = max(scores, key=scores.get)

                results.append({
                    "Ticker": ticker,
                    "Price": round(current, 2),
                    "Chg%": round(change, 2),
                    "5d%": round(perf_5d, 2),
                    "RSI": round(rsi, 1),
                    "VolR": round(vol_ratio, 2),
                    "ATR": round(atr, 2),
                    "SMA20 Dist": round(dist_sma20, 2),
                    "Mom Score": round(m_score, 1),
                    "Swing Score": round(s_score, 1),
                    "Rev Score": round(r_score, 1),
                    "Best Score": round(scores[best_strat], 1),
                    "Strategy": best_strat.title(),
                })
            except Exception:
                continue

        progress.empty()

        if results:
            df = pd.DataFrame(results)
            df = df[df["Best Score"] >= min_score]
            df = df.sort_values("Best Score", ascending=False).head(top_n).reset_index(drop=True)

            # Store in session for other pages
            st.session_state["last_scan"] = df
            st.session_state["scan_time"] = datetime.now().strftime("%H:%M")

            # Display
            st.success(f"Found {len(df)} signals above {min_score} score")

            # Strategy distribution
            c1, c2, c3 = st.columns(3)
            mom_count = len(df[df["Strategy"] == "Momentum"])
            swi_count = len(df[df["Strategy"] == "Swing"])
            rev_count = len(df[df["Strategy"] == "Reversion"])
            c1.metric("⚡ Momentum", mom_count)
            c2.metric("🔄 Swing", swi_count)
            c3.metric("📉 Reversion", rev_count)

            # Color scoring
            def score_color(val):
                if isinstance(val, (int, float)):
                    if val >= 75: return "background-color: rgba(34,197,94,0.3)"
                    if val >= 60: return "background-color: rgba(234,179,8,0.2)"
                    if val >= 40: return "background-color: rgba(249,115,22,0.2)"
                return ""

            def pnl_color(val):
                if isinstance(val, (int, float)):
                    return "color: #22c55e" if val > 0 else "color: #ef4444" if val < 0 else ""
                return ""

            styled = df.style.format({
                "Price": "${:.2f}", "Chg%": "{:+.2f}%", "5d%": "{:+.2f}%",
                "SMA20 Dist": "{:+.1f}%", "ATR": "${:.2f}",
            }).map(score_color, subset=["Best Score", "Mom Score", "Swing Score", "Rev Score"]
            ).map(pnl_color, subset=["Chg%", "5d%"])

            st.dataframe(styled, use_container_width=True, hide_index=True, height=500)

            # Save button
            if st.button("💾 Save Scan to CSV"):
                os.makedirs("logs", exist_ok=True)
                fname = f"logs/morning_scan_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
                df.to_csv(fname, index=False)
                st.success(f"Saved: {fname}")
        else:
            st.warning("No results. Market may be closed or no tickers matched criteria.")

    # Show last scan if available
    elif "last_scan" in st.session_state:
        st.caption(f"Last scan: {st.session_state.get('scan_time', '?')}")
        st.dataframe(st.session_state["last_scan"], use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════
# GAP SCANNER
# ═══════════════════════════════════════════════════════════════════════
with tab_gap:
    gap_scope = st.radio("Scope", ["All (Stocks + ETFs)", "ETFs Only", "Custom"],
                          horizontal=True, key="gap_scope")

    custom_gap = ""
    if gap_scope == "Custom":
        custom_gap = st.text_input("Tickers (comma-separated)", "XLE, NVDA, AAPL", key="gap_custom")

    run_gap = st.button("📊 Run Gap Scan", use_container_width=True, type="primary", key="gap_run")

    if run_gap:
        if gap_scope == "Custom":
            tickers = [t.strip().upper() for t in custom_gap.split(",") if t.strip()]
        elif gap_scope == "ETFs Only":
            tickers = ETF_TICKERS
        else:
            tickers = DEFAULT_TICKERS + ETF_TICKERS

        # Get held tickers
        held = set()
        if os.path.exists(STOPS_FILE):
            with open(STOPS_FILE) as f:
                held = set(json.load(f).keys())

        progress = st.progress(0, text="Scanning gaps...")
        results = []

        for i, ticker in enumerate(tickers):
            progress.progress((i + 1) / len(tickers), text=f"Checking {ticker}...")
            try:
                end = datetime.now()
                start = end - timedelta(days=20)
                bars = broker.api.get_bars(ticker, "1Day",
                                           start=start.strftime("%Y-%m-%d"),
                                           end=end.strftime("%Y-%m-%d"), limit=15)
                if not bars or len(bars) < 2:
                    continue

                data = [{"o": b.o, "h": b.h, "l": b.l, "c": b.c, "v": b.v} for b in bars]
                prev_close = data[-2]["c"]
                today_open = data[-1]["o"]
                current = data[-1]["c"]

                # ATR
                tr = []
                for j in range(1, min(11, len(data))):
                    tr.append(max(data[j]["h"] - data[j]["l"],
                                  abs(data[j]["h"] - data[j-1]["c"]),
                                  abs(data[j]["l"] - data[j-1]["c"])))
                atr = np.mean(tr) if tr else 1

                gap_pct = (current - prev_close) / prev_close * 100
                gap_atr = abs(gap_pct / 100 * prev_close) / atr if atr > 0 else 0

                direction = "⬆️ UP" if gap_pct > 0.1 else "⬇️ DOWN" if gap_pct < -0.1 else "➡️ FLAT"
                abs_gap = abs(gap_pct)
                severity = ("EXTREME" if abs_gap >= 5 else "LARGE" if abs_gap >= 3 else
                           "MODERATE" if abs_gap >= 1.5 else "SMALL" if abs_gap >= 0.5 else "NONE")

                is_held = ticker in held

                # Action recommendation
                if is_held:
                    if gap_pct < -3: action = "⛔ CHECK STOPS"
                    elif gap_pct < -1.5: action = "👀 Monitor stops"
                    elif gap_pct > 3: action = "💰 Scale out into strength"
                    elif gap_pct > 1.5: action = "📈 Trail stop up"
                    else: action = "✅ Hold"
                else:
                    if gap_pct < -3: action = "🔄 Mean reversion bounce"
                    elif gap_pct < -1.5: action = "👀 Watch for support"
                    elif gap_pct > 3: action = "🚫 DO NOT CHASE"
                    elif gap_pct > 1.5: action = "📊 Breakout if vol confirms"
                    else: action = "👀 Watch"

                results.append({
                    "Ticker": ("⭐ " if is_held else "") + ticker,
                    "Prev Close": round(prev_close, 2),
                    "Open": round(today_open, 2),
                    "Current": round(current, 2),
                    "Gap%": round(gap_pct, 2),
                    "Gap ATR": round(gap_atr, 1),
                    "Direction": direction,
                    "Severity": severity,
                    "Held": "YES" if is_held else "",
                    "Action": action,
                })
            except Exception:
                continue

        progress.empty()

        if results:
            df = pd.DataFrame(results)
            df = df.sort_values("Gap%", key=abs, ascending=False)

            # Market breadth
            up = sum(1 for r in results if r["Gap%"] > 0.1)
            down = sum(1 for r in results if r["Gap%"] < -0.1)
            flat = len(results) - up - down
            avg_gap = np.mean([r["Gap%"] for r in results])

            b1, b2, b3, b4 = st.columns(4)
            b1.metric("Gapping Up", up)
            b2.metric("Gapping Down", down)
            b3.metric("Flat", flat)
            b4.metric("Avg Gap", f"{avg_gap:+.2f}%")

            if avg_gap > 0.5:
                st.success("🟢 Bullish open — favor momentum trades")
            elif avg_gap < -0.5:
                st.error("🔴 Bearish open — watch stops, favor reversion")
            else:
                st.info("➡️ Neutral open — follow scanner signals")

            def gap_color(val):
                if isinstance(val, (int, float)):
                    return "color: #22c55e" if val > 0 else "color: #ef4444" if val < 0 else ""
                return ""

            styled = df.style.format({
                "Prev Close": "${:.2f}", "Open": "${:.2f}", "Current": "${:.2f}",
                "Gap%": "{:+.2f}%",
            }).map(gap_color, subset=["Gap%"])

            st.dataframe(styled, use_container_width=True, hide_index=True, height=500)

            # Save
            if st.button("💾 Save Gap Scan"):
                os.makedirs("logs", exist_ok=True)
                fname = f"logs/gap_scan_{datetime.now().strftime('%Y%m%d')}.csv"
                df.to_csv(fname, index=False)
                st.success(f"Saved: {fname}")
        else:
            st.warning("No gap data. Market may be closed.")
