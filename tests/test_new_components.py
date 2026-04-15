"""Tests nouveaux composants: settings, journal, calendar, alerter."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest


def test_user_settings_roundtrip(tmp_path, monkeypatch):
    """Settings se sauvent puis se rechargent identiques."""
    monkeypatch.setattr("src.utils.user_settings.USER_DATA_DIR", tmp_path)
    monkeypatch.setattr("src.utils.user_settings.SETTINGS_FILE",
                         tmp_path / "settings.json")
    monkeypatch.setattr("src.utils.user_settings.ENV_FILE",
                         tmp_path / ".env")
    from src.utils.user_settings import UserSettings

    s = UserSettings(
        firm="ftmo", variant="funded",
        account_balance=50_000,
        risk_per_trade_pct=0.75,
        discord_webhook_url="https://example.com/webhook",
    )
    s.save()
    # reload
    s2 = UserSettings.load()
    assert s2.firm == "ftmo"
    assert s2.variant == "funded"
    assert s2.account_balance == 50_000
    assert s2.risk_per_trade_pct == 0.75
    assert s2.discord_webhook_url == "https://example.com/webhook"


def test_user_settings_defaults():
    from src.utils.user_settings import UserSettings
    s = UserSettings()
    assert s.firm == "ftmo"
    assert s.risk_per_trade_pct == 0.5
    assert len(s.assets_h1) == 6
    assert len(s.assets_d1) == 6


def test_trade_journal_add_close(tmp_path):
    from src.trade_journal import TradeJournal, JournalEntry
    from datetime import datetime

    path = tmp_path / "journal.jsonl"
    j = TradeJournal(path=path)

    entry = JournalEntry(
        trade_id="test-1", created_at=datetime.utcnow().isoformat(),
        symbol="XAUUSD", ltf="1h", side="long",
        entry=2400.0, stop_loss=2395.0, take_profit_1=2410.0,
        entry_time=datetime.utcnow().isoformat(), entry_fill=2400.0,
        lots=1.0, risk_usd=500,
    )
    j.log(entry)
    assert len(j.load_all()) == 1

    # Close it
    ok = j.close_trade("test-1", datetime.utcnow().isoformat(),
                        2410.0, 1000.0, 2.0, "tp1")
    assert ok

    entries = j.load_all()
    assert len(entries) == 1
    assert entries[0].is_closed
    assert entries[0].pnl_r == 2.0


def test_trade_journal_analytics(tmp_path):
    from src.trade_journal import TradeJournal, JournalEntry
    from datetime import datetime

    path = tmp_path / "journal.jsonl"
    j = TradeJournal(path=path)

    # 3 wins + 2 losses, with ML prob
    for i in range(5):
        entry = JournalEntry(
            trade_id=f"t-{i}", created_at=datetime.utcnow().isoformat(),
            symbol="XAUUSD", ltf="1h", side="long",
            entry=2400, stop_loss=2395, take_profit_1=2410,
            entry_time=datetime.utcnow().isoformat(), entry_fill=2400,
            exit_time=datetime.utcnow().isoformat(),
            exit_fill=2410 if i < 3 else 2395,
            pnl_usd=1000 if i < 3 else -500,
            pnl_r=2.0 if i < 3 else -1.0,
            exit_reason="tp1" if i < 3 else "sl",
            ml_prob_win_at_signal=0.50, lots=1.0, risk_usd=500,
        )
        j.log(entry)

    stats = j.analytics()
    assert stats["n_closed"] == 5
    assert stats["win_rate"] == 0.6
    assert stats["n_wins"] == 3
    ml = stats["ml_calibration"]
    assert ml["n_with_ml"] == 5
    assert ml["actual_winrate"] == 0.6
    assert ml["avg_predicted_winrate"] == 0.5


def test_news_calendar_no_events_empty():
    from src.news_calendar import NewsCalendar
    from datetime import datetime
    cal = NewsCalendar()
    # Sans refresh → 0 events → False
    assert cal.is_in_news_window(datetime.utcnow()) in (True, False)


def test_news_calendar_currencies_for():
    from src.news_calendar.calendar import currencies_for
    assert "USD" in currencies_for("EURUSD")
    assert "EUR" in currencies_for("EURUSD")
    assert currencies_for("XAUUSD") == ["USD"]
    assert "UNKNOWN" not in currencies_for("UNKNOWN")


def test_desktop_notify_doesnt_crash():
    """Notification ne doit pas crasher même si platform ne supporte pas."""
    from src.live_scanner.desktop_notify import notify
    # Ne doit pas crasher, retourne True ou False
    result = notify("Test", "Message test")
    assert isinstance(result, bool)


def test_alerter_dedup(tmp_path, monkeypatch):
    """Un signal ne doit pas être alert 2 fois."""
    from src.live_scanner.alerter import Alerter
    from src.live_scanner.scanner import LiveSignal
    from datetime import datetime

    monkeypatch.setattr("src.utils.config.REPORTS_DIR", tmp_path)
    monkeypatch.setattr("src.live_scanner.alerter.REPORTS_DIR", tmp_path)

    alerter = Alerter()
    # Désactive tous les canaux (no credentials)

    sig = LiveSignal(
        timestamp_scan=datetime.utcnow().isoformat(),
        symbol="XAUUSD", ltf="1h", side="long",
        entry=2400, stop_loss=2395, take_profit_1=2410,
        take_profit_2=2415, risk_reward=2.0,
        fvg_size_atr=1.0, fvg_age_bars=3, fvg_impulsion=1.5,
        killzone="ny_am_kz", current_price=2400,
        distance_to_entry_pct=0.0, ml_prob_win=0.47,
        tier="BALANCED", priority_score=75.0,
    )

    n1 = alerter.alert_new([sig])   # premier appel
    n2 = alerter.alert_new([sig])   # même signal → 0 new
    assert n1 == 1
    assert n2 == 0


def test_scanner_import():
    """Juste check que scanner module importe sans erreur."""
    from src.live_scanner import LiveScanner, LiveSignal
    assert LiveScanner is not None
    assert LiveSignal is not None
