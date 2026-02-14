"""
4_Analysis.py — Market Analysis
Market regime detection, sector momentum rankings, signal quality review.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import os, sys, glob
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import check_connection

SECTOR_ETFS = {
    "XLE": "Energy", "XLF": "Financials", "XLK": "Technology",
    "XLV": "Healthcare", "XLI": "Industrials", "XLP": "Cons Staples",
    "XLY": "Cons Disc", "XLB": "Materials", "XLU": "Utilities",
    "XLRE": "Real Estate", "XLC": "Communication",
}

st.title("📈 Market Analysis")

broker = check_connection()

tab_regime, tab_sectors, tab_quality = st.tabs(["🌡️ Market Regime", "📊 Sector Rankings", "🎯 Signal Quality"])

# ═══════════════════════════════════════════════════════════════════════
# MARKET REGIME
# ═══════════════════════════════════════════════════════════════════════
with tab_regime:
    if st.button("🔄 Analyze Market Regime", use_container_width=True, type="primary", key="regime_run"):
        with st.spinner("Analyzing SPY..."):
            try:
                end = datetime.now()
                start = end - timedelta(days=220)
                bars = broker.api.get_bars("SPY", "1Day",
                                           start=start.strftime("%Y-%m-%d"),
                                           end=end.strftime("%Y-%m-%d"), limit=200)
                closes = [b.c for b in bars]
                dates = [b.t for b in bars]

                current = closes[-1]
                sma20 = np.mean(closes[-20:])
                sma50 = np.mean(closes[-50:]) if len(closes) >= 50 else sma20
                sma200 = np.mean(closes[-200:]) if len(closes) >= 200 else sma50

                perf_5d = (current - closes[-5]) / closes[-5] * 100 if len(closes) >= 5 else 0
                perf_20d = (current - closes[-20]) / closes[-20] * 100 if len(closes) >= 20 else 0
                perf_50d = (current - closes[-50]) / closes[-50] * 100 if len(closes) >= 50 else 0

                # Volatility
                rets = np.diff(np.log(closes[-21:]))
                vol_20d = np.std(rets) * np.sqrt(252) * 100

                # RSI
                deltas = np.diff(closes[-15:])
                gains = np.mean(np.where(deltas > 0, deltas, 0))
                losses_val = np.mean(np.where(deltas < 0, -deltas, 0))
                rsi = 100 - (100 / (1 + gains / (losses_val + 1e-10)))

                # Classify
                if current > sma20 > sma50 > sma200 and perf_20d > 3 and vol_20d < 20:
                    regime = "STRONG_BULL"
                elif current > sma50 > sma200 and perf_20d > 0:
                    regime = "BULL"
                elif current < sma50 and current < sma200 and perf_20d < -5:
                    regime = "CRISIS" if vol_20d > 30 else "BEAR"
                elif current < sma50 and perf_20d < -3:
                    regime = "BEAR"
                else:
                    regime = "NEUTRAL"

                # Regime display
                regime_config = {
                    "STRONG_BULL": {"icon": "🚀", "color": "#22c55e", "sizing": "100%",
                                    "strategies": "Momentum, Sector ETF", "stops": "Wide trailing"},
                    "BULL": {"icon": "📈", "color": "#3b82f6", "sizing": "100%",
                             "strategies": "All active", "stops": "Standard"},
                    "NEUTRAL": {"icon": "➡️", "color": "#f59e0b", "sizing": "75%",
                                "strategies": "Swing, Reversion", "stops": "Tighter"},
                    "BEAR": {"icon": "📉", "color": "#ef4444", "sizing": "50%",
                             "strategies": "Reversion only", "stops": "Very tight"},
                    "CRISIS": {"icon": "🔥", "color": "#991b1b", "sizing": "25% / CASH",
                               "strategies": "No new longs", "stops": "Flatten all"},
                }
                rc = regime_config.get(regime, regime_config["NEUTRAL"])

                st.markdown(f"""
                <div style="text-align:center; padding:20px; background:{rc['color']}22;
                            border:2px solid {rc['color']}; border-radius:12px; margin-bottom:20px;">
                    <div style="font-size:3rem;">{rc['icon']}</div>
                    <div style="font-size:2rem; font-weight:700; color:{rc['color']};">{regime}</div>
                </div>
                """, unsafe_allow_html=True)

                # Metrics
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("SPY", f"${current:.2f}", f"{perf_5d:+.1f}% (5d)")
                m2.metric("20d Perf", f"{perf_20d:+.1f}%")
                m3.metric("Volatility (20d)", f"{vol_20d:.1f}%")
                m4.metric("RSI", f"{rsi:.0f}")

                # Strategy adjustments
                st.subheader("Strategy Adjustments")
                a1, a2, a3 = st.columns(3)
                a1.info(f"**Sizing:** {rc['sizing']}")
                a2.info(f"**Strategies:** {rc['strategies']}")
                a3.info(f"**Stops:** {rc['stops']}")

                # MA stacking visual
                st.subheader("MA Structure")
                ma_data = {
                    "Level": ["Price", "SMA 20", "SMA 50", "SMA 200"],
                    "Value": [current, round(sma20, 2), round(sma50, 2), round(sma200, 2)],
                }
                ma_df = pd.DataFrame(ma_data)
                colors = ["#8b5cf6", "#3b82f6", "#22c55e", "#f59e0b"]
                stacked = "✅" if sma20 > sma50 > sma200 else "❌"
                st.caption(f"MA Stacking: {stacked} | Price > SMA20: {'✅' if current > sma20 else '❌'}")

                fig = go.Figure(go.Bar(
                    x=ma_df["Level"], y=ma_df["Value"],
                    marker_color=colors, text=[f"${v:.2f}" for v in ma_df["Value"]],
                    textposition="outside",
                ))
                fig.update_layout(height=300, template="plotly_dark",
                                 margin=dict(l=20, r=20, t=20, b=20), yaxis_title="Price ($)")
                st.plotly_chart(fig, use_container_width=True)

                # SPY chart with MAs
                st.subheader("SPY Daily Chart")
                chart_closes = closes[-60:]
                chart_dates = dates[-60:]

                fig2 = go.Figure()
                fig2.add_trace(go.Scatter(x=chart_dates, y=chart_closes, name="SPY",
                                          line=dict(color="#3b82f6", width=2)))
                # SMA20 overlay
                if len(closes) >= 80:
                    sma20_vals = [np.mean(closes[i-20:i]) for i in range(len(closes)-60, len(closes))]
                    fig2.add_trace(go.Scatter(x=chart_dates, y=sma20_vals, name="SMA20",
                                              line=dict(color="#f59e0b", width=1, dash="dash")))
                if len(closes) >= 110:
                    sma50_vals = [np.mean(closes[i-50:i]) for i in range(len(closes)-60, len(closes))]
                    fig2.add_trace(go.Scatter(x=chart_dates, y=sma50_vals, name="SMA50",
                                              line=dict(color="#22c55e", width=1, dash="dot")))

                fig2.update_layout(height=350, template="plotly_dark",
                                  margin=dict(l=20, r=20, t=10, b=20))
                st.plotly_chart(fig2, use_container_width=True)

            except Exception as e:
                st.error(f"Error analyzing regime: {e}")


# ═══════════════════════════════════════════════════════════════════════
# SECTOR RANKINGS
# ═══════════════════════════════════════════════════════════════════════
with tab_sectors:
    if st.button("📊 Rank Sectors", use_container_width=True, type="primary", key="sector_run"):
        progress = st.progress(0, text="Ranking sectors...")
        results = []
        all_tickers = list(SECTOR_ETFS.keys()) + ["SPY", "QQQ", "IWM"]

        for i, ticker in enumerate(all_tickers):
            progress.progress((i + 1) / len(all_tickers), text=f"Analyzing {ticker}...")
            try:
                end = datetime.now()
                start = end - timedelta(days=100)
                bars = broker.api.get_bars(ticker, "1Day",
                                           start=start.strftime("%Y-%m-%d"),
                                           end=end.strftime("%Y-%m-%d"), limit=90)
                if not bars:
                    continue
                closes = [b.c for b in bars]
                current = closes[-1]

                p1w = (current - closes[-5]) / closes[-5] * 100 if len(closes) >= 5 else 0
                p1m = (current - closes[-21]) / closes[-21] * 100 if len(closes) >= 21 else 0
                p3m = (current - closes[0]) / closes[0] * 100

                mom = p1w * 0.4 + p1m * 0.35 + p3m * 0.25
                results.append({
                    "Ticker": ticker,
                    "Sector": SECTOR_ETFS.get(ticker, "Benchmark"),
                    "Price": round(current, 2),
                    "1W%": round(p1w, 2),
                    "1M%": round(p1m, 2),
                    "3M%": round(p3m, 2),
                    "Score": round(mom, 2),
                    "Type": "Benchmark" if ticker in ["SPY", "QQQ", "IWM"] else "Sector",
                })
            except Exception:
                continue

        progress.empty()

        if results:
            df = pd.DataFrame(results)
            sectors = df[df["Type"] == "Sector"].sort_values("Score", ascending=False).reset_index(drop=True)
            benchmarks = df[df["Type"] == "Benchmark"]

            # Top/bottom callout
            if not sectors.empty:
                top = sectors.iloc[0]
                bot = sectors.iloc[-1]
                st.success(f"🟢 **FAVOR:** {top['Ticker']} ({top['Sector']}) — Score: {top['Score']:+.1f}")
                st.error(f"🔴 **AVOID:** {bot['Ticker']} ({bot['Sector']}) — Score: {bot['Score']:+.1f}")

            # Bar chart
            fig = go.Figure(go.Bar(
                x=sectors["Ticker"], y=sectors["Score"],
                marker_color=["#22c55e" if v > 0 else "#ef4444" for v in sectors["Score"]],
                text=[f"{v:+.1f}" for v in sectors["Score"]], textposition="outside",
            ))
            fig.update_layout(title="Sector Momentum Score", height=350,
                             template="plotly_dark", margin=dict(l=20, r=20, t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)

            # Full table
            def pnl_color(val):
                if isinstance(val, (int, float)):
                    return "color: #22c55e" if val > 0 else "color: #ef4444" if val < 0 else ""
                return ""

            st.subheader("Sector Detail")
            styled = sectors.style.format({
                "Price": "${:.2f}", "1W%": "{:+.2f}%", "1M%": "{:+.2f}%",
                "3M%": "{:+.2f}%", "Score": "{:+.2f}",
            }).map(pnl_color, subset=["1W%", "1M%", "3M%", "Score"])
            st.dataframe(styled, use_container_width=True, hide_index=True)

            if not benchmarks.empty:
                st.subheader("Benchmarks")
                st.dataframe(benchmarks.style.format({
                    "Price": "${:.2f}", "1W%": "{:+.2f}%", "1M%": "{:+.2f}%",
                    "3M%": "{:+.2f}%", "Score": "{:+.2f}",
                }), use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════
# SIGNAL QUALITY
# ═══════════════════════════════════════════════════════════════════════
with tab_quality:
    st.subheader("Signal Quality Analysis")

    # Load all scan files
    scan_files = glob.glob("logs/morning_scan_*.csv")
    if not scan_files:
        st.info("No scan data yet. Run the Scanner and save results to build up data.")
        st.caption("Signal quality improves over weeks as you accumulate scan → trade data.")
    else:
        frames = []
        for f in scan_files:
            try:
                df = pd.read_csv(f)
                df["scan_file"] = os.path.basename(f)
                frames.append(df)
            except:
                continue

        if frames:
            all_scans = pd.concat(frames, ignore_index=True)

            st.metric("Scan Files", len(scan_files))
            st.metric("Total Signals", len(all_scans))

            # Find score column
            score_col = None
            for col in all_scans.columns:
                if "best" in col.lower() and "score" in col.lower():
                    score_col = col
                    break
                elif "score" in col.lower() and "best" not in col.lower():
                    if score_col is None:
                        score_col = col

            if score_col:
                # Score distribution
                fig = px.histogram(all_scans, x=score_col, nbins=20,
                                  title="Signal Score Distribution",
                                  color_discrete_sequence=["#3b82f6"])
                fig.update_layout(template="plotly_dark", height=300)
                st.plotly_chart(fig, use_container_width=True)

            # Strategy distribution
            strat_col = None
            for col in all_scans.columns:
                if "strateg" in col.lower() or "routed" in col.lower():
                    strat_col = col
                    break

            if strat_col:
                strat_counts = all_scans[strat_col].value_counts()
                fig = px.pie(values=strat_counts.values, names=strat_counts.index,
                            title="Signal Distribution by Strategy", hole=0.3)
                fig.update_layout(template="plotly_dark", height=300)
                st.plotly_chart(fig, use_container_width=True)

            # Most signaled tickers
            ticker_col = None
            for col in all_scans.columns:
                if col.lower() in ("ticker", "symbol"):
                    ticker_col = col
                    break

            if ticker_col:
                st.subheader("Most Frequent Signals")
                freq = all_scans[ticker_col].value_counts().head(15)
                fig = go.Figure(go.Bar(
                    x=freq.index, y=freq.values,
                    marker_color="#8b5cf6",
                    text=freq.values, textposition="outside",
                ))
                fig.update_layout(title="Top 15 Most Signaled Tickers",
                                 height=300, template="plotly_dark",
                                 margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig, use_container_width=True)
