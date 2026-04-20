"""
RECAP GENERATOR — morning brief + evening recap + weekly + monthly.

Morning (07h UTC) :
- Stats d'hier
- Events news aujourd'hui
- Niveaux clés par asset
- Bias HTF courant

Evening (22h UTC) :
- Trades du jour (nb, WR, R, PnL)
- Meilleur / pire trade
- Compliance FTMO
- Suggestions demain

Weekly (Dim 20h UTC) :
- Bilan 7 jours
- Top/flop assets
- Equity curve

Monthly :
- Performance mensuelle complète
- Projection vers target FTMO
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict
import pandas as pd

from src.trade_journal import TradeJournal
from src.utils.user_settings import UserSettings, apply_env
from src.utils.config import get_prop_firm_rules
from src.utils.logging_conf import get_logger

log = get_logger(__name__)


class RecapGenerator:

    def __init__(self):
        apply_env()
        self.settings = UserSettings.load()
        self.journal = TradeJournal()
        self.rules = get_prop_firm_rules(self.settings.firm, self.settings.variant)

    # ==================================================================
    # MORNING BRIEF
    # ==================================================================
    def morning_brief(self) -> str:
        now = datetime.utcnow()
        yesterday = now - timedelta(days=1)

        y_trades = self._trades_on_date(yesterday.date())
        y_stats = self._compute_stats(y_trades)

        lines = [
            f"🌅 *MORNING BRIEF — {now.strftime('%A %d %B')}*\n",
        ]

        # Yesterday recap
        if y_stats["n"] > 0:
            lines.append(f"📊 *Hier* : {y_stats['n']} trades")
            lines.append(f"  • WR : {y_stats['win_rate']:.0%}")
            lines.append(f"  • PnL : {y_stats['pnl']:+.0f} USD ({y_stats['pnl_pct']:+.2f}%)")
            lines.append(f"  • R total : {y_stats['r']:+.2f}R")
        else:
            lines.append("📊 *Hier* : aucun trade")

        lines.append("")

        # Today's news
        try:
            from src.news_calendar import NewsCalendar
            cal = NewsCalendar(min_impact="High")
            cal.refresh()
            today_high = [
                ev for ev in cal.upcoming(hours=24)
                if ev.impact == "High"
            ][:5]
            if today_high:
                lines.append("⚠️ *News high impact aujourd'hui* :")
                for ev in today_high:
                    t = ev.datetime_utc.strftime("%H:%M")
                    lines.append(f"  • `{t}` {ev.currency} — {ev.title[:40]}")
            else:
                lines.append("✅ Pas d'event high impact aujourd'hui")
        except Exception:
            pass

        lines.append("")

        # Killzones rappel
        lines.append("⏰ *Killzones UTC* :")
        lines.append("  • London    : 07h-10h")
        lines.append("  • NY AM     : 13h30-15h")
        lines.append("  • NY Lunch  : 16h-17h")
        lines.append("  • NY PM     : 18h30-20h30")

        lines.append("")

        # Cumul semaine
        week_trades = self._trades_last_n_days(7)
        w_stats = self._compute_stats(week_trades)
        if w_stats["n"] > 0:
            lines.append(f"📅 *Cette semaine* : {w_stats['n']} trades | "
                          f"WR {w_stats['win_rate']:.0%} | {w_stats['r']:+.1f}R")

        # Balance vs target
        current_balance = self._estimate_balance()
        target = self.settings.account_balance * (1 + self.rules.get("profit_target_pct", 0) / 100)
        to_target = target - current_balance
        if to_target > 0:
            lines.append(f"\n🎯 *FTMO Target* : {target:,.0f}$ → reste {to_target:+,.0f}$ "
                          f"({to_target/self.settings.account_balance*100:+.1f}%)")
        else:
            lines.append(f"\n✅ *FTMO TARGET ATTEINT* ! +{-to_target:,.0f}$")

        return "\n".join(lines)

    # ==================================================================
    # EVENING RECAP (CLEAN - v2026.04.20, no legacy "Hidden Alert")
    # ==================================================================
    def evening_recap(self) -> str:
        now = datetime.utcnow()
        today = now.date()
        t_trades = self._trades_on_date(today)
        t_stats = self._compute_stats(t_trades)

        # Paris time for header
        try:
            from src.utils.tz_display import format_paris
            paris_time = format_paris(fmt="%H:%M")
        except Exception:
            paris_time = (now + timedelta(hours=2)).strftime("%H:%M")

        lines = [
            f"🏙️ *RECAP DU SOIR*",
            f"{today.strftime('%A %d/%m/%Y')}  ·  {paris_time} Paris\n",
        ]

        # ======= SIGNAUX DU JOUR =======
        closed_today = [t for t in t_trades if getattr(t, "is_closed", False)]
        count_s_aplus = sum(1 for t in t_trades if getattr(t, "tier", None) in ("S", "A+"))
        count_a = sum(1 for t in t_trades if getattr(t, "tier", None) == "A")
        count_b = sum(1 for t in t_trades if getattr(t, "tier", None) == "B")

        lines.append(f"🎯 *SIGNAUX DU JOUR*")
        lines.append(f"Total: {t_stats['n']}")
        if t_stats["n"] > 0:
            lines.append(f"🏆 A+/S: {count_s_aplus}    ⭐ A: {count_a}    ⚡ B: {count_b}")
        else:
            lines.append(f"🏆 A+/S: 0    ⭐ A: 0    ⚡ B: 0")
        lines.append("")

        # ======= PROPFIRM =======
        daily_limit = self.rules["max_daily_loss_pct"]
        target_pct = self.rules.get("profit_target_pct", 10.0)

        pnl_pct_day = t_stats["pnl_pct"] if t_stats["n"] > 0 else 0.0
        dd_pct = max(0, -pnl_pct_day) if pnl_pct_day < 0 else 0

        # Calculate objective % accomplished (week-to-date)
        week_trades_local = self._trades_last_n_days(7)
        w_stats_local = self._compute_stats(week_trades_local)
        accompli_pct = min(100, max(0, (w_stats_local["pnl_pct"] / target_pct * 100))) if target_pct > 0 else 0

        lines.append(f"🏛️ *PROPFIRM*")
        lines.append(f"P&L jour:   {pnl_pct_day:+.2f}%")
        lines.append(f"Drawdown:   {dd_pct:.2f}% (limit -{daily_limit}%)")
        lines.append(f"Objectif:   {accompli_pct:.1f}% accompli (target +{target_pct}%)")
        lines.append("")

        # ======= TRADE DETAIL (only if trades today) =======
        if t_stats["n"] > 0:
            lines.append(f"📊 *Performance*")
            lines.append(f"  WR : *{t_stats['win_rate']:.0%}*   R : *{t_stats['r']:+.2f}R*   PnL : *{t_stats['pnl']:+.0f}$*")

            if closed_today:
                best = max(closed_today, key=lambda t: t.pnl_r or 0)
                worst = min(closed_today, key=lambda t: t.pnl_r or 0)
                lines.append(f"🏆 Best  : {best.symbol} {best.side} {best.pnl_r:+.1f}R")
                lines.append(f"📉 Worst : {worst.symbol} {worst.side} {worst.pnl_r:+.1f}R")
            lines.append("")

        # ======= DEMAIN (killzones) =======
        lines.append(f"🕐 *DEMAIN*")
        lines.append(f"🇬🇧 London:  09:00 Paris  (07:00 UTC)")
        lines.append(f"🇺🇸 NY AM:   14:30 Paris  (12:30 UTC)")

        # ======= Weekly context (at bottom) =======
        if w_stats_local["n"] > 0:
            lines.append("")
            lines.append(f"📅 *Cumul 7j* : {w_stats_local['n']} trades | "
                          f"WR {w_stats_local['win_rate']:.0%} | "
                          f"{w_stats_local['r']:+.1f}R | "
                          f"{w_stats_local['pnl_pct']:+.2f}%")

        # ======= Closing (CLEAN - no "Hidden Alert" legacy) =======
        lines.append("")
        lines.append(f"💤 Bonne nuit David — discipline ✓")

        return "\n".join(lines)

    # ==================================================================
    # WEEKLY RECAP (Sunday)
    # ==================================================================
    def weekly_recap(self) -> str:
        week = self._trades_last_n_days(7)
        stats = self._compute_stats(week)
        closed = [t for t in week if t.is_closed]

        lines = [
            f"📅 *WEEKLY RECAP — Week {datetime.utcnow().isocalendar()[1]}*\n",
        ]

        if stats["n"] == 0:
            lines.append("Aucun trade cette semaine.")
            return "\n".join(lines)

        lines.append(f"📊 *Total 7 jours* : {stats['n']} trades")
        lines.append(f"  • WR : *{stats['win_rate']:.0%}*")
        lines.append(f"  • PnL : *{stats['pnl']:+,.0f} USD* ({stats['pnl_pct']:+.2f}%)")
        lines.append(f"  • R : *{stats['r']:+.2f}R*")
        lines.append(f"  • Expectancy : {stats['r'] / stats['n']:+.3f}R/trade")

        lines.append("")

        # Par jour
        lines.append("📅 *Breakdown par jour* :")
        for i in range(7):
            d = (datetime.utcnow() - timedelta(days=i)).date()
            dt_trades = [t for t in closed
                          if t.exit_time and datetime.fromisoformat(t.exit_time).date() == d]
            if dt_trades:
                d_pnl = sum(t.pnl_usd for t in dt_trades)
                d_wr = sum(1 for t in dt_trades if t.pnl_usd > 0) / len(dt_trades)
                icon = "🟢" if d_pnl > 0 else ("🔴" if d_pnl < 0 else "⚪")
                lines.append(f"  {icon} {d.strftime('%a %d')} : {len(dt_trades)}t | "
                              f"WR {d_wr:.0%} | {d_pnl:+.0f}$")

        lines.append("")

        # Top assets
        by_asset = {}
        for t in closed:
            by_asset.setdefault(t.symbol, []).append(t)
        asset_stats = []
        for sym, ts in by_asset.items():
            pnl = sum(t.pnl_usd for t in ts)
            wr = sum(1 for t in ts if t.pnl_usd > 0) / len(ts)
            asset_stats.append((sym, len(ts), wr, pnl))
        asset_stats.sort(key=lambda x: -x[3])
        if asset_stats:
            lines.append("🏆 *Top assets* :")
            for sym, n, wr, pnl in asset_stats[:5]:
                lines.append(f"  • {sym} : {n}t | WR {wr:.0%} | {pnl:+,.0f}$")

        # Project FTMO
        balance = self.settings.account_balance + stats["pnl"]
        target = self.settings.account_balance * 1.10
        if balance >= target:
            lines.append(f"\n🎯 *FTMO 10% TARGET ATTEINT !*")
        else:
            remaining = target - balance
            if stats["pnl"] > 0:
                weeks = remaining / stats["pnl"]
                lines.append(f"\n🎯 Au rythme actuel : target dans ~{weeks:.1f} semaines")

        return "\n".join(lines)

    # ==================================================================
    # MONTHLY RECAP
    # ==================================================================
    def monthly_recap(self) -> str:
        month = self._trades_last_n_days(30)
        stats = self._compute_stats(month)

        lines = [
            f"📆 *MONTHLY RECAP — {datetime.utcnow().strftime('%B %Y')}*\n",
        ]

        if stats["n"] == 0:
            lines.append("Aucun trade ce mois.")
            return "\n".join(lines)

        lines.append(f"📊 *30 jours* : *{stats['n']} trades*")
        lines.append(f"  • WR : *{stats['win_rate']:.1%}*")
        lines.append(f"  • PnL : *{stats['pnl']:+,.0f} USD* ({stats['pnl_pct']:+.2f}%)")
        lines.append(f"  • R : *{stats['r']:+.2f}R*")
        lines.append(f"  • Trades/semaine : {stats['n'] / 4.3:.1f}")

        lines.append("")

        # ML calibration
        with_ml = [t for t in month if t.is_closed and t.ml_prob_win_at_signal]
        if with_ml:
            avg_predicted = sum(t.ml_prob_win_at_signal for t in with_ml) / len(with_ml)
            actual_wr = sum(1 for t in with_ml if t.pnl_usd > 0) / len(with_ml)
            delta = actual_wr - avg_predicted
            lines.append(f"🎯 *ML Calibration* :")
            lines.append(f"  • Prédit : {avg_predicted:.0%}")
            lines.append(f"  • Réel   : {actual_wr:.0%}")
            icon = "✅" if abs(delta) < 0.10 else ("⚠️" if delta < 0 else "🚀")
            lines.append(f"  • Écart  : {delta:+.0%} {icon}")

        return "\n".join(lines)

    # ==================================================================
    # HELPERS
    # ==================================================================
    def _trades_on_date(self, date) -> List:
        all_trades = self.journal.load_all()
        return [
            t for t in all_trades
            if t.exit_time and datetime.fromisoformat(t.exit_time).date() == date
        ]

    def _trades_last_n_days(self, n: int) -> List:
        all_trades = self.journal.load_all()
        cutoff = datetime.utcnow() - timedelta(days=n)
        return [
            t for t in all_trades
            if t.exit_time and datetime.fromisoformat(t.exit_time) >= cutoff
        ]

    def _compute_stats(self, trades: List) -> Dict:
        closed = [t for t in trades if t.is_closed]
        if not closed:
            return {"n": 0, "wins": 0, "win_rate": 0, "pnl": 0, "pnl_pct": 0, "r": 0}
        wins = sum(1 for t in closed if t.pnl_usd > 0)
        pnl = sum(t.pnl_usd for t in closed)
        r = sum(t.pnl_r or 0 for t in closed)
        pnl_pct = pnl / self.settings.account_balance * 100
        return {
            "n": len(closed),
            "wins": wins,
            "win_rate": wins / len(closed),
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "r": r,
        }

    def _estimate_balance(self) -> float:
        closed = [t for t in self.journal.load_all() if t.is_closed]
        total_pnl = sum(t.pnl_usd for t in closed)
        return self.settings.account_balance + total_pnl
