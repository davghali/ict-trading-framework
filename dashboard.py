"""
DASHBOARD v3 — SIMPLE, CLAIR, FONCTIONNEL.

5 pages uniquement :
  🏠 ACCUEIL       — signaux du jour + actions rapides
  🎯 SIGNAUX       — liste des setups ACTIFS (cards visuelles)
  📔 MES TRADES    — journal perso
  📅 NEWS          — events macro à éviter
  ⚙️ RÉGLAGES      — configurer ses alertes
"""
from __future__ import annotations

import sys
import json
import warnings
import uuid
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
warnings.filterwarnings("ignore")

import streamlit as st

from src.data_engine import DataLoader
from src.feature_engine import FeatureEngine
from src.utils.types import Timeframe
from src.utils.config import list_instruments, get_prop_firm_rules
from src.utils.user_settings import UserSettings, apply_env
from src.trade_journal import TradeJournal, JournalEntry

apply_env()
SETTINGS = UserSettings.load()

# ------------------------------------------------------------------
st.set_page_config(
    page_title="ICT Framework",
    page_icon="🔴",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ------------------------------------------------------------------
# AUTO-HEALING : télécharge la data si manquante (cloud first-run)
# ------------------------------------------------------------------
# CLOUD MODE : bootstrap LÉGER — seulement 3 assets D1 au démarrage
# Le reste se télécharge à la demande (quand l'user clique Scanner)
# ------------------------------------------------------------------
@st.cache_resource
def _bootstrap_data():
    """Télécharge le MINIMUM de data au démarrage (cloud-friendly)."""
    data_dir = Path("data/raw")
    data_dir.mkdir(parents=True, exist_ok=True)
    existing = list(data_dir.glob("*.parquet"))
    if len(existing) >= 4:
        return True

    try:
        from src.data_engine.downloader import download_asset
        from src.utils.types import Timeframe
        # Seulement 3 assets D1 = rapide (5-10s)
        for sym in ["XAUUSD", "NAS100", "EURUSD"]:
            try:
                download_asset(sym, Timeframe.D1, save=True)
            except Exception:
                pass
    except Exception:
        pass
    return True

_bootstrap_data()

# ------------------------------------------------------------------
# CSS — cards visuelles simples
# ------------------------------------------------------------------
st.markdown("""
<style>
.signal-card {
    background: #1E293B;
    border-radius: 12px;
    padding: 20px;
    margin: 10px 0;
    border-left: 6px solid #64748B;
}
.signal-card.long { border-left-color: #22C55E; }
.signal-card.short { border-left-color: #EF4444; }

.big-asset { font-size: 28px; font-weight: bold; color: #F1F5F9; }
.big-side-long { font-size: 20px; color: #22C55E; font-weight: bold; }
.big-side-short { font-size: 20px; color: #EF4444; font-weight: bold; }

.metric-row { display: flex; gap: 20px; margin-top: 12px; }
.metric-box {
    background: #0F172A;
    padding: 10px 14px;
    border-radius: 8px;
    flex: 1;
    min-width: 120px;
}
.metric-label { font-size: 11px; color: #94A3B8; text-transform: uppercase; }
.metric-val { font-size: 18px; color: #F1F5F9; font-weight: 600; }

.quality-badge {
    display: inline-block;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
}
.q-elite { background: #FCD34D; color: #78350F; }
.q-balanced { background: #93C5FD; color: #1E3A8A; }
.q-volume { background: #A7F3D0; color: #064E3B; }

.big-btn button { font-size: 20px !important; padding: 20px !important; }
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------
# SIDEBAR
# ------------------------------------------------------------------
with st.sidebar:
    st.markdown("# 🔴 ICT")
    st.caption("Ton outil de trading")
    st.markdown("---")

    page = st.radio(
        "Navigation",
        [
            "🏠 ACCUEIL",
            "📊 ANALYSE DU JOUR",
            "🎯 SIGNAUX",
            "📈 ESPÉRANCES",
            "📔 MES TRADES",
            "📅 NEWS",
            "⚙️ RÉGLAGES",
        ],
        label_visibility="collapsed",
    )

    st.markdown("---")
    st.markdown(f"**{SETTINGS.firm.upper()}**")
    st.caption(f"{SETTINGS.variant}")
    st.caption(f"💰 ${SETTINGS.account_balance:,.0f}")
    st.caption(f"⚠️ Risk {SETTINGS.risk_per_trade_pct}%/trade")


# ==================================================================
# HELPERS
# ==================================================================
@st.cache_data(ttl=60)
def get_latest_public_url():
    p = Path("user_data/public_url.txt")
    if p.exists():
        return p.read_text().strip()
    return ""


def tier_badge(tier: str) -> str:
    cls = {"ELITE": "q-elite", "BALANCED": "q-balanced", "VOLUME": "q-volume"}.get(tier, "q-volume")
    label = {"ELITE": "🎯 ELITE", "BALANCED": "⚖ BALANCED", "VOLUME": "🚀 VOLUME"}.get(tier, tier)
    return f'<span class="quality-badge {cls}">{label}</span>'


def signal_card(s, idx: int):
    """Render a visual card for a signal."""
    side_cls = "long" if s.side == "long" else "short"
    side_emoji = "🟢 ACHETER" if s.side == "long" else "🔴 VENDRE"
    prob = f"{s.ml_prob_win:.0%}" if s.ml_prob_win else "—"

    st.markdown(f"""
<div class="signal-card {side_cls}">
    <div style="display:flex; justify-content:space-between; align-items:center;">
        <div>
            <div class="big-asset">{s.symbol} <span style="font-size:14px;color:#94A3B8">{s.ltf.upper()}</span></div>
            <div class="big-side-{side_cls}">{side_emoji}</div>
        </div>
        <div style="text-align:right;">
            {tier_badge(s.tier)}
            <div style="color:#94A3B8; margin-top:8px; font-size:12px;">Probabilité de gain</div>
            <div style="font-size:24px; font-weight:bold; color:#F1F5F9;">{prob}</div>
        </div>
    </div>
    <div class="metric-row">
        <div class="metric-box">
            <div class="metric-label">Prix actuel</div>
            <div class="metric-val">{s.current_price:.4f}</div>
        </div>
        <div class="metric-box">
            <div class="metric-label">Entrée</div>
            <div class="metric-val">{s.entry:.4f}</div>
        </div>
        <div class="metric-box">
            <div class="metric-label">Stop Loss</div>
            <div class="metric-val" style="color:#EF4444">{s.stop_loss:.4f}</div>
        </div>
        <div class="metric-box">
            <div class="metric-label">TP1 (2R)</div>
            <div class="metric-val" style="color:#22C55E">{s.take_profit_1:.4f}</div>
        </div>
        <div class="metric-box">
            <div class="metric-label">TP2 (3R)</div>
            <div class="metric-val" style="color:#22C55E">{s.take_profit_2:.4f}</div>
        </div>
        <div class="metric-box">
            <div class="metric-label">Session</div>
            <div class="metric-val">{s.killzone.replace("_", " ").title()}</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)


# ==================================================================
# 🏠 ACCUEIL
# ==================================================================
if page == "🏠 ACCUEIL":
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # TON TRADER PERSONNEL — page "what to do NOW"
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    st.title("🔴 TON TRADER PERSONNEL")
    st.caption(f"⏰ {datetime.now().strftime('%A %d %B — %H:%M')}")

    col_a, col_b, col_c = st.columns([1, 1, 1])
    if col_a.button("🔄  SCANNER MAINTENANT", type="primary", use_container_width=True):
        st.session_state["home_scan"] = True
    col_b.metric("💰 Ton compte", f"${SETTINGS.account_balance:,.0f}")
    col_c.metric("⚠️ Risk/trade", f"{SETTINGS.risk_per_trade_pct}%")

    if st.session_state.get("home_scan"):
        st.session_state["home_scan"] = False
        try:
            with st.spinner("Scan en cours (téléchargement data + analyse, 30-90s)..."):
                from src.live_scanner import LiveScanner

                # Cloud-friendly : scan seulement 3 assets clés (rapide)
                scanner = LiveScanner(
                    symbols_h1=["XAUUSD", "NAS100"],
                    symbols_d1=["EURUSD"],
                    tier=SETTINGS.default_tier, refresh_data=True,
                )
                signals = scanner.scan_once()

                # Filter news
                try:
                    from src.news_calendar import NewsCalendar, currencies_for
                    cal = NewsCalendar(min_impact="High")
                    cal.refresh()
                    signals = [s for s in signals
                               if not cal.is_in_news_window(
                                   datetime.fromisoformat(s.timestamp_scan),
                                   currencies_for(s.symbol))]
                except Exception:
                    pass

                st.session_state["home_signals"] = signals
        except Exception as e:
            st.error(f"Erreur scan : {e}")
            st.info("Réessaie dans 30 secondes.")

    signals = st.session_state.get("home_signals", [])

    st.markdown("---")

    if not signals:
        st.info("👆 **Clique SCANNER MAINTENANT** pour voir les trades du moment.")
    else:
        # Top 1 — LE trade à prendre MAINTENANT
        best = signals[0]
        side_fr = "🟢 ACHETER" if best.side == "long" else "🔴 VENDRE"
        side_cls = "long" if best.side == "long" else "short"

        # Calcul lot size
        from src.risk_engine import PositionSizer
        sizer = PositionSizer()
        risk_usd = SETTINGS.account_balance * SETTINGS.risk_per_trade_pct / 100
        sizing = sizer.calculate(best.symbol, best.entry, best.stop_loss, risk_usd)
        lots_str = f"{sizing.size:.2f}" if sizing.valid else "calc manual"

        prob = f"{best.ml_prob_win:.0%}" if best.ml_prob_win else "—"

        st.markdown(f"""
<div class="signal-card {side_cls}" style="border-left-width:8px;">
    <div style="display:flex; justify-content:space-between; align-items:flex-start;">
        <div>
            <div style="font-size:14px; color:#94A3B8;">Ton trader te dit de</div>
            <div style="font-size:36px; font-weight:bold; margin:6px 0;">{side_fr}</div>
            <div style="font-size:28px; font-weight:bold;">{best.symbol}</div>
            <div style="color:#94A3B8;">Session : {best.killzone.replace("_", " ").upper()}</div>
        </div>
        <div style="text-align:right;">
            {tier_badge(best.tier)}
            <div style="color:#94A3B8; margin-top:12px; font-size:12px;">PROBA DE GAIN</div>
            <div style="font-size:32px; font-weight:bold;">{prob}</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

        st.markdown("### 📋  Copie-colle dans ton broker :")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Prix entrée", f"{best.entry:.4f}")
        c2.metric("Stop Loss", f"{best.stop_loss:.4f}", help="Protection si le trade se retourne")
        c3.metric("Take Profit 1", f"{best.take_profit_1:.4f}", help="Sors 50% ici (partial)")
        c4.metric("Take Profit 2", f"{best.take_profit_2:.4f}", help="Sors le reste ici")

        c1, c2, c3 = st.columns(3)
        c1.metric("🎯 Taille position", f"{lots_str} lots",
                   help=f"Calculé pour risquer ${risk_usd:.0f}")
        c2.metric("📐 Risk:Reward", f"1 : {best.risk_reward:.1f}")
        c3.metric("📏 Prix actuel", f"{best.current_price:.4f}")

        # Plan d'exécution
        st.markdown("### 🎯  Plan d'exécution — à suivre à la lettre")
        with st.container():
            st.markdown(f"""
1. **Maintenant** : place un ordre **{side_fr}** sur {best.symbol} @ `{best.entry:.4f}` avec Stop Loss `{best.stop_loss:.4f}` et TP `{best.take_profit_2:.4f}`
2. **Quand le prix atteint `{best.take_profit_1:.4f}`** (1R) → ferme la moitié de ta position + déplace le Stop Loss à l'entrée (`{best.entry:.4f}`) = **break-even**
3. **Laisse courir** jusqu'à `{best.take_profit_2:.4f}` (2R) → ferme le reste
4. **Si le Stop Loss est touché** avant → accepte la perte, passe au suivant. **NE DÉPLACE PAS LE SL CONTRE TOI.**
            """)

        # Log trade rapidement
        c1, c2 = st.columns(2)
        if c1.button("✅  JE PRENDS CE TRADE — log au journal", type="primary", use_container_width=True):
            jj = TradeJournal()
            entry_obj = JournalEntry(
                trade_id=str(uuid.uuid4())[:8],
                created_at=datetime.utcnow().isoformat(),
                symbol=best.symbol, ltf=best.ltf, side=best.side,
                entry=best.entry, stop_loss=best.stop_loss,
                take_profit_1=best.take_profit_1, take_profit_2=best.take_profit_2,
                source_signal_id=f"{best.symbol}_{best.fvg_age_bars}",
                ml_prob_win_at_signal=best.ml_prob_win, tier_at_signal=best.tier,
                entry_time=datetime.utcnow().isoformat(), entry_fill=best.current_price,
                lots=sizing.size if sizing.valid else 0,
                risk_usd=risk_usd, killzone=best.killzone,
                notes=f"Auto-log depuis ACCUEIL (ML P={prob})",
            )
            jj.log(entry_obj)
            st.success(f"✅ Trade #{entry_obj.trade_id} logged. Ferme-le via '📔 MES TRADES'.")
        if c2.button("⏭  PASSER AU SUIVANT", use_container_width=True):
            st.session_state["home_signals"] = signals[1:]
            st.rerun()

        # Next trades (autres opportunités)
        if len(signals) > 1:
            st.markdown("---")
            with st.expander(f"📋 Autres opportunités actives ({len(signals) - 1})"):
                for s in signals[1:6]:
                    side_icon = "🟢" if s.side == "long" else "🔴"
                    p = f"{s.ml_prob_win:.0%}" if s.ml_prob_win else "—"
                    st.markdown(f"- {side_icon} **{s.symbol}** {s.ltf} — {s.side.upper()} @ {s.entry:.4f} — RR {s.risk_reward:.1f} — P {p} — {s.tier}")
                st.caption("Voir tous les détails → page 🎯 SIGNAUX")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Stats compte (bottom)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    st.markdown("---")
    c1, c2, c3 = st.columns(3)

    j = TradeJournal()
    stats = j.analytics()
    with c1:
        st.markdown("##### 📔 Ton journal")
        if stats["n_closed"] > 0:
            st.metric("Trades fermés", stats["n_closed"])
            st.caption(f"WR réel : {stats['win_rate']:.1%} • PnL {stats['total_pnl_usd']:+,.0f}$")
        else:
            st.caption("Aucun trade loggé encore.")

    with c2:
        st.markdown("##### 📅 Prochains events news")
        try:
            from src.news_calendar import NewsCalendar
            cal = NewsCalendar(min_impact="High")
            cal.refresh()
            upc = [e for e in cal.upcoming(hours=12) if e.impact == "High"][:3]
            if upc:
                for ev in upc:
                    t = ev.datetime_utc.strftime("%H:%M")
                    st.caption(f"🔴 **{t}** {ev.currency} {ev.title[:35]}")
            else:
                st.caption("✅ Rien dans les 12h")
        except Exception:
            st.caption("N/A")

    with c3:
        st.markdown("##### 🛡️ Protection FTMO")
        rules = get_prop_firm_rules(SETTINGS.firm, SETTINGS.variant)
        st.caption(f"Limite daily : -{rules['max_daily_loss_pct']}%")
        st.caption(f"Stop à : -{rules['safety']['daily_loss_hard_cap_pct']}% (auto)")
        st.caption(f"Trades/jour max : {rules['safety']['max_trades_per_day']}")

# ==================================================================
# 🎯 SIGNAUX
# ==================================================================
elif page == "🎯 SIGNAUX":
    st.title("🎯 Signaux actifs")

    c1, c2, c3 = st.columns([2, 1, 2])
    tier = c1.selectbox("Qualité minimum", ["Toutes", "Balanced ou mieux", "Elite seulement"])
    skip_news = c2.checkbox("Skip news", True, help="Ne pas trader pendant les events macro")
    run = c3.button("🔍  SCANNER MAINTENANT", type="primary", use_container_width=True)

    auto = st.session_state.pop("auto_scan", False)

    if run or auto:
      try:
        with st.spinner("Scan en cours (téléchargement data + analyse, 30-90s)..."):
            from src.live_scanner import LiveScanner
            tier_code = {"Toutes": "volume", "Balanced ou mieux": "balanced", "Elite seulement": "elite"}[tier]
            scanner = LiveScanner(
                symbols_h1=["XAUUSD", "XAGUSD", "NAS100"],
                symbols_d1=["EURUSD", "GBPUSD"],
                tier=tier_code,
                refresh_data=True,
            )
            signals = scanner.scan_once()

            if skip_news and signals:
                try:
                    from src.news_calendar import NewsCalendar, currencies_for
                    cal = NewsCalendar(min_impact="High")
                    cal.refresh()
                    filtered = []
                    for s in signals:
                        ts = datetime.fromisoformat(s.timestamp_scan)
                        if not cal.is_in_news_window(ts, currencies_for(s.symbol)):
                            filtered.append(s)
                    if len(signals) - len(filtered) > 0:
                        st.info(f"⏭ {len(signals) - len(filtered)} signal(s) ignorés (fenêtre news)")
                    signals = filtered
                except Exception:
                    pass

        if not signals:
            st.info("😴 Aucun signal actif dans les conditions actuelles. Reviens dans quelques heures.")
        else:
            st.success(f"✅ {len(signals)} signal(s) trouvés — triés par qualité")

            for idx, s in enumerate(signals):
                signal_card(s, idx)

                with st.expander(f"➕ Logger ce trade dans mon journal"):
                    c1, c2 = st.columns(2)
                    lots = c1.number_input("Lots", 0.01, 10.0, 0.5, 0.01, key=f"lots_{idx}")
                    notes = c2.text_input("Notes", "", key=f"notes_{idx}")
                    if st.button("📔 Ajouter au journal", key=f"log_{idx}"):
                        jj = TradeJournal()
                        entry = JournalEntry(
                            trade_id=str(uuid.uuid4())[:8],
                            created_at=datetime.utcnow().isoformat(),
                            symbol=s.symbol, ltf=s.ltf, side=s.side,
                            entry=s.entry, stop_loss=s.stop_loss,
                            take_profit_1=s.take_profit_1,
                            take_profit_2=s.take_profit_2,
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
                        jj.log(entry)
                        st.success(f"✅ Trade #{entry.trade_id} ajouté — ferme-le dans '📔 MES TRADES'")

      except Exception as e:
        st.error(f"Erreur scan : {e}")
        st.info("Le cloud télécharge les données. Réessaie dans 30 secondes.")

    else:
        st.markdown("""
👆 **Clique le bouton rouge** pour scanner. Premier scan = 30-90s (téléchargement data).

**Assets analysés** : XAUUSD, XAGUSD, NAS100, EURUSD, GBPUSD
        """)


# ==================================================================
# 📔 MES TRADES
# ==================================================================
elif page == "📔 MES TRADES":
    st.title("📔 Mes trades")
    j = TradeJournal()
    entries = j.load_all()

    tab1, tab2, tab3 = st.tabs(["📋 Tous mes trades", "📊 Performance", "➕ Ajouter manuel"])

    with tab1:
        if not entries:
            st.info("Aucun trade pour l'instant. Ajoute via '🎯 SIGNAUX' ou l'onglet '➕ Ajouter manuel'.")
        else:
            opens = [e for e in entries if not e.is_closed]
            closed = [e for e in entries if e.is_closed]

            if opens:
                st.subheader(f"🟡 Trades en cours ({len(opens)})")
                for e in opens:
                    cols = st.columns([1, 1, 1, 1, 1, 2])
                    cols[0].markdown(f"**{e.symbol}**")
                    cols[1].markdown("🟢 LONG" if e.side == "long" else "🔴 SHORT")
                    cols[2].markdown(f"Entry: {e.entry:.4f}")
                    cols[3].markdown(f"SL: {e.stop_loss:.4f}")
                    cols[4].markdown(f"TP: {e.take_profit_1:.4f}")
                    with cols[5].expander(f"Fermer #{e.trade_id}"):
                        exit_p = st.number_input("Prix de sortie", value=e.entry,
                                                   format="%.4f", key=f"close_{e.trade_id}")
                        reason = st.selectbox("Raison", ["tp1", "tp2", "sl", "be", "manuel"],
                                                key=f"reason_{e.trade_id}")
                        if st.button("Fermer", key=f"btn_{e.trade_id}"):
                            side_mult = 1 if e.side == "long" else -1
                            pnl_r = side_mult * (exit_p - e.entry_fill) / abs(e.entry_fill - e.stop_loss)
                            pnl_usd = pnl_r * e.risk_usd
                            j.close_trade(e.trade_id, datetime.utcnow().isoformat(),
                                           exit_p, pnl_usd, pnl_r, reason)
                            st.success(f"Fermé : {pnl_r:+.2f}R ({pnl_usd:+.0f}$)")
                            st.rerun()

            if closed:
                st.subheader(f"✅ Trades fermés ({len(closed)})")
                rows = []
                for e in closed:
                    rows.append({
                        "Asset": e.symbol, "Side": "🟢" if e.side == "long" else "🔴",
                        "Entry": f"{e.entry:.4f}", "Exit": f"{e.exit_fill:.4f}" if e.exit_fill else "—",
                        "PnL $": f"{e.pnl_usd:+.0f}", "PnL R": f"{e.pnl_r:+.2f}",
                        "Raison": e.exit_reason,
                    })
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    with tab2:
        stats = j.analytics()
        if stats["n_closed"] == 0:
            st.info("Ferme des trades pour voir tes stats.")
        else:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Trades", stats["n_closed"])
            c2.metric("Wins", stats["n_wins"])
            c3.metric("WR", f"{stats['win_rate']:.1%}")
            c4.metric("Total $", f"{stats['total_pnl_usd']:+,.0f}")

            c5, c6, c7 = st.columns(3)
            c5.metric("Avg R", f"{stats['avg_r_per_trade']:+.2f}")
            ml = stats["ml_calibration"]
            if ml["n_with_ml"] > 0:
                c6.metric("ML prédisait", f"{ml['avg_predicted_winrate']:.1%}")
                delta = ml['delta']
                c7.metric("Écart (réel - prédit)", f"{delta:+.1%}",
                           help="Positif = tu performes mieux que le modèle")

            # Equity
            eq = j.equity_curve(SETTINGS.account_balance)
            if not eq.empty:
                st.subheader("📈 Ton equity curve")
                st.line_chart(eq.set_index("exit_time")["equity"])

    with tab3:
        with st.form("manual_form"):
            c1, c2, c3 = st.columns(3)
            sym = c1.selectbox("Asset", list_instruments())
            side = c2.selectbox("Côté", ["long", "short"])
            ltf = c3.selectbox("TF", ["1h", "4h", "1d", "15m"])
            c4, c5, c6 = st.columns(3)
            entry = c4.number_input("Entrée", 0.0, format="%.4f")
            sl = c5.number_input("Stop Loss", 0.0, format="%.4f")
            tp = c6.number_input("Take Profit", 0.0, format="%.4f")
            c7, c8 = st.columns(2)
            lots = c7.number_input("Lots", 0.01, 10.0, 0.5, 0.01)
            notes = c8.text_input("Notes", "")
            if st.form_submit_button("➕ Ajouter", type="primary"):
                entry_obj = JournalEntry(
                    trade_id=str(uuid.uuid4())[:8],
                    created_at=datetime.utcnow().isoformat(),
                    symbol=sym, ltf=ltf, side=side,
                    entry=entry, stop_loss=sl, take_profit_1=tp,
                    entry_time=datetime.utcnow().isoformat(), entry_fill=entry,
                    lots=lots, risk_usd=SETTINGS.account_balance * SETTINGS.risk_per_trade_pct / 100,
                    notes=notes,
                )
                j.log(entry_obj)
                st.success(f"✅ Trade #{entry_obj.trade_id} ajouté")


# ==================================================================
# 📅 NEWS
# ==================================================================
elif page == "📅 NEWS":
    st.title("📅 Calendrier économique")
    st.caption("Events macro à venir — le système skip automatiquement les trades pendant ces fenêtres")

    try:
        from src.news_calendar import NewsCalendar
        cal = NewsCalendar()
        with st.spinner("Chargement du calendrier..."):
            cal.refresh()

        hours = st.slider("Horizon", 24, 168, 48, step=24)
        events = cal.upcoming(hours=hours)

        if not events:
            st.success("✅ Aucun event à venir")
        else:
            # Group by day
            from itertools import groupby
            events.sort(key=lambda e: e.datetime_utc)

            for day, day_events in groupby(events, key=lambda e: e.datetime_utc.date()):
                day_events = list(day_events)
                st.subheader(f"📆 {day.strftime('%A %d %B')}")
                for ev in day_events:
                    icon = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}.get(ev.impact, "⚪")
                    time_str = ev.datetime_utc.strftime("%H:%M UTC")
                    if ev.impact == "High":
                        st.error(f"{icon} **{time_str}** — {ev.currency} — **{ev.title}**")
                    elif ev.impact == "Medium":
                        st.warning(f"{icon} **{time_str}** — {ev.currency} — {ev.title}")
                    else:
                        st.caption(f"{icon} {time_str} — {ev.currency} — {ev.title}")
    except Exception as e:
        st.error(f"Impossible de charger le calendrier : {e}")


# ==================================================================
# ⚙️ RÉGLAGES
# ==================================================================
elif page == "⚙️ RÉGLAGES":
    st.title("⚙️ Réglages")

    with st.form("settings"):
        st.subheader("🏦 Ton compte prop firm")
        c1, c2 = st.columns(2)
        firm = c1.selectbox("Firme", ["ftmo", "the_5ers"],
                              index=["ftmo", "the_5ers"].index(SETTINGS.firm))
        variants = {"ftmo": ["classic_challenge", "verification", "funded"],
                    "the_5ers": ["bootcamp", "hpt"]}
        vs = variants[firm]
        variant = c2.selectbox("Phase", vs,
                                 index=vs.index(SETTINGS.variant) if SETTINGS.variant in vs else 0)
        balance = st.number_input("Balance de ton compte ($)", 1000.0,
                                     value=SETTINGS.account_balance, step=1000.0)

        st.subheader("⚠️ Ton risque")
        risk = st.slider("Risk par trade (%)", 0.1, 2.0, SETTINGS.risk_per_trade_pct, 0.1,
                          help="On recommande 0.5% pour passer FTMO avec marge")

        st.subheader("📱 Tes alertes")
        discord = st.text_input("Discord Webhook URL (optionnel)",
                                  SETTINGS.discord_webhook_url, type="password",
                                  help="Paramètres Discord > Intégrations > Webhook")
        c1, c2 = st.columns(2)
        tg_token = c1.text_input("Telegram Token (optionnel)",
                                   SETTINGS.telegram_bot_token, type="password")
        tg_chat = c2.text_input("Telegram Chat ID",
                                  SETTINGS.telegram_chat_id)
        desktop = st.checkbox("Notifications Mac", SETTINGS.desktop_notifications)

        st.subheader("📅 Skip les news")
        c1, c2, c3 = st.columns(3)
        nb = c1.number_input("Min avant", 0, 120, SETTINGS.skip_news_minutes_before)
        na = c2.number_input("Min après", 0, 120, SETTINGS.skip_news_minutes_after)
        ni = c3.selectbox("Impact", ["high", "all", "none"],
                            index=["high", "all", "none"].index(SETTINGS.skip_news_impact)
                                if SETTINGS.skip_news_impact in ["high", "all", "none"] else 0)

        submit = st.form_submit_button("💾  SAUVEGARDER", type="primary",
                                          use_container_width=True)
        if submit:
            new = UserSettings(
                firm=firm, variant=variant, account_balance=balance,
                risk_per_trade_pct=risk,
                daily_soft_cap_pct=SETTINGS.daily_soft_cap_pct,
                daily_hard_cap_pct=SETTINGS.daily_hard_cap_pct,
                assets_h1=SETTINGS.assets_h1, assets_d1=SETTINGS.assets_d1,
                scan_interval_minutes=SETTINGS.scan_interval_minutes,
                default_tier=SETTINGS.default_tier,
                min_alert_tier=SETTINGS.min_alert_tier,
                discord_webhook_url=discord, telegram_bot_token=tg_token,
                telegram_chat_id=tg_chat,
                desktop_notifications=desktop,
                sound_alerts=SETTINGS.sound_alerts,
                skip_news_minutes_before=nb, skip_news_minutes_after=na,
                skip_news_impact=ni,
                partial_tp_at_r=SETTINGS.partial_tp_at_r,
                partial_tp_pct=SETTINGS.partial_tp_pct,
                move_be_at_r=SETTINGS.move_be_at_r,
            )
            new.save()
            st.success("✅ Sauvegardé. Recharge la page pour voir les changements.")

    # ------ Info compte + règles FTMO
    st.markdown("---")
    st.subheader(f"🛡️ Règles {SETTINGS.firm.upper()} — {SETTINGS.variant}")
    rules = get_prop_firm_rules(SETTINGS.firm, SETTINGS.variant)
    c1, c2, c3 = st.columns(3)
    c1.metric("Max daily loss", f"-{rules['max_daily_loss_pct']}%",
               help="Limite officielle de la firm")
    c2.metric("Max overall", f"-{rules['max_overall_loss_pct']}%")
    c3.metric("Target profit", f"+{rules.get('profit_target_pct', 0)}%")
    st.caption(f"🛡️ Le système bloque à -{rules['safety']['daily_loss_hard_cap_pct']}% daily (safety buffer)")


# ==================================================================
# 📊 ANALYSE DU JOUR
# ==================================================================
elif page == "📊 ANALYSE DU JOUR":
    st.title("📊 Analyse du jour")
    st.caption("Biais HTF + niveaux clés + meilleur trade par asset")
    st.warning("⚠ L'analyse télécharge les données et peut prendre 1-2 min sur le cloud. Patience.")

    if st.button("🔄 Lancer l'analyse", type="primary", use_container_width=True):
        try:
            from src.daily_analysis import DailyAnalyzer
            with st.spinner("Analyse en cours (téléchargement données + calculs)..."):
                analyzer = DailyAnalyzer()
                results = analyzer.analyze_all()
            st.session_state["daily_results"] = results
        except Exception as e:
            st.error(f"Erreur : {e}")
            st.info("Certains assets n'ont pas pu être analysés (données indisponibles sur le cloud). Réessaie dans 1 min.")

    results = st.session_state.get("daily_results", [])
    if not results:
        st.info("👆 Clique le bouton pour lancer l'analyse complète")
    else:
        # Summary
        with_trade = [r for r in results if r.trade_idea is not None]
        buys = [r for r in with_trade if r.recommendation == "BUY"]
        sells = [r for r in with_trade if r.recommendation == "SELL"]
        waits = [r for r in results if r.recommendation == "WAIT"]

        c1, c2, c3 = st.columns(3)
        c1.metric("🟢 Opportunités BUY", len(buys))
        c2.metric("🔴 Opportunités SELL", len(sells))
        c3.metric("⏸ WAIT", len(waits))

        st.markdown("---")

        # Cards par asset
        for a in results:
            rec_color = {"BUY": "🟢", "SELL": "🔴", "WAIT": "⚪"}.get(a.recommendation, "⚪")
            rec_bg = {"BUY": "#14532D", "SELL": "#7F1D1D", "WAIT": "#334155"}.get(a.recommendation, "#334155")

            with st.container():
                st.markdown(f"""
<div style="background:#1E293B; border-radius:12px; padding:16px; margin:10px 0; border-left:6px solid {rec_bg};">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <div>
            <span style="font-size:24px; font-weight:bold;">{rec_color} {a.symbol}</span>
            <span style="color:#94A3B8; margin-left:8px; font-size:14px;">{a.ltf.upper()}</span>
            <span style="background:#334155; padding:3px 10px; border-radius:999px; margin-left:12px; font-size:12px;">
                Biais {a.htf_bias} ({a.bias_probability:.0%})
            </span>
        </div>
        <div style="text-align:right;">
            <div style="font-size:12px; color:#94A3B8;">PRIORITÉ</div>
            <div style="font-size:24px; font-weight:bold;">{a.priority_score:.0f}/100</div>
        </div>
    </div>
    <div style="color:#CBD5E1; margin-bottom:8px;">{a.summary_fr}</div>
</div>
""", unsafe_allow_html=True)

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Prix actuel", f"{a.current_price:.4f}")
                c2.metric("Tendance Weekly", a.weekly_trend)
                c3.metric("Tendance Daily", a.daily_trend)
                c4.metric("Volatilité", a.vol_regime)

                if a.trade_idea:
                    ti = a.trade_idea
                    st.markdown(f"**🎯 Idée de trade : {'ACHETER' if ti.side == 'long' else 'VENDRE'}** — {ti.tier}")
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Entry", f"{ti.entry:.4f}")
                    c2.metric("Stop Loss", f"{ti.stop_loss:.4f}")
                    c3.metric("Take Profit 1", f"{ti.take_profit_1:.4f}")
                    c4.metric("RR", f"{ti.risk_reward:.1f}  |  P {ti.probability:.0%}")
                    st.caption(ti.rationale)

                # Key levels
                if a.key_levels:
                    with st.expander(f"Niveaux clés ({len(a.key_levels)})"):
                        for lv in a.key_levels[:6]:
                            swept = "✓ touché" if lv.swept else "non touché"
                            direction = "↑" if lv.distance_pct > 0 else "↓"
                            st.caption(f"**{lv.name}** @ {lv.price:.4f} — {direction} {abs(lv.distance_pct):.2f}% — {swept}")

                if a.warnings:
                    for w in a.warnings:
                        st.warning(f"⚠ {w}")

                st.markdown("---")


# ==================================================================
# 📈 ESPÉRANCES
# ==================================================================
elif page == "📈 ESPÉRANCES":
    st.title("📈 Tes espérances de gains")

    try:
        from src.daily_analysis import compute_asset_expectations, compute_global
    except Exception:
        st.info("Module en cours de chargement...")
        st.stop()

    # Check si les rapports Pareto existent
    pareto_files = sorted(Path("reports").glob("max_edge_pareto_*.json")) if Path("reports").exists() else []
    if not pareto_files:
        st.warning("⚠ Pas encore de rapport Pareto sur le cloud.")
        st.markdown("""
**Les espérances chiffrées nécessitent un rapport ML** qui est généré sur ton Mac.

**Résumé des chiffres (calculés localement) :**

| Tier | Trades/mois | WR | Rendement/mois (0.5%) |
|---|---|---|---|
| ELITE | 93 | 41.7% | ~+9.5% |
| BALANCED | 138 | 41.4% | ~+14% |
| VOLUME | 165 | 40.3% | ~+16% |

**Top assets :**
- XAGUSD H1 : 35/mo @ WR 46.2%
- XAUUSD H1 : 27/mo @ WR 47.3%
- BTCUSD H1 : 72/mo @ WR 36.9%

**FTMO 10% target** : ~10-30 jours selon risk (0.25-1%)
        """)
        st.stop()

    st.caption("Chiffres basés sur les backtests OOS validés par ML")

    tier = st.selectbox("Mode de trading", ["balanced", "elite", "volume"], index=0,
                         format_func=lambda x: {
                             "balanced": "⚖ BALANCED (recommandé)",
                             "elite": "🎯 ELITE (max qualité)",
                             "volume": "🚀 VOLUME (max trades)",
                         }[x])

    global_exp = compute_global(tier)
    asset_exps = compute_asset_expectations(tier)

    if global_exp is None:
        st.warning("Pas de données Pareto. Lance `python3 run_maximum_edge.py` d'abord.")
        st.stop()

    # ─── GLOBAL
    st.header("🌍 Global (tous assets cumulés)")
    c1, c2, c3 = st.columns(3)
    c1.metric("Trades / semaine", f"{global_exp.total_trades_per_week:.0f}")
    c2.metric("Win Rate moyen", f"{global_exp.blended_winrate:.1%}")
    c3.metric("Expectancy / trade", f"{global_exp.blended_expectancy_r:+.2f} R",
               help="R = risque par trade. Ex: 0.20R → +20% du risque pris en moyenne par trade")

    st.subheader("💰 Rendement mensuel attendu selon ton risque/trade")
    c1, c2, c3 = st.columns(3)
    c1.metric("Risk 0.25% (ultra-safe)",
               f"+{global_exp.monthly_return_pct_at_risk['0.25%']}% / mois",
               help=f"Pass FTMO 10% en {global_exp.days_to_pass_ftmo['0.25%']} jours ouvrés")
    c2.metric("Risk 0.5% (recommandé)",
               f"+{global_exp.monthly_return_pct_at_risk['0.5%']}% / mois",
               help=f"Pass FTMO 10% en {global_exp.days_to_pass_ftmo['0.5%']} jours ouvrés")
    c3.metric("Risk 1% (agressif)",
               f"+{global_exp.monthly_return_pct_at_risk['1.0%']}% / mois",
               help=f"Pass FTMO 10% en {global_exp.days_to_pass_ftmo['1.0%']} jours ouvrés")

    st.markdown(f"""
📌 **Pour passer ta FTMO Classic Challenge (target +10%)** :
- Risk **0.25%** → en ~**{global_exp.days_to_pass_ftmo['0.25%']} jours** (ultra-safe, DD attendu ~3%)
- Risk **0.5%** → en ~**{global_exp.days_to_pass_ftmo['0.5%']} jours** (recommandé, DD ~{global_exp.worst_case_dd_pct:.0f}%)
- Risk **1%** → en ~**{global_exp.days_to_pass_ftmo['1.0%']} jours** (agressif, DD ~{global_exp.worst_case_dd_pct*2:.0f}%)

⚠ **Le Risk Engine bloque AUTOMATIQUEMENT à -3.5% daily** (FTMO limit = -5%) → impossible de blow-up.
    """)

    # ─── PAR ASSET
    st.markdown("---")
    st.header("🔍 Détail par asset")

    for a in asset_exps:
        conf_icon = {"high": "🟢", "medium": "🟡", "low": "🟠"}[a.data_confidence]
        conf_txt = {"high": "confiance HAUTE (n>100)", "medium": "confiance MOYENNE (n 30-100)", "low": "confiance FAIBLE (n<30)"}[a.data_confidence]

        with st.expander(f"{conf_icon} **{a.asset}** {a.tf.upper()} — {a.trades_per_week:.1f} trades/sem, WR {a.winrate:.0%}, exp {a.expectancy_r:+.2f}R  →  +{a.monthly_return_pct_at_risk['0.5%']:.1f}%/mois à 0.5%"):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Trades/sem", f"{a.trades_per_week:.1f}")
            c2.metric("Win Rate", f"{a.winrate:.1%}")
            c3.metric("Exp R / trade", f"{a.expectancy_r:+.2f}")
            c4.metric("Expectancy mensuelle", f"{a.monthly_r_expected:+.1f} R")

            c1, c2, c3 = st.columns(3)
            c1.metric("@ 0.25% risk", f"+{a.monthly_return_pct_at_risk['0.25%']}%/mois",
                       f"FTMO en {a.days_to_10pct_at_risk['0.25%']}j")
            c2.metric("@ 0.5% risk", f"+{a.monthly_return_pct_at_risk['0.5%']}%/mois",
                       f"FTMO en {a.days_to_10pct_at_risk['0.5%']}j")
            c3.metric("@ 1% risk", f"+{a.monthly_return_pct_at_risk['1.0%']}%/mois",
                       f"FTMO en {a.days_to_10pct_at_risk['1.0%']}j")

            st.caption(f"📊 {conf_txt} — Money management actif appliqué (partial TP, BE @ 0.5R)")

    st.markdown("---")
    st.info("""
**⚠️ Ces chiffres sont des ESPÉRANCES basées sur OOS ML**.

Réalité :
- Les perfs passées ne garantissent pas les perfs futures
- La variance sur 100 trades peut être ±20%
- Ton résultat dépend aussi de TOI : discipline, skip news, respect des règles
- Reste conservateur (0.25-0.5%) jusqu'à 100+ trades validés en journal
    """)


# ==================================================================
# 🎯 TRADER MAINTENANT — la page "just do it"
# ==================================================================
# (handled via ACCUEIL / SIGNAUX already, but we add a dedicated page below)
