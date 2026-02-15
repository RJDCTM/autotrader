#!/usr/bin/env python3
"""
app.py — RD AutoTrader Streamlit App
Launch: streamlit run app.py
"""

import streamlit as st
import os
import sys

# Ensure we can import our modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Page Config (must be first Streamlit call) ──────────────────────────
st.set_page_config(
    page_title="RD AutoTrader",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Shared CSS ───────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Tighten spacing */
    .block-container { padding-top: 1.5rem; padding-bottom: 1rem; }
    /* Metric cards */
    [data-testid="stMetricValue"] { font-size: 1.4rem; }
    /* Sidebar */
    [data-testid="stSidebar"] { min-width: 220px; }
    /* Tables */
    .stDataFrame { font-size: 0.85rem; }
    /* Green/red P&L */
    .pnl-pos { color: #22c55e; font-weight: 600; }
    .pnl-neg { color: #ef4444; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# ── Broker Connection (cached across reruns) ─────────────────────────────
@st.cache_resource(show_spinner="Connecting to Alpaca...")
def get_broker():
    """Create broker connection once, reuse across pages."""
    try:
        from core.config import load_config
        from core.broker import AlpacaBroker
        cfg = load_config()
        broker = AlpacaBroker(cfg.broker)
        return broker, None
    except Exception as e:
        return None, str(e)


def check_connection():
    """Verify broker connection. Returns broker or shows error."""
    broker, error = get_broker()
    if error:
        st.error(f"⚠️ Broker connection failed: {error}")
        st.info("Add your keys in Settings → Secrets (TOML format)")
        st.code('ALPACA_API_KEY = "your_key"\nALPACA_SECRET_KEY = "your_secret"\nALPACA_BASE_URL = "https://paper-api.alpaca.markets"', language="toml")
        st.stop()
    return broker

def check_connection():
    """Verify broker connection. Returns broker or shows error."""
    broker, error = get_broker()
    if error:
        st.error(f"⚠️ Broker connection failed: {error}")
        st.info("Check your `.env` file has valid ALPACA_API_KEY and ALPACA_SECRET_KEY")
        st.stop()
    return broker


# ── Landing Page ─────────────────────────────────────────────────────────
def main():
    broker = check_connection()
    acct = broker.get_account()
    clock = broker.get_clock()

    # Header
    col1, col2 = st.columns([3, 1])
    with col1:
        st.title("📈 RD AutoTrader")
    with col2:
        status = "🟢 Market Open" if clock["is_open"] else "🔴 Market Closed"
        st.markdown(f"### {status}")

    # Key metrics row
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Equity", f"${acct.equity:,.2f}", f"{acct.daily_pnl_pct:+.2f}% today")
    m2.metric("Cash", f"${acct.cash:,.2f}")
    m3.metric("Buying Power", f"${acct.buying_power:,.2f}")
    m4.metric("Daily P&L", f"${acct.daily_pnl:+,.2f}",
              delta_color="normal" if acct.daily_pnl >= 0 else "inverse")

    # Circuit breaker warning
    if acct.daily_pnl_pct <= -3.0:
        st.error("⛔ CIRCUIT BREAKER — Daily loss exceeds -3%. No new entries.")
    elif acct.daily_pnl_pct <= -2.0:
        st.warning("⚠️ Daily loss exceeds -2%. Reduce position sizing.")

    st.divider()

    # Positions
    positions = broker.get_positions()
    st.subheader(f"Open Positions ({len(positions)})")

    if positions:
        import pandas as pd
        rows = []
        for p in positions:
            rows.append({
                "Ticker": p.ticker,
                "Side": p.side.title(),
                "Qty": int(p.qty),
                "Entry": p.avg_entry_price,
                "Current": p.current_price,
                "Mkt Value": p.market_value,
                "P&L $": p.unrealized_pnl,
                "P&L %": p.unrealized_pnl_pct,
            })
        df = pd.DataFrame(rows)

        # Style the dataframe
        def color_pnl(val):
            if isinstance(val, (int, float)):
                return "color: #22c55e" if val > 0 else "color: #ef4444" if val < 0 else ""
            return ""

        styled = df.style.format({
            "Entry": "${:.2f}", "Current": "${:.2f}",
            "Mkt Value": "${:,.2f}", "P&L $": "${:+,.2f}", "P&L %": "{:+.1f}%"
        }).map(color_pnl, subset=["P&L $", "P&L %"])

        st.dataframe(styled, use_container_width=True, hide_index=True)

        total_pnl = sum(p.unrealized_pnl for p in positions)
        total_value = sum(p.market_value for p in positions)
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Market Value", f"${total_value:,.2f}")
        c2.metric("Total Unrealized P&L", f"${total_pnl:+,.2f}")
        c3.metric("Positions", len(positions))
    else:
        st.info("No open positions.")

    # Open orders
    orders = broker.get_open_orders()
    if orders:
        st.subheader(f"Open Orders ({len(orders)})")
        for o in orders:
            st.text(str(o))

    # Navigation hint
    st.divider()
    st.caption("Use the sidebar to navigate: Dashboard → Scanner → Positions → Analysis → Backtest → Journal")


if __name__ == "__main__":
    main()
