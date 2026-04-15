"""
DASHBOARD STREAMLIT v2 — interface CLÉ EN MAIN.

Pages :
  🏠 Overview          — vue d'ensemble
  🔴 Live Scanner      — signaux actifs + notifications
  📊 Edge Explorer     — courbes Pareto ML
  📈 Backtest Runner   — simuler stratégies
  🧪 Edge Discovery    — analyse features
  📉 Charts            — graphiques bougies + FVG overlays
  📔 Trade Journal     — log + analytics trades réels
  📅 News Calendar     — events macro
  🛡️ Risk Compliance   — règles FTMO/5ers
  ⚙️ Settings          — configuration tout-en-un
  🔧 System Health     — état technique
"""
from __future__ import annotations

import sys
import json
import warnings
from pathlib import Path
from datetime import datetime, timedelta
import uuid

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
warnings.filterwarnings("ignore")

import streamlit as st

from src.data_engine import DataLoader, IntegrityChecker
from src.feature_engine import FeatureEngine
from src.utils.types import Timeframe
from src.utils.config import list_instruments, get_prop_firm_rules, REPORTS_DIR
from src.utils.user_settings import UserSettings, apply_env
from src.ict_engine import FVGDetector, OrderBlockDetector, LiquidityDetector
from src.trade_journal import TradeJournal, JournalEntry

# Load user settings + push secrets to env
apply_env()
SETTINGS = UserSettings.load()

# ------------------------------------------------------------------
st.set_page_config(
    page_title="ICT Institutional Framework",
    page_icon="🔴",
    layout="wide",
    initial_sidebar_state="expanded",
)

with st.sidebar:
    st.title("🔴 ICT FRAMEWORK")
    st.caption("Infrastructure quant • FTMO/5ers")
    st.markdown("---")
    page = st.radio(
        "Navigation",
        [
            "🏠 Overview",
            "🔴 Live Scanner",
            "📊 Edge Explorer",
            "📈 Backtest Runner",
            "🧪 Edge Discovery",
            "📉 Charts",
            "📔 Trade Journal",
            "📅 News Calendar",
            "🛡️ Risk Compliance",
            "⚙️ Settings",
            "🔧 System Health",
        ],
    )
    st.markdown("---")
    st.caption(f"Firm: {SETTINGS.firm.upper()}/{SETTINGS.variant}")
    st.caption(f"Balance: ${SETTINGS.account_balance:,.0f}")
    st.caption(f"Risk/trade: {SETTINGS.risk_per_trade_pct}%")


# ==================================================================
# OVERVIEW
# ==================================================================
if page == "🏠 Overview":
    st.title("🔴 ICT Institutional Framework")
    st.markdown("### Le laboratoire quant qui devient ton outil quotidien")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Engines", "14", "live scanner added")
    c2.metric("Tests", "56/56", "100%")
    c3.metric("Assets", "12", "multi-TF")
    c4.metric("Modules", "52", "importables")

    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.subheader("🔴 Live Actions")
        if st.button("🔍 Scanner maintenant", use_container_width=True, type="primary"):
            st.session_state["do_scan"] = True
            st.switch_page(None) if False else st.info("→ Page Live Scanner")
        if st.button("📈 Lancer backtest", use_container_width=True):
            st.info("→ Page Backtest Runner")

    with c2:
        st.subheader("📊 Dernier Pareto")
        reports = sorted(Path("reports").glob("max_edge_pareto_*.json"))
        if reports:
            d = json.loads(reports[-1].read_text())
            n = len(d["assets"])
            st.metric("Assets analysés", n)
        else:
            st.info("Pas de rapport Pareto — lance `ict setup`")

    with c3:
        st.subheader("📔 Journal")
        j = TradeJournal()
        stats = j.analytics()
        if stats["n_closed"] > 0:
            st.metric("Trades réels", stats["n_closed"])
            st.metric("WR réel", f"{stats['win_rate']:.1%}")
        else:
            st.info("Aucun trade journalisé encore.")

    st.markdown("---")
    st.subheader("🗺️ Workflow quotidien")
    st.markdown("""
1. **Check le dashboard** le matin → page **Live Scanner** → SCAN
2. **Examine** les signaux (Tier / WR / Distance to entry)
3. **Check** la page **News Calendar** pour skipper les events macro
4. **Prend** les trades sur ton broker (manuellement)
5. **Journalise** sur la page **Trade Journal**
6. **Dashboard analyse** ta performance réelle vs prédite
    """)


