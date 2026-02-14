"""
1_Dashboard.py — Command Center Dashboard
Real-time account overview, position heatmap, sector allocation, equity tracking.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import os, sys, json
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import check_connection

EQUITY_LOG = "logs/equity_snapshots.csv"
STOPS_FILE = "logs/trailing_stops.json"

SECTOR_MAP = {
    "XLE": "Energy", "CVX": "Energy", "XOM": "Energy", "SLB": "Energy",
    "XLF": "Financials", "JPM": "Financials", "GS": "Financials", "V": "Financials", "MA": "Financials",
    "XLK": "Technology", "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology",
    "AMD": "Technology", "AVGO": "Technology", "MU": "Technology", "QCOM": "Technology",
    "META": "Technology", "GOOGL": "Technology", "CRM": "Technology", "ORCL": "Technology",
    "XLV": "Healthcare", "LLY": "Healthcare", "UNH": "Healthcare",
    "XLI": "Industrials", "CAT": "Industrials", "DE": "Industrials", "GE": "Industrials", "BA": "Industrials",
    "XLP": "Cons Staples", "COST": "Cons Staples", "WMT": "Cons Staples",
    "XLY": "Cons Disc", "AMZN": "Cons Disc", "TSLA": "Cons Disc", "HD": "Cons Disc", "NFLX": "Cons Disc",
    "XLB": "Materials", "XLU": "Utilities", "XLRE": "Real Estate", "XLC": "Communication",
}

st.title("📊 Dashboard")

broker = check_connection()
acct = broker.get_account()
clock = broker.get_clock()
positions = broker.get_positions()

# ── Top Metrics ──────────────────────────────────────────────────────────
status_color = "🟢" if clock["is_open"] else "🔴"
st.caption(f"{status_color} Market {'Open' if clock['is_open'] else 'Closed'} — "
           f"Last updated: {datetime.now().strftime('%H:%M:%S')}")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Equity", f"${acct.equity:,.0f}", f"{acct.daily_pnl_pct:+.2f}%")
m2.metric("Cash", f"${acct.cash:,.0f}")
m3.metric("Buying Power", f"${acct.buying_power:,.0f}")
m4.metric("Daily P&L", f"${acct.daily_pnl:+,.0f}")
m5.metric("Positions", len(positions))

if acct.daily_pnl_pct <= -3.0:
    st.error("⛔ CIRCUIT BREAKER ACTIVE — Daily loss > 3%")
elif acct.daily_pnl_pct <= -2.0:
    st.warning("⚠️ Caution — Daily loss > 2%, reduce sizing")

# ── Save Equity Snapshot Button ──────────────────────────────────────────
col_snap, col_refresh = st.columns([1, 4])
with col_snap:
    if st.button("📸 Save Snapshot", use_container_width=True):
        os.makedirs("logs", exist_ok=True)
        row = {"date": datetime.now().strftime("%Y-%m-%d"),
               "time": datetime.now().strftime("%H:%M"),
               "equity": acct.equity, "cash": acct.cash,
               "positions": len(positions)}
        if os.path.exists(EQUITY_LOG):
            df = pd.read_csv(EQUITY_LOG)
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        else:
            df = pd.DataFrame([row])
        df.to_csv(EQUITY_LOG, index=False)
        st.success("Snapshot saved!")

with col_refresh:
    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_resource.clear()
        st.rerun()

st.divider()

# ── Position Details ─────────────────────────────────────────────────────
if positions:
    tab_table, tab_chart, tab_sectors = st.tabs(["📋 Positions", "📊 P&L Chart", "🥧 Sectors"])

    with tab_table:
        rows = []
        for p in sorted(positions, key=lambda x: x.unrealized_pnl, reverse=True):
            # Load trailing stop info if available
            phase = "—"
            stop = "—"
            if os.path.exists(STOPS_FILE):
                with open(STOPS_FILE) as f:
                    stops = json.load(f)
                if p.ticker in stops:
                    phase = stops[p.ticker].get("phase", "—")
                    stop = f"${stops[p.ticker].get('stop', 0):.2f}"

            rows.append({
                "Ticker": p.ticker,
                "Side": p.side.title(),
                "Qty": int(p.qty),
                "Entry": p.avg_entry_price,
                "Current": p.current_price,
                "Value": p.market_value,
                "P&L $": p.unrealized_pnl,
                "P&L %": p.unrealized_pnl_pct,
                "Sector": SECTOR_MAP.get(p.ticker, "Other"),
                "Trail Phase": phase,
                "Stop": stop,
            })

        df = pd.DataFrame(rows)

        def color_pnl(val):
            if isinstance(val, (int, float)):
                return "color: #22c55e" if val > 0 else "color: #ef4444" if val < 0 else ""
            return ""

        styled = df.style.format({
            "Entry": "${:.2f}", "Current": "${:.2f}", "Value": "${:,.0f}",
            "P&L $": "${:+,.2f}", "P&L %": "{:+.1f}%"
        }).map(color_pnl, subset=["P&L $", "P&L %"])

        st.dataframe(styled, use_container_width=True, hide_index=True, height=400)

        # Totals
        total_pnl = sum(p.unrealized_pnl for p in positions)
        total_val = sum(p.market_value for p in positions)
        winners = sum(1 for p in positions if p.unrealized_pnl > 0)
        losers = len(positions) - winners
        st.caption(f"Total Value: ${total_val:,.0f} | P&L: ${total_pnl:+,.0f} | "
                   f"Winners: {winners} | Losers: {losers}")

    with tab_chart:
        # Horizontal bar chart of P&L by position
        chart_df = pd.DataFrame([
            {"Ticker": p.ticker, "P&L %": p.unrealized_pnl_pct, "P&L $": p.unrealized_pnl}
            for p in sorted(positions, key=lambda x: x.unrealized_pnl_pct)
        ])

        colors = ["#22c55e" if v > 0 else "#ef4444" for v in chart_df["P&L %"]]

        fig = go.Figure(go.Bar(
            x=chart_df["P&L %"], y=chart_df["Ticker"],
            orientation="h", marker_color=colors,
            text=[f"{v:+.1f}%" for v in chart_df["P&L %"]],
            textposition="outside",
        ))
        fig.update_layout(
            title="Position P&L (%)", height=max(300, len(positions) * 40),
            xaxis_title="P&L %", yaxis_title="",
            margin=dict(l=20, r=20, t=40, b=20),
            template="plotly_dark",
        )
        st.plotly_chart(fig, use_container_width=True)

    with tab_sectors:
        # Sector allocation pie
        sector_data = {}
        for p in positions:
            s = SECTOR_MAP.get(p.ticker, "Other")
            sector_data[s] = sector_data.get(s, 0) + p.market_value

        if sector_data:
            fig = px.pie(
                values=list(sector_data.values()),
                names=list(sector_data.keys()),
                title="Sector Allocation",
                hole=0.4,
            )
            fig.update_layout(template="plotly_dark", height=400)
            st.plotly_chart(fig, use_container_width=True)

            # Concentration warnings
            for sector, val in sector_data.items():
                pct = val / acct.equity * 100
                if pct > 25:
                    st.warning(f"⚠️ {sector}: {pct:.1f}% of equity (max 25%)")

else:
    st.info("No open positions. Use the Scanner to find setups.")

# ── Equity Curve ─────────────────────────────────────────────────────────
st.divider()
st.subheader("📈 Equity Curve")

if os.path.exists(EQUITY_LOG):
    eq_df = pd.read_csv(EQUITY_LOG)
    if not eq_df.empty and "equity" in eq_df.columns:
        eq_df["date"] = pd.to_datetime(eq_df["date"])
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=eq_df["date"], y=eq_df["equity"],
            mode="lines+markers", name="Equity",
            line=dict(color="#3b82f6", width=2),
            fill="tozeroy", fillcolor="rgba(59,130,246,0.1)",
        ))
        fig.update_layout(
            height=300, template="plotly_dark",
            margin=dict(l=20, r=20, t=10, b=20),
            yaxis_title="Equity ($)",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("No equity data yet. Click 'Save Snapshot' to start tracking.")
else:
    st.caption("No equity data yet. Click 'Save Snapshot' to start tracking.")
