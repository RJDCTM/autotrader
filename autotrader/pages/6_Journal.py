"""
6_Journal.py — Trade Journal & Performance
Track psychology, review performance, generate reports.
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

JOURNAL_FILE = "logs/journal.csv"
TRADE_LOG = "logs/trade_log.csv"
EQUITY_LOG = "logs/equity_snapshots.csv"

st.title("📝 Journal & Performance")

tab_journal, tab_performance, tab_report = st.tabs(["📝 Journal Entry", "📊 Performance", "📄 Reports"])


# ═══════════════════════════════════════════════════════════════════════
# JOURNAL ENTRY
# ═══════════════════════════════════════════════════════════════════════
with tab_journal:
    st.subheader("Daily Journal Entry")

    col1, col2, col3 = st.columns(3)
    with col1:
        mood = st.slider("Mood", 1, 10, 7, key="j_mood",
                         help="1 = terrible, 10 = excellent")
    with col2:
        confidence = st.slider("Confidence", 1, 10, 7, key="j_conf",
                              help="How confident are you in today's decisions?")
    with col3:
        market_read = st.slider("Market Read", 1, 10, 6, key="j_market",
                               help="How well did you read the market today?")

    col4, col5 = st.columns(2)
    with col4:
        trades_today = st.number_input("Trades Executed", 0, 50, 0, key="j_trades")
    with col5:
        followed_plan = st.radio("Followed Plan?", ["Yes", "Mostly", "No"],
                                 horizontal=True, key="j_plan")

    mistakes = st.text_area("Mistakes / What went wrong", key="j_mistakes",
                           placeholder="e.g., Chased a gap up, didn't wait for pullback...")
    lessons = st.text_area("Lessons / What went right", key="j_lessons",
                          placeholder="e.g., Waited for confirmation before entry, proper sizing...")
    notes = st.text_area("Additional Notes", key="j_notes",
                        placeholder="Market observations, upcoming catalysts, general thoughts...")

    if st.button("💾 Save Journal Entry", use_container_width=True, type="primary"):
        os.makedirs("logs", exist_ok=True)
        entry = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "time": datetime.now().strftime("%H:%M"),
            "mood": mood, "confidence": confidence, "market_read": market_read,
            "trades_today": trades_today,
            "followed_plan": followed_plan,
            "mistakes": mistakes.replace("\n", " "),
            "lessons": lessons.replace("\n", " "),
            "notes": notes.replace("\n", " "),
        }

        if os.path.exists(JOURNAL_FILE):
            df = pd.read_csv(JOURNAL_FILE)
            df = pd.concat([df, pd.DataFrame([entry])], ignore_index=True)
        else:
            df = pd.DataFrame([entry])
        df.to_csv(JOURNAL_FILE, index=False)
        st.success("📝 Journal entry saved!")
        st.balloons()

    # Show insights from past entries
    st.divider()
    st.subheader("📊 Journal Insights")

    if os.path.exists(JOURNAL_FILE):
        jdf = pd.read_csv(JOURNAL_FILE)
        if not jdf.empty:
            n = len(jdf)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Entries", n)
            c2.metric("Avg Mood", f"{jdf['mood'].mean():.1f}/10")
            c3.metric("Avg Confidence", f"{jdf['confidence'].mean():.1f}/10")
            c4.metric("Avg Market Read", f"{jdf['market_read'].mean():.1f}/10")

            # Plan adherence
            if "followed_plan" in jdf.columns:
                yes_count = len(jdf[jdf["followed_plan"] == "Yes"])
                adherence = yes_count / n * 100
                st.metric("Plan Adherence", f"{adherence:.0f}%")

            # Mood over time
            if n >= 3:
                jdf["date"] = pd.to_datetime(jdf["date"])
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=jdf["date"], y=jdf["mood"],
                                         name="Mood", line=dict(color="#3b82f6")))
                fig.add_trace(go.Scatter(x=jdf["date"], y=jdf["confidence"],
                                         name="Confidence", line=dict(color="#22c55e")))
                fig.add_trace(go.Scatter(x=jdf["date"], y=jdf["market_read"],
                                         name="Market Read", line=dict(color="#f59e0b")))
                fig.update_layout(title="Trading Psychology Over Time", height=300,
                                 template="plotly_dark",
                                 margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig, use_container_width=True)

            # Recent mistakes
            if "mistakes" in jdf.columns:
                recent_mistakes = jdf[jdf["mistakes"].notna() & (jdf["mistakes"] != "")].tail(5)
                if not recent_mistakes.empty:
                    st.subheader("Recent Mistakes")
                    for _, row in recent_mistakes.iterrows():
                        st.caption(f"**{row['date']}**: {row['mistakes']}")

            # Recent lessons
            if "lessons" in jdf.columns:
                recent_lessons = jdf[jdf["lessons"].notna() & (jdf["lessons"] != "")].tail(5)
                if not recent_lessons.empty:
                    st.subheader("Recent Lessons")
                    for _, row in recent_lessons.iterrows():
                        st.caption(f"**{row['date']}**: {row['lessons']}")

            # Full history
            with st.expander("Full Journal History"):
                st.dataframe(jdf.sort_values("date", ascending=False),
                           use_container_width=True, hide_index=True)
    else:
        st.info("No journal entries yet. Start logging to build insights over time.")
        st.caption("Consistency matters — even a quick daily entry helps identify patterns "
                   "in your trading psychology.")


# ═══════════════════════════════════════════════════════════════════════
# PERFORMANCE
# ═══════════════════════════════════════════════════════════════════════
with tab_performance:
    st.subheader("Trade Performance Analytics")

    if os.path.exists(TRADE_LOG):
        tdf = pd.read_csv(TRADE_LOG)

        if not tdf.empty:
            # Normalize column names
            col_map = {}
            for c in tdf.columns:
                cl = c.lower()
                if "ticker" in cl or "symbol" in cl: col_map[c] = "ticker"
                elif "pnl" in cl and "pct" in cl: col_map[c] = "pnl_pct"
                elif "pnl" in cl: col_map[c] = "pnl"
                elif "side" in cl or "action" in cl: col_map[c] = "side"
                elif "date" in cl and "entry" in cl: col_map[c] = "entry_date"
                elif "date" in cl and "exit" in cl: col_map[c] = "exit_date"
                elif "strat" in cl: col_map[c] = "strategy"
            tdf = tdf.rename(columns=col_map)

            # Key metrics
            if "pnl_pct" in tdf.columns:
                tdf["pnl_pct"] = pd.to_numeric(tdf["pnl_pct"], errors="coerce")
                wins = tdf[tdf["pnl_pct"] > 0]
                losses = tdf[tdf["pnl_pct"] <= 0]
                n = len(tdf)
                win_rate = len(wins) / n * 100 if n else 0

                m1, m2, m3, m4, m5 = st.columns(5)
                m1.metric("Total Trades", n)
                m2.metric("Win Rate", f"{win_rate:.0f}%")
                m3.metric("Total P&L", f"{tdf['pnl_pct'].sum():+.1f}%")
                m4.metric("Avg Win", f"{wins['pnl_pct'].mean():+.1f}%" if len(wins) else "—")
                m5.metric("Avg Loss", f"{losses['pnl_pct'].mean():+.1f}%" if len(losses) else "—")

                # Profit factor
                gross_win = wins["pnl_pct"].sum() if len(wins) else 0
                gross_loss = abs(losses["pnl_pct"].sum()) if len(losses) else 1
                pf = gross_win / gross_loss if gross_loss > 0 else float("inf")

                m6, m7 = st.columns(2)
                m6.metric("Profit Factor", f"{pf:.2f}")
                m7.metric("Expectancy", f"{tdf['pnl_pct'].mean():+.2f}% / trade")

                # P&L histogram
                fig = px.histogram(tdf, x="pnl_pct", nbins=20,
                                  title="P&L Distribution",
                                  color_discrete_sequence=["#3b82f6"])
                fig.add_vline(x=0, line_dash="dash", line_color="white")
                fig.update_layout(template="plotly_dark", height=300)
                st.plotly_chart(fig, use_container_width=True)

                # Cumulative P&L
                tdf_sorted = tdf.sort_index()
                tdf_sorted["cum_pnl"] = tdf_sorted["pnl_pct"].cumsum()

                fig2 = go.Figure()
                fig2.add_trace(go.Scatter(
                    y=tdf_sorted["cum_pnl"], mode="lines",
                    line=dict(color="#22c55e", width=2),
                    fill="tozeroy", fillcolor="rgba(34,197,94,0.1)",
                ))
                fig2.add_hline(y=0, line_dash="dash", line_color="#6b7280")
                fig2.update_layout(title="Cumulative P&L (%)", height=300,
                                  template="plotly_dark",
                                  margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig2, use_container_width=True)

                # By strategy
                if "strategy" in tdf.columns:
                    st.subheader("Performance by Strategy")
                    strat_perf = tdf.groupby("strategy").agg(
                        trades=("pnl_pct", "count"),
                        win_rate=("pnl_pct", lambda x: (x > 0).sum() / len(x) * 100),
                        total_pnl=("pnl_pct", "sum"),
                        avg_pnl=("pnl_pct", "mean"),
                    ).round(2).reset_index()

                    st.dataframe(strat_perf.style.format({
                        "win_rate": "{:.0f}%", "total_pnl": "{:+.1f}%", "avg_pnl": "{:+.2f}%"
                    }), use_container_width=True, hide_index=True)

            # Full log
            with st.expander("Full Trade Log"):
                st.dataframe(tdf, use_container_width=True, hide_index=True)
        else:
            st.info("Trade log is empty.")
    else:
        st.info("No trade log found at `logs/trade_log.csv`.")
        st.caption("Trades are logged automatically when you execute through the system. "
                   "You can also manually create the CSV with columns: "
                   "ticker, entry_date, exit_date, entry_price, exit_price, pnl_pct, strategy")

    # Equity snapshots
    st.divider()
    st.subheader("Equity History")
    if os.path.exists(EQUITY_LOG):
        edf = pd.read_csv(EQUITY_LOG)
        if not edf.empty and "equity" in edf.columns:
            edf["date"] = pd.to_datetime(edf["date"])

            start_eq = edf["equity"].iloc[0]
            end_eq = edf["equity"].iloc[-1]
            total_ret = (end_eq - start_eq) / start_eq * 100

            # Max drawdown
            running_max = edf["equity"].expanding().max()
            drawdown = (edf["equity"] - running_max) / running_max * 100
            max_dd = drawdown.min()

            c1, c2, c3 = st.columns(3)
            c1.metric("Start Equity", f"${start_eq:,.0f}")
            c2.metric("Current Equity", f"${end_eq:,.0f}", f"{total_ret:+.1f}%")
            c3.metric("Max Drawdown", f"{max_dd:.1f}%")

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=edf["date"], y=edf["equity"],
                mode="lines+markers", name="Equity",
                line=dict(color="#3b82f6", width=2),
            ))
            fig.update_layout(height=300, template="plotly_dark",
                             margin=dict(l=20, r=20, t=10, b=20))
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("No equity snapshots yet. Use Dashboard → Save Snapshot to track over time.")


# ═══════════════════════════════════════════════════════════════════════
# REPORTS
# ═══════════════════════════════════════════════════════════════════════
with tab_report:
    st.subheader("Generate Report")

    report_type = st.radio("Report Type", ["Daily", "Weekly"], horizontal=True)

    if st.button("📄 Generate Report", use_container_width=True, type="primary", key="gen_report"):
        broker = check_connection()
        acct = broker.get_account()
        positions = broker.get_positions()

        st.markdown(f"## {'Daily' if report_type == 'Daily' else 'Weekly'} Report — "
                   f"{datetime.now().strftime('%Y-%m-%d')}")

        # Account
        st.markdown(f"**Equity:** ${acct.equity:,.2f} | "
                   f"**Cash:** ${acct.cash:,.2f} | "
                   f"**Daily P&L:** ${acct.daily_pnl:+,.2f} ({acct.daily_pnl_pct:+.2f}%)")

        # Positions summary
        st.markdown(f"**Open Positions:** {len(positions)}")
        if positions:
            total_pnl = sum(p.unrealized_pnl for p in positions)
            winners = sum(1 for p in positions if p.unrealized_pnl > 0)
            st.markdown(f"**Unrealized P&L:** ${total_pnl:+,.2f} | "
                       f"**Winners:** {winners}/{len(positions)}")

        # Trade activity
        if os.path.exists(TRADE_LOG):
            tdf = pd.read_csv(TRADE_LOG)
            if not tdf.empty:
                # Filter by period
                for c in tdf.columns:
                    if "date" in c.lower():
                        tdf[c] = pd.to_datetime(tdf[c], errors="coerce")
                        break

                days_back = 1 if report_type == "Daily" else 7
                cutoff = datetime.now() - timedelta(days=days_back)

                # Try to filter
                date_cols = [c for c in tdf.columns if "date" in c.lower()]
                if date_cols:
                    recent = tdf[tdf[date_cols[0]] >= cutoff]
                    if not recent.empty:
                        st.markdown(f"**Trades this period:** {len(recent)}")

        # Journal notes
        if os.path.exists(JOURNAL_FILE):
            jdf = pd.read_csv(JOURNAL_FILE)
            if not jdf.empty:
                jdf["date"] = pd.to_datetime(jdf["date"])
                days_back = 1 if report_type == "Daily" else 7
                cutoff = datetime.now() - timedelta(days=days_back)
                recent_j = jdf[jdf["date"] >= cutoff]
                if not recent_j.empty:
                    st.markdown("### Journal Notes")
                    for _, row in recent_j.iterrows():
                        if pd.notna(row.get("notes")) and str(row["notes"]).strip():
                            st.caption(f"**{row['date'].strftime('%Y-%m-%d')}**: {row['notes']}")

        st.divider()
        st.caption("For a downloadable report, use `python report.py --save` from the CLI.")