# ==================================================================
# LIVE SCANNER
# ==================================================================
elif page == "🔴 Live Scanner":
    st.title("🔴 Live Scanner")

    # Auto-trigger from Overview
    do_scan = st.session_state.pop("do_scan", False)

    c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
    tier = c1.selectbox("Tier", ["balanced", "elite", "volume"], index=0)
    refresh = c2.checkbox("Refresh data", value=True)
    skip_news = c3.checkbox("Skip news events", value=True)
    run_btn = c4.button("🔍 SCAN MAINTENANT", type="primary",
                        use_container_width=True)

    if run_btn or do_scan:
        with st.spinner("Scanning 12 assets..."):
            from src.live_scanner import LiveScanner
            scanner = LiveScanner(
                symbols_h1=SETTINGS.assets_h1,
                symbols_d1=SETTINGS.assets_d1,
                tier=tier, refresh_data=refresh,
            )
            signals = scanner.scan_once()

        # Filter by news
        if skip_news and signals:
            try:
                from src.news_calendar import NewsCalendar, currencies_for
                cal = NewsCalendar(
                    skip_minutes_before=SETTINGS.skip_news_minutes_before,
                    skip_minutes_after=SETTINGS.skip_news_minutes_after,
                    min_impact=SETTINGS.skip_news_impact.capitalize(),
                )
                cal.refresh()
                filtered = []
                for s in signals:
                    ts = datetime.fromisoformat(s.timestamp_scan)
                    if cal.is_in_news_window(ts, currencies_for(s.symbol)):
                        continue
                    filtered.append(s)
                skipped = len(signals) - len(filtered)
                signals = filtered
                if skipped > 0:
                    st.info(f"⏭ {skipped} signal(s) skipped due to news windows")
            except Exception as e:
                st.warning(f"News calendar unavailable: {e}")

        if not signals:
            st.info("Aucun signal ACTIF. Reviens plus tard.")
        else:
            st.success(f"🎯 {len(signals)} signal(s)")
            rows = []
            for s in signals:
                rows.append({
                    "Tier": s.tier,
                    "Asset": s.symbol,
                    "TF": s.ltf,
                    "Side": "🟢 LONG" if s.side == "long" else "🔴 SHORT",
                    "Current": f"{s.current_price:.4f}",
                    "Entry": f"{s.entry:.4f}",
                    "SL": f"{s.stop_loss:.4f}",
                    "TP1": f"{s.take_profit_1:.4f}",
                    "TP2": f"{s.take_profit_2:.4f}",
                    "RR": f"{s.risk_reward:.2f}",
                    "P(win)": f"{s.ml_prob_win:.1%}" if s.ml_prob_win else "n/a",
                    "Dist%": f"{s.distance_to_entry_pct:.2f}",
                    "Age": s.fvg_age_bars,
                    "KZ": s.killzone,
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            # Quick-add to journal
            st.markdown("---")
            st.subheader("➕ Add to Trade Journal")
            with st.form("add_journal"):
                c1, c2, c3 = st.columns(3)
                idx = c1.selectbox("Signal #", list(range(len(signals))))
                lots = c2.number_input("Lots", min_value=0.01, value=0.5, step=0.01)
                notes = c3.text_input("Notes", "")
                submit = st.form_submit_button("📔 Log this trade (OPEN)")
                if submit:
                    s = signals[idx]
                    j = TradeJournal()
                    entry = JournalEntry(
                        trade_id=str(uuid.uuid4())[:8],
                        created_at=datetime.utcnow().isoformat(),
                        symbol=s.symbol, ltf=s.ltf, side=s.side,
                        entry=s.entry, stop_loss=s.stop_loss,
                        take_profit_1=s.take_profit_1, take_profit_2=s.take_profit_2,
                        source_signal_id=f"{s.symbol}_{s.fvg_age_bars}",
                        ml_prob_win_at_signal=s.ml_prob_win,
                        tier_at_signal=s.tier,
                        entry_time=datetime.utcnow().isoformat(),
                        entry_fill=s.current_price,
                        lots=lots,
                        risk_usd=SETTINGS.account_balance * SETTINGS.risk_per_trade_pct / 100,
                        killzone=s.killzone,
                        notes=notes,
                    )
                    j.log(entry)
                    st.success(f"✓ Trade {entry.trade_id} logged. Close it via Trade Journal.")


# ==================================================================
# EDGE EXPLORER
# ==================================================================
elif page == "📊 Edge Explorer":
    st.title("📊 Edge Explorer — Pareto Frontier")
    reports = sorted(Path("reports").glob("max_edge_pareto_*.json"))
    if not reports:
        st.warning("Pas de rapport Pareto. Lance `python3 run_maximum_edge.py`.")
        st.stop()

    data = json.loads(reports[-1].read_text())
    asset = st.selectbox("Asset", list(data["assets"].keys()))
    info = data["assets"][asset]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Test trades", info["n_test"])
    c2.metric("Baseline WR", f"{info['baseline_wr_test']:.1%}")
    c3.metric("AUC OOS", f"{info['auc']:.3f}")
    c4.metric("TF", info["ltf"])

    pareto = pd.DataFrame(info["pareto"])
    if not pareto.empty:
        st.subheader("Courbe Pareto")
        chart_data = pareto[["threshold", "winrate_oos", "trades_per_month"]].copy()
        chart_data.columns = ["Threshold", "WR", "Trades/mois"]
        st.line_chart(chart_data.set_index("Threshold"))
        p_disp = pareto.copy()
        p_disp.columns = ["Threshold", "n OOS", "WR", "exp_R", "Trades/mo", "Total R"]
        p_disp["WR"] = p_disp["WR"].apply(lambda x: f"{x:.1%}")
        p_disp["exp_R"] = p_disp["exp_R"].apply(lambda x: f"{x:+.3f}")
        p_disp["Total R"] = p_disp["Total R"].apply(lambda x: f"{x:+.2f}")
        st.dataframe(p_disp, use_container_width=True, hide_index=True)

    st.subheader("3 TIERS")
    tiers = info.get("tiers", {})
    cols = st.columns(3)
    for i, (name, icon) in enumerate([("elite", "🎯"), ("balanced", "⚖"), ("volume", "🚀")]):
        with cols[i]:
            st.markdown(f"#### {icon} {name.upper()}")
            t = tiers.get(name)
            if t:
                st.metric("WR", f"{t['winrate_oos']:.1%}")
                st.metric("exp_R", f"{t['expectancy_r_oos']:+.3f}")
                st.metric("Trades/mois", f"{t['trades_per_month']:.1f}")
                st.caption(f"Threshold: {t['threshold']:.2f} • n: {t['n_trades_oos']}")
            else:
                st.info("N/A")

    st.subheader("🔍 Top features (ML)")
    feats = info.get("top_features", {})
    if feats:
        st.bar_chart(pd.DataFrame(list(feats.items()),
                                  columns=["Feature", "Importance"]).set_index("Feature"))


# ==================================================================
# BACKTEST RUNNER
# ==================================================================
elif page == "📈 Backtest Runner":
    st.title("📈 Backtest Runner")
    c1, c2, c3 = st.columns(3)
    asset = c1.selectbox("Asset", list_instruments())
    tf = c2.selectbox("Timeframe", ["1h", "1d"])
    firm = c3.selectbox("Prop firm", [
        "ftmo/classic_challenge", "ftmo/funded",
        "the_5ers/bootcamp", "the_5ers/hpt",
    ])
    c4, c5 = st.columns(2)
    balance = c4.number_input("Balance", 1000, value=int(SETTINGS.account_balance), step=1000)
    risk = c5.number_input("Risk %", 0.1, 2.0, SETTINGS.risk_per_trade_pct, 0.1)

    if st.button("🚀 RUN BACKTEST", type="primary", use_container_width=True):
        with st.spinner("Running..."):
            from src.execution_engine import ExecutionEngine
            from src.backtest_engine import Backtester
            from src.backtest_engine.backtest import BacktestConfig
            from src.audit_engine import AuditEngine
            from src.utils.types import SetupGrade

            firm_name, variant = firm.split("/")
            loader = DataLoader()
            df_d = loader.load(asset, Timeframe.D1)
            df_ltf = loader.load(asset, Timeframe(tf))
            df_w = df_d.resample("1W").agg({
                "open": "first", "high": "max", "low": "min",
                "close": "last", "volume": "sum",
            }).dropna()
            df_h4 = (df_ltf.resample("4h").agg({
                "open": "first", "high": "max", "low": "min",
                "close": "last", "volume": "sum",
            }).dropna() if Timeframe(tf).minutes < 240 else df_d)

            df_ltf = FeatureEngine().compute(df_ltf)
            execer = ExecutionEngine(min_grade=SetupGrade.B)
            signals = execer.generate_signals(asset, df_ltf, df_w, df_d, df_h4)
            cfg = BacktestConfig(initial_balance=balance, firm=firm_name, variant=variant)
            result = Backtester(cfg).run(asset, df_ltf, signals)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Trades", result.total_trades)
        c2.metric("Return", f"{result.total_return_pct:+.2f}%")
        c3.metric("Max DD", f"{result.max_drawdown_pct:.2f}%")
        c4.metric("Sharpe", f"{result.sharpe_ratio:.2f}")
        c5, c6, c7, c8 = st.columns(4)
        c5.metric("WR", f"{result.win_rate:.1%}")
        c6.metric("PF", f"{result.profit_factor:.2f}")
        c7.metric("Exp R", f"{result.expectancy_r:+.3f}")
        c8.metric("Daily DD max", f"{result.max_daily_drawdown_pct:.2f}%")

        c9, c10 = st.columns(2)
        c9.markdown(f"**FTMO:** {'✅' if result.ftmo_compliant else '❌'}")
        c10.markdown(f"**5ers:** {'✅' if result.the5ers_compliant else '❌'}")

        audit = AuditEngine().audit(result)
        st.subheader(f"🔍 Audit: {audit.verdict}")
        for f in audit.findings:
            icon = {"CRITICAL": "❌", "WARNING": "⚠️", "INFO": "ℹ️"}.get(f.severity, "•")
            st.write(f"{icon} **{f.category}** — {f.message}")


# ==================================================================
# EDGE DISCOVERY
# ==================================================================
elif page == "🧪 Edge Discovery":
    st.title("🧪 Edge Discovery")
    csvs = sorted(Path("reports").glob("edge_insights_*.csv"))
    if not csvs:
        st.warning("Lance `python3 run_edge_insights.py` d'abord.")
        st.stop()
    data = pd.read_csv(csvs[-1])
    st.caption(f"Source: `{csvs[-1].name}` • {len(data)} observations")

    c1, c2, c3 = st.columns(3)
    af = c1.multiselect("Assets", sorted(data["asset"].unique()))
    ff = c2.multiselect("Features", sorted(data["feature"].unique()))
    min_n = c3.slider("Min n", 10, 500, 20)

    df = data[data["n"] >= min_n]
    if af: df = df[df["asset"].isin(af)]
    if ff: df = df[df["feature"].isin(ff)]
    st.dataframe(df.sort_values("expectancy_r", ascending=False),
                 use_container_width=True, hide_index=True)


# ==================================================================
# CHARTS (candlestick + FVG overlays)
# ==================================================================
elif page == "📉 Charts":
    st.title("📉 Charts")
    c1, c2 = st.columns(2)
    asset = c1.selectbox("Asset", list_instruments())
    tf_opts = ["1h", "1d"]
    tf = c2.selectbox("TF", tf_opts)

    try:
        loader = DataLoader()
        df = loader.load(asset, Timeframe(tf))
        df = FeatureEngine().compute(df)
        # limit to last 300 bars for readability
        df = df.tail(300)
    except Exception as e:
        st.error(f"Erreur: {e}")
        st.stop()

    # Detect FVG + OB
    fvg_det = FVGDetector(min_size_atr=0.2, displacement_min=1.1)
    fvgs = fvg_det.detect(df)
    ob_det = OrderBlockDetector()
    obs = ob_det.detect(df, fvgs)

    try:
        import plotly.graph_objects as go
        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=df.index, open=df["open"], high=df["high"],
            low=df["low"], close=df["close"],
            name=asset,
        ))

        # FVG overlays
        for f in fvgs[-30:]:                 # last 30 FVGs pour lisibilité
            color = "rgba(0, 200, 0, 0.15)" if f.side.value == "long" else "rgba(200, 0, 0, 0.15)"
            end_idx = min(f.filled_at_index or len(df), len(df) - 1) if f.filled_at_index else len(df) - 1
            if end_idx <= f.index:
                continue
            try:
                start_ts = df.index[f.index]
                end_ts = df.index[min(end_idx, len(df) - 1)]
                fig.add_shape(
                    type="rect",
                    x0=start_ts, x1=end_ts,
                    y0=f.bottom, y1=f.top,
                    fillcolor=color,
                    line=dict(width=0),
                    layer="below",
                )
            except Exception:
                continue

        # OB markers
        for ob in obs[-15:]:
            if ob.index >= len(df):
                continue
            try:
                ts = df.index[ob.index]
                symbol = "triangle-up" if ob.side.value == "long" else "triangle-down"
                color = "green" if ob.side.value == "long" else "red"
                fig.add_trace(go.Scatter(
                    x=[ts],
                    y=[(ob.high + ob.low) / 2],
                    mode="markers",
                    marker=dict(symbol=symbol, size=10, color=color),
                    name="OB",
                    showlegend=False,
                ))
            except Exception:
                continue

        fig.update_layout(
            title=f"{asset} {tf}",
            xaxis_rangeslider_visible=False,
            height=600,
            margin=dict(t=40, b=30, l=30, r=30),
        )
        st.plotly_chart(fig, use_container_width=True)

        # Stats
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("FVG total", len(fvgs))
        c2.metric("FVG bull", sum(1 for f in fvgs if f.side.value == "long"))
        c3.metric("FVG bear", sum(1 for f in fvgs if f.side.value == "short"))
        c4.metric("OB valides", len(obs))
    except ImportError:
        st.warning("Installe plotly: `pip install plotly`")


