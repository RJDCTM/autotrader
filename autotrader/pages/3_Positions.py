"""
3_Positions.py — Position Management
Trailing stops, alerts, position monitoring with visual phase indicators.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import os, sys, json
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import check_connection

STOPS_FILE = "logs/trailing_stops.json"
SETTINGS_DIR = "settings"

PHASE_COLORS = {
    "INITIAL": "#6b7280", "T1_HIT": "#3b82f6",
    "T2_HIT": "#22c55e", "RUNAWAY": "#f59e0b",
}
PHASE_PROGRESS = {"INITIAL": 0.25, "T1_HIT": 0.50, "T2_HIT": 0.75, "RUNAWAY": 1.0}

st.title("🎯 Position Management")

broker = check_connection()
positions = broker.get_positions()

# ── Trailing Stops ───────────────────────────────────────────────────────
tab_stops, tab_alerts, tab_init = st.tabs(["📊 Trailing Stops", "🔔 Alerts", "➕ New Position"])

with tab_stops:
    # Load stops
    stops = {}
    if os.path.exists(STOPS_FILE):
        with open(STOPS_FILE) as f:
            stops = json.load(f)

    if not stops:
        st.info("No trailing stops configured. Use the '➕ New Position' tab to add one.")
    else:
        # Update all button
        if st.button("🔄 Update All Stops with Live Prices", use_container_width=True, type="primary"):
            updated = 0
            for ticker in list(stops.keys()):
                price = broker.get_latest_price(ticker)
                if price is None:
                    continue

                pos = stops[ticker]
                entry = pos["entry"]
                old_stop = pos["stop"]
                old_phase = pos["phase"]
                config = pos.get("config", {})

                if price > pos.get("highest_price", entry):
                    pos["highest_price"] = price

                highest = pos["highest_price"]
                new_stop = old_stop
                new_phase = old_phase

                # Phase transitions
                if old_phase == "INITIAL" and price >= pos.get("t1_target", entry * 1.03):
                    new_phase = "T1_HIT"
                    new_stop = round(entry * (1 + config.get("t1_trail", 0.002)), 2)
                if new_phase == "T1_HIT" and price >= pos.get("t2_target", entry * 1.06):
                    new_phase = "T2_HIT"
                    gain = highest - entry
                    new_stop = round(entry + gain * config.get("t2_trail", 0.50), 2)
                if new_phase == "T2_HIT" and price >= pos.get("runaway_target", entry * 1.12):
                    new_phase = "RUNAWAY"
                    gain = highest - entry
                    new_stop = round(entry + gain * config.get("runaway_trail", 0.70), 2)

                # Trail within phase
                if new_phase in ("T2_HIT", "RUNAWAY"):
                    trail_pct = config.get("runaway_trail" if new_phase == "RUNAWAY" else "t2_trail", 0.50)
                    gain = highest - entry
                    trail_stop = round(entry + gain * trail_pct, 2)
                    new_stop = max(new_stop, trail_stop)

                new_stop = max(new_stop, old_stop)  # Never lower
                pos["stop"] = new_stop
                pos["phase"] = new_phase
                pos["last_updated"] = datetime.now().isoformat()
                stops[ticker] = pos
                updated += 1

            with open(STOPS_FILE, "w") as f:
                json.dump(stops, f, indent=2)
            st.success(f"Updated {updated} positions")
            st.rerun()

        # Display each position
        for ticker, pos in sorted(stops.items()):
            entry = pos["entry"]
            stop = pos["stop"]
            phase = pos["phase"]
            highest = pos.get("highest_price", entry)

            # Get live price
            live = broker.get_latest_price(ticker)
            current = live if live else highest
            pnl_pct = (current - entry) / entry * 100
            risk_pct = (stop - entry) / entry * 100

            with st.container():
                # Header row with phase badge
                phase_color = PHASE_COLORS.get(phase, "#6b7280")
                st.markdown(f"""
                <div style="display:flex; align-items:center; gap:12px; margin-bottom:4px;">
                    <span style="font-size:1.3rem; font-weight:700;">{ticker}</span>
                    <span style="background:{phase_color}; color:white; padding:2px 10px;
                                 border-radius:12px; font-size:0.8rem; font-weight:600;">{phase}</span>
                    <span style="color:{'#22c55e' if pnl_pct > 0 else '#ef4444'};
                                 font-weight:600;">{pnl_pct:+.1f}%</span>
                </div>
                """, unsafe_allow_html=True)

                # Progress bar showing phase
                st.progress(PHASE_PROGRESS.get(phase, 0.25),
                           text=f"INITIAL → T1_HIT → T2_HIT → RUNAWAY")

                # Key levels
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("Entry", f"${entry:.2f}")
                c2.metric("Current", f"${current:.2f}")
                c3.metric("Stop", f"${stop:.2f}")
                c4.metric("Highest", f"${highest:.2f}")
                c5.metric("Risk from Entry", f"{risk_pct:+.1f}%")

                # Visual price levels
                t1 = pos.get("t1_target", entry * 1.03)
                t2 = pos.get("t2_target", entry * 1.06)
                runaway = pos.get("runaway_target", entry * 1.12)

                fig = go.Figure()
                # Price range
                all_levels = [stop, entry, current, t1, t2, runaway, highest]
                y_min = min(all_levels) * 0.99
                y_max = max(all_levels) * 1.01

                fig.add_hline(y=stop, line_dash="dash", line_color="#ef4444",
                             annotation_text=f"Stop: ${stop:.2f}")
                fig.add_hline(y=entry, line_dash="dot", line_color="#6b7280",
                             annotation_text=f"Entry: ${entry:.2f}")
                fig.add_hline(y=t1, line_dash="dot", line_color="#3b82f6",
                             annotation_text=f"T1: ${t1:.2f}")
                fig.add_hline(y=t2, line_dash="dot", line_color="#22c55e",
                             annotation_text=f"T2: ${t2:.2f}")
                fig.add_hline(y=runaway, line_dash="dot", line_color="#f59e0b",
                             annotation_text=f"Runaway: ${runaway:.2f}")

                # Current price marker
                fig.add_trace(go.Scatter(
                    x=["Current"], y=[current],
                    mode="markers+text", marker=dict(size=14, color="#8b5cf6"),
                    text=[f"${current:.2f}"], textposition="top center",
                    name="Current Price"
                ))

                fig.update_layout(
                    height=200, template="plotly_dark",
                    margin=dict(l=20, r=120, t=10, b=20),
                    yaxis=dict(range=[y_min, y_max]),
                    showlegend=False, xaxis=dict(visible=False),
                )
                st.plotly_chart(fig, use_container_width=True)
                st.divider()

with tab_alerts:
    st.subheader("Position Alerts")

    if not positions:
        st.info("No open positions to monitor.")
    else:
        alerts = []
        for p in positions:
            ticker = p.ticker
            pnl_pct = p.unrealized_pnl_pct

            # Load settings
            settings = {"stop_pct": 5, "target1_pct": 4, "target2_pct": 8}
            spath = os.path.join(SETTINGS_DIR, f"{ticker}.json")
            if os.path.exists(spath):
                with open(spath) as f:
                    settings = json.load(f)

            stop_pct = settings.get("stop_pct", 5)
            t1_pct = settings.get("target1_pct", 4)
            t2_pct = settings.get("target2_pct", 8)

            if pnl_pct <= -stop_pct:
                alerts.append(("🔴", ticker, f"STOP HIT — P&L {pnl_pct:+.1f}% (stop: -{stop_pct}%)", "error"))
            elif pnl_pct <= -(stop_pct * 0.7):
                alerts.append(("🟡", ticker, f"NEAR STOP — P&L {pnl_pct:+.1f}%", "warning"))
            elif pnl_pct >= t2_pct:
                alerts.append(("🎯", ticker, f"TARGET 2 HIT — P&L {pnl_pct:+.1f}% (T2: +{t2_pct}%)", "success"))
            elif pnl_pct >= t1_pct:
                alerts.append(("🎯", ticker, f"TARGET 1 HIT — P&L {pnl_pct:+.1f}% (T1: +{t1_pct}%)", "info"))
            elif pnl_pct > 12:
                alerts.append(("⚡", ticker, f"OVEREXTENDED — P&L {pnl_pct:+.1f}%", "warning"))

        if alerts:
            for icon, ticker, msg, level in alerts:
                getattr(st, level)(f"{icon} **{ticker}**: {msg}")
        else:
            st.success(f"✅ All {len(positions)} positions within normal parameters.")

        # Position summary table
        st.subheader("Position Summary")
        rows = []
        for p in sorted(positions, key=lambda x: x.unrealized_pnl_pct, reverse=True):
            settings = {"stop_pct": 5, "target1_pct": 4, "target2_pct": 8}
            spath = os.path.join(SETTINGS_DIR, f"{p.ticker}.json")
            if os.path.exists(spath):
                with open(spath) as f:
                    settings = json.load(f)

            status = "✅ OK"
            if p.unrealized_pnl_pct <= -settings.get("stop_pct", 5):
                status = "⛔ STOP"
            elif p.unrealized_pnl_pct >= settings.get("target2_pct", 8):
                status = "🎯 T2"
            elif p.unrealized_pnl_pct >= settings.get("target1_pct", 4):
                status = "🎯 T1"

            rows.append({
                "Ticker": p.ticker, "P&L %": p.unrealized_pnl_pct,
                "Stop": -settings.get("stop_pct", 5),
                "T1": settings.get("target1_pct", 4),
                "T2": settings.get("target2_pct", 8),
                "Status": status,
            })

        df = pd.DataFrame(rows)
        st.dataframe(df.style.format({"P&L %": "{:+.1f}%", "Stop": "{:+.1f}%",
                                       "T1": "+{:.1f}%", "T2": "+{:.1f}%"}),
                     use_container_width=True, hide_index=True)


with tab_init:
    st.subheader("Initialize Trailing Stop")

    strategies = ["swing", "momentum_breakout", "mean_reversion", "sector_etf", "earnings_run"]

    col1, col2, col3 = st.columns(3)
    with col1:
        new_ticker = st.text_input("Ticker", "XLE", key="init_ticker").upper()
    with col2:
        new_entry = st.number_input("Entry Price", min_value=0.01, value=54.33, step=0.01, key="init_entry")
    with col3:
        new_strategy = st.selectbox("Strategy", strategies, key="init_strat")

    if st.button("✅ Initialize Trailing Stop", type="primary"):
        from trailing_stop import PHASE_CONFIGS
        config = PHASE_CONFIGS.get(new_strategy, PHASE_CONFIGS["swing"])

        stop_price = round(new_entry * (1 - config["initial_stop_pct"] / 100), 2)
        t1 = round(new_entry * (1 + config["t1_pct"] / 100), 2)
        t2 = round(new_entry * (1 + config["t2_pct"] / 100), 2)
        t2_gain = t2 - new_entry
        runaway = round(new_entry + config["runaway_trigger_mult"] * t2_gain, 2)

        stops = {}
        if os.path.exists(STOPS_FILE):
            with open(STOPS_FILE) as f:
                stops = json.load(f)

        stops[new_ticker] = {
            "entry": new_entry, "stop": stop_price, "phase": "INITIAL",
            "strategy": new_strategy,
            "t1_target": t1, "t2_target": t2, "runaway_target": runaway,
            "highest_price": new_entry, "config": config,
            "initialized_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
        }

        os.makedirs("logs", exist_ok=True)
        with open(STOPS_FILE, "w") as f:
            json.dump(stops, f, indent=2)

        st.success(f"✅ {new_ticker} initialized!")
        st.info(f"Entry: ${new_entry:.2f} | Stop: ${stop_price:.2f} | "
                f"T1: ${t1:.2f} | T2: ${t2:.2f} | Runaway: ${runaway:.2f}")
        st.rerun()