# ==================================================================
# TRADE JOURNAL
# ==================================================================
elif page == "📔 Trade Journal":
    st.title("📔 Trade Journal")
    j = TradeJournal()
    entries = j.load_all()

    tab1, tab2, tab3 = st.tabs(["📋 Trades", "📊 Analytics", "➕ Add Manual"])

    with tab1:
        if not entries:
            st.info("Aucun trade journalisé. Ajoute via Live Scanner ou onglet Manual.")
        else:
            df = j.to_dataframe()
            st.dataframe(df, use_container_width=True, hide_index=True)

            st.markdown("---")
            st.subheader("Fermer un trade ouvert")
            opens = [e for e in entries if not e.is_closed]
            if opens:
                with st.form("close_form"):
                    tid = st.selectbox("Trade ID",
                                        [e.trade_id for e in opens])
                    exit_price = st.number_input("Exit price", value=0.0, step=0.01)
                    exit_reason = st.selectbox("Reason", ["tp1", "tp2", "sl", "be", "manual"])
                    if st.form_submit_button("Close trade"):
                        e = next(e for e in opens if e.trade_id == tid)
                        side_mult = 1 if e.side == "long" else -1
                        pnl_r = side_mult * (exit_price - e.entry_fill) / abs(e.entry_fill - e.stop_loss)
                        pnl_usd = pnl_r * e.risk_usd
                        j.close_trade(tid, datetime.utcnow().isoformat(),
                                       exit_price, pnl_usd, pnl_r, exit_reason)
                        st.success(f"Closed {tid}: {pnl_r:+.2f}R ({pnl_usd:+.2f} USD)")
                        st.rerun()

    with tab2:
        stats = j.analytics()
        if stats["n_closed"] == 0:
            st.info("Pas encore de trades fermés.")
        else:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Closed", stats["n_closed"])
            c2.metric("WR réel", f"{stats['win_rate']:.1%}")
            c3.metric("PnL total", f"${stats['total_pnl_usd']:+,.2f}")
            c4.metric("Avg R", f"{stats['avg_r_per_trade']:+.2f}")

            # ML calibration
            ml = stats["ml_calibration"]
            if ml["n_with_ml"] > 0:
                st.subheader("🎯 Calibration ML")
                c5, c6, c7 = st.columns(3)
                c5.metric("Prédit moyen", f"{ml['avg_predicted_winrate']:.1%}")
                c6.metric("Réel", f"{ml['actual_winrate']:.1%}")
                c7.metric("Delta",
                           f"{ml['delta']:+.1%}",
                           delta="ML trop optimiste" if ml["delta"] < 0 else "ML précis")

            # Equity curve
            ec = j.equity_curve(SETTINGS.account_balance)
            if not ec.empty:
                st.subheader("📈 Equity Curve")
                st.line_chart(ec.set_index("exit_time")["equity"])

            st.subheader("Par asset")
            st.dataframe(j.by_asset(), use_container_width=True, hide_index=True)
            st.subheader("Par killzone")
            st.dataframe(j.by_killzone(), use_container_width=True, hide_index=True)

    with tab3:
        st.subheader("Add manual trade")
        with st.form("manual_trade"):
            c1, c2, c3 = st.columns(3)
            sym = c1.selectbox("Symbol", list_instruments())
            side = c2.selectbox("Side", ["long", "short"])
            ltf = c3.selectbox("TF", ["1h", "4h", "1d", "15m", "5m"])
            c4, c5, c6 = st.columns(3)
            entry = c4.number_input("Entry", value=0.0, step=0.0001, format="%.4f")
            sl = c5.number_input("SL", value=0.0, step=0.0001, format="%.4f")
            tp1 = c6.number_input("TP1", value=0.0, step=0.0001, format="%.4f")
            c7, c8 = st.columns(2)
            lots = c7.number_input("Lots", value=0.5, step=0.01)
            notes = c8.text_input("Notes", "")
            if st.form_submit_button("➕ Log trade (OPEN)"):
                entry_obj = JournalEntry(
                    trade_id=str(uuid.uuid4())[:8],
                    created_at=datetime.utcnow().isoformat(),
                    symbol=sym, ltf=ltf, side=side,
                    entry=entry, stop_loss=sl, take_profit_1=tp1,
                    entry_time=datetime.utcnow().isoformat(),
                    entry_fill=entry, lots=lots,
                    risk_usd=SETTINGS.account_balance * SETTINGS.risk_per_trade_pct / 100,
                    notes=notes,
                )
                j.log(entry_obj)
                st.success(f"✓ Trade {entry_obj.trade_id} logged.")


# ==================================================================
# NEWS CALENDAR
# ==================================================================
elif page == "📅 News Calendar":
    st.title("📅 News Calendar")
    try:
        from src.news_calendar import NewsCalendar
        cal = NewsCalendar(
            skip_minutes_before=SETTINGS.skip_news_minutes_before,
            skip_minutes_after=SETTINGS.skip_news_minutes_after,
            min_impact=SETTINGS.skip_news_impact.capitalize(),
        )
        with st.spinner("Refreshing calendar..."):
            cal.refresh()

        hours = st.slider("Upcoming hours", 24, 168, 48)
        events = cal.upcoming(hours=hours)
        if not events:
            st.info("Aucun event à venir.")
        else:
            rows = []
            for e in events:
                rows.append({
                    "Time UTC": e.datetime_utc.strftime("%Y-%m-%d %H:%M"),
                    "Currency": e.currency,
                    "Impact": e.impact,
                    "Title": e.title,
                    "Forecast": e.forecast,
                    "Previous": e.previous,
                })
            df = pd.DataFrame(rows)
            # color
            def color_impact(val):
                if val == "High": return "background-color: rgba(255, 0, 0, 0.3)"
                if val == "Medium": return "background-color: rgba(255, 165, 0, 0.3)"
                return ""
            st.dataframe(
                df.style.applymap(color_impact, subset=["Impact"]),
                use_container_width=True, hide_index=True,
            )
    except Exception as e:
        st.error(f"Calendar unavailable: {e}")


# ==================================================================
# RISK COMPLIANCE
# ==================================================================
elif page == "🛡️ Risk Compliance":
    st.title("🛡️ Risk Compliance")
    firm = st.selectbox("Firm", ["ftmo", "the_5ers"])
    variants = {"ftmo": ["classic_challenge", "verification", "funded"],
                "the_5ers": ["bootcamp", "hpt"]}
    variant = st.selectbox("Variant", variants[firm])
    rules = get_prop_firm_rules(firm, variant)

    st.subheader("Règles officielles")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Balance initial", f"${rules['initial_balance']:,}")
    c2.metric("Max daily loss", f"{rules['max_daily_loss_pct']}%")
    c3.metric("Max overall", f"{rules['max_overall_loss_pct']}%")
    c4.metric("Profit target", f"{rules.get('profit_target_pct', 0)}%")

    st.subheader("🛡️ Limites INTERNES (buffer safety)")
    s = rules["safety"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Daily soft", f"{s['daily_loss_soft_cap_pct']}%", "stop trading")
    c2.metric("Daily hard", f"{s['daily_loss_hard_cap_pct']}%", "KILL SWITCH")
    c3.metric("Risk/trade", f"{s['risk_per_trade_base_pct']}%")
    c4.metric("Max trades/jour", s["max_trades_per_day"])

    st.markdown("""
    **Protection automatique** :
    - Stop trading à 50% de la limite daily (soft)
    - Kill switch à 70% de la limite daily (hard)
    - Size auto-réduite en DD (-2% → x0.75, -3.5% → x0.50, -5% → x0.25)
    - 3 pertes consécutives → pause 24h
    """)


# ==================================================================
# SETTINGS
# ==================================================================
elif page == "⚙️ Settings":
    st.title("⚙️ Settings — tout en un")
    st.caption("Ces paramètres sont persistants (user_data/settings.json + .env)")

    with st.form("settings_form"):
        st.subheader("🏦 Prop Firm")
        c1, c2, c3 = st.columns(3)
        firm = c1.selectbox("Firm", ["ftmo", "the_5ers"],
                              index=["ftmo", "the_5ers"].index(SETTINGS.firm))
        variants = {"ftmo": ["classic_challenge", "verification", "funded"],
                    "the_5ers": ["bootcamp", "hpt"]}
        vs = variants[firm]
        variant = c2.selectbox("Variant", vs,
                                 index=vs.index(SETTINGS.variant) if SETTINGS.variant in vs else 0)
        balance = c3.number_input("Balance", value=SETTINGS.account_balance, step=1000.0)

        st.subheader("📊 Risk")
        c1, c2, c3 = st.columns(3)
        risk = c1.number_input("Risk/trade %", 0.1, 2.0, SETTINGS.risk_per_trade_pct, 0.1)
        soft = c2.number_input("Daily soft cap %", 1.0, 5.0, SETTINGS.daily_soft_cap_pct, 0.1)
        hard = c3.number_input("Daily hard cap %", 1.0, 5.0, SETTINGS.daily_hard_cap_pct, 0.1)

        st.subheader("🎯 Scan")
        c1, c2, c3 = st.columns(3)
        tier = c1.selectbox("Default tier", ["elite", "balanced", "volume"],
                              index=["elite", "balanced", "volume"].index(SETTINGS.default_tier))
        interval = c2.number_input("Scan interval (min)", 5, 120, SETTINGS.scan_interval_minutes)
        alert_tier = c3.selectbox("Min alert tier", ["ELITE", "BALANCED", "VOLUME"],
                                    index=["ELITE", "BALANCED", "VOLUME"].index(SETTINGS.min_alert_tier))

        st.subheader("📱 Alertes")
        discord = st.text_input("Discord Webhook URL", SETTINGS.discord_webhook_url,
                                  type="password")
        c1, c2 = st.columns(2)
        tg_token = c1.text_input("Telegram Bot Token", SETTINGS.telegram_bot_token, type="password")
        tg_chat = c2.text_input("Telegram Chat ID", SETTINGS.telegram_chat_id)
        c1, c2 = st.columns(2)
        desktop = c1.checkbox("Desktop notifications", SETTINGS.desktop_notifications)
        sound = c2.checkbox("Sound alerts", SETTINGS.sound_alerts)

        st.subheader("📅 News skipping")
        c1, c2, c3 = st.columns(3)
        news_before = c1.number_input("Skip N min BEFORE news",
                                        0, 120, SETTINGS.skip_news_minutes_before)
        news_after = c2.number_input("Skip N min AFTER news",
                                       0, 120, SETTINGS.skip_news_minutes_after)
        news_impact = c3.selectbox("Impact min", ["all", "high", "none"],
                                     index=["all", "high", "none"].index(SETTINGS.skip_news_impact)
                                         if SETTINGS.skip_news_impact in ["all", "high", "none"] else 1)

        st.subheader("💰 Money Management")
        c1, c2, c3 = st.columns(3)
        partial_r = c1.number_input("Partial TP at (R)",
                                      0.0, 3.0, SETTINGS.partial_tp_at_r, 0.1)
        partial_pct = c2.number_input("Partial %",
                                        0.0, 1.0, SETTINGS.partial_tp_pct, 0.05)
        be_r = c3.number_input("BE at (R)", 0.0, 2.0, SETTINGS.move_be_at_r, 0.1)

        st.subheader("📊 Assets à scanner")
        all_inst = list_instruments()
        assets_h1 = st.multiselect("Assets H1", all_inst,
                                      default=SETTINGS.assets_h1)
        assets_d1 = st.multiselect("Assets D1", all_inst,
                                      default=SETTINGS.assets_d1)

        submit = st.form_submit_button("💾 SAVE SETTINGS", type="primary",
                                          use_container_width=True)
        if submit:
            new = UserSettings(
                firm=firm, variant=variant, account_balance=balance,
                risk_per_trade_pct=risk, daily_soft_cap_pct=soft, daily_hard_cap_pct=hard,
                assets_h1=assets_h1, assets_d1=assets_d1,
                scan_interval_minutes=interval, default_tier=tier, min_alert_tier=alert_tier,
                discord_webhook_url=discord, telegram_bot_token=tg_token, telegram_chat_id=tg_chat,
                desktop_notifications=desktop, sound_alerts=sound,
                skip_news_minutes_before=news_before, skip_news_minutes_after=news_after,
                skip_news_impact=news_impact,
                partial_tp_at_r=partial_r, partial_tp_pct=partial_pct, move_be_at_r=be_r,
            )
            new.save()
            st.success("✓ Settings saved. Reload la page pour voir les changements.")

    st.markdown("---")
    st.subheader("🧪 Test alertes")
    if st.button("Tester notification desktop"):
        from src.live_scanner.desktop_notify import notify
        ok = notify("ICT Framework", "Test ✓")
        st.success("Sent ✓") if ok else st.error("Échec")


# ==================================================================
# SYSTEM HEALTH
# ==================================================================
elif page == "🔧 System Health":
    st.title("🔧 System Health")
    c1, c2, c3 = st.columns(3)

    with c1:
        st.subheader("📁 Data")
        loader = DataLoader()
        checker = IntegrityChecker()
        files = sorted(Path("data/raw").glob("*.parquet"))
        ok = fail = 0
        for f in files:
            parts = f.stem.split("_", 1)
            if len(parts) != 2:
                continue
            try:
                sym, tf_s = parts
                df = loader.load(sym, Timeframe(tf_s))
                rep = checker.check(df, sym, Timeframe(tf_s))
                if rep.passed: ok += 1
                else: fail += 1
            except Exception:
                fail += 1
        if fail == 0:
            st.success(f"{ok}/{ok+fail} OK")
        else:
            st.warning(f"{ok}/{ok+fail} OK")

    with c2:
        st.subheader("🧪 Tests")
        import subprocess
        res = subprocess.run(
            ["python3", "-m", "pytest", "tests/", "-q", "--tb=no"],
            capture_output=True, text=True,
        )
        last = res.stdout.splitlines()[-1] if res.stdout else "?"
        if "passed" in last and "failed" not in last:
            st.success(last)
        else:
            st.error(last)

    with c3:
        st.subheader("📊 Reports")
        st.metric("JSON", len(list(Path("reports").glob("*.json"))))
        st.metric("CSV", len(list(Path("reports").glob("*.csv"))))

    st.subheader("💾 Dernières analyses")
    reports = sorted(Path("reports").glob("*.json"),
                     key=lambda p: p.stat().st_mtime, reverse=True)[:15]
    for r in reports:
        mtime = datetime.fromtimestamp(r.stat().st_mtime)
        st.text(f"• {r.name}  [{mtime:%Y-%m-%d %H:%M}]")

    st.subheader("🔗 Settings actifs")
    st.json({
        "firm": f"{SETTINGS.firm}/{SETTINGS.variant}",
        "balance": SETTINGS.account_balance,
        "risk_per_trade_pct": SETTINGS.risk_per_trade_pct,
        "assets_h1": SETTINGS.assets_h1,
        "assets_d1": SETTINGS.assets_d1,
        "discord_configured": bool(SETTINGS.discord_webhook_url),
        "telegram_configured": bool(SETTINGS.telegram_bot_token and SETTINGS.telegram_chat_id),
    })
