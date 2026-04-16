"""
HEALTH MONITOR — vérifie en continu que tout fonctionne.

Checks :
1. Daemon Cyborg running ? (PID + last log entry < 20 min)
2. Data fresh ? (fichier parquet < 24h)
3. Telegram bot répond ?
4. Dashboard cloud up ?
5. Disk space OK ?
6. Logs errors récentes ?

Si problème détecté → alerte Telegram immédiate.
Heartbeat toutes les heures : "✅ Cyborg alive"
"""
from __future__ import annotations

import os
import subprocess
import json
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict

from src.utils.logging_conf import get_logger
from src.utils.user_settings import apply_env

log = get_logger(__name__)


@dataclass
class HealthCheck:
    name: str
    ok: bool
    message: str = ""


@dataclass
class HealthReport:
    timestamp: str
    all_ok: bool
    checks: List[HealthCheck] = field(default_factory=list)

    def summary(self) -> str:
        icon = "✅" if self.all_ok else "⚠️"
        lines = [f"{icon} *Health check {self.timestamp}*"]
        for c in self.checks:
            i = "✅" if c.ok else "❌"
            lines.append(f"{i} {c.name} : {c.message}")
        return "\n".join(lines)


class HealthMonitor:

    def __init__(self):
        apply_env()
        self.root = Path(__file__).parents[2]
        self.log_dir = self.root / "reports" / "logs"
        self.data_dir = self.root / "data" / "raw"

    # ------------------------------------------------------------------
    def check_all(self) -> HealthReport:
        checks = []
        checks.append(self._check_cyborg_daemon())
        checks.append(self._check_data_freshness())
        checks.append(self._check_telegram_bot())
        checks.append(self._check_dashboard_cloud())
        checks.append(self._check_disk_space())
        checks.append(self._check_recent_errors())
        checks.append(self._check_journal_integrity())

        all_ok = all(c.ok for c in checks)
        return HealthReport(
            timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            all_ok=all_ok,
            checks=checks,
        )

    # ------------------------------------------------------------------
    def _check_cyborg_daemon(self) -> HealthCheck:
        try:
            res = subprocess.run(
                ["launchctl", "list", "com.ictframework.cyborg"],
                capture_output=True, text=True, timeout=5,
            )
            if "PID" not in res.stdout and "\"PID\" = " not in res.stdout:
                return HealthCheck("Cyborg daemon", False, "not running")
            log_file = self.log_dir / "cyborg.log"
            if log_file.exists():
                age_sec = time.time() - log_file.stat().st_mtime
                if age_sec > 20 * 60:
                    return HealthCheck("Cyborg daemon", False,
                                        f"log stale ({age_sec/60:.0f}min)")
            return HealthCheck("Cyborg daemon", True, "running, log fresh")
        except Exception as e:
            return HealthCheck("Cyborg daemon", False, str(e))

    def _check_data_freshness(self) -> HealthCheck:
        try:
            xau = self.data_dir / "XAUUSD_1h.parquet"
            if not xau.exists():
                return HealthCheck("Data freshness", False, "XAUUSD H1 missing")
            age_h = (time.time() - xau.stat().st_mtime) / 3600
            if age_h > 24:
                return HealthCheck("Data freshness", False, f"stale ({age_h:.0f}h)")
            return HealthCheck("Data freshness", True, f"fresh ({age_h:.1f}h)")
        except Exception as e:
            return HealthCheck("Data freshness", False, str(e))

    def _check_telegram_bot(self) -> HealthCheck:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if not token:
            return HealthCheck("Telegram bot", False, "no token configured")
        try:
            url = f"https://api.telegram.org/bot{token}/getMe"
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                if data.get("ok"):
                    return HealthCheck("Telegram bot", True,
                                        f"@{data['result']['username']} online")
                return HealthCheck("Telegram bot", False, str(data))
        except Exception as e:
            return HealthCheck("Telegram bot", False, str(e)[:50])

    def _check_dashboard_cloud(self) -> HealthCheck:
        try:
            url = "https://ict-quant-david.streamlit.app/_stcore/health"
            with urllib.request.urlopen(url, timeout=10) as resp:
                if resp.status == 200:
                    return HealthCheck("Dashboard cloud", True, "online")
                return HealthCheck("Dashboard cloud", False, f"HTTP {resp.status}")
        except Exception as e:
            return HealthCheck("Dashboard cloud", False, str(e)[:50])

    def _check_disk_space(self) -> HealthCheck:
        try:
            stat = os.statvfs(str(self.root))
            free_gb = stat.f_bavail * stat.f_frsize / 1024**3
            if free_gb < 1:
                return HealthCheck("Disk space", False, f"only {free_gb:.1f} GB free")
            return HealthCheck("Disk space", True, f"{free_gb:.1f} GB free")
        except Exception as e:
            return HealthCheck("Disk space", False, str(e))

    def _check_recent_errors(self) -> HealthCheck:
        try:
            err_file = self.log_dir / "cyborg.err"
            if not err_file.exists() or err_file.stat().st_size == 0:
                return HealthCheck("Recent errors", True, "none")
            # Only alert if errors in last 30 min
            age = time.time() - err_file.stat().st_mtime
            if age < 30 * 60:
                content = err_file.read_text()[-1000:]
                if "Traceback" in content or "Error" in content:
                    return HealthCheck("Recent errors", False, "errors in last 30min")
            return HealthCheck("Recent errors", True, "no recent errors")
        except Exception as e:
            return HealthCheck("Recent errors", False, str(e))

    def _check_journal_integrity(self) -> HealthCheck:
        try:
            from src.trade_journal import TradeJournal
            j = TradeJournal()
            entries = j.load_all()
            return HealthCheck("Journal", True, f"{len(entries)} entries")
        except Exception as e:
            return HealthCheck("Journal", False, str(e))

    # ------------------------------------------------------------------
    def auto_recover(self, report: HealthReport) -> None:
        """Tente de réparer les problèmes détectés."""
        for c in report.checks:
            if not c.ok:
                if "Cyborg daemon" in c.name:
                    try:
                        subprocess.run([
                            "launchctl", "unload",
                            str(Path.home() / "Library" / "LaunchAgents" / "com.ictframework.cyborg.plist")
                        ], check=False, capture_output=True)
                        time.sleep(2)
                        subprocess.run([
                            "launchctl", "load",
                            str(Path.home() / "Library" / "LaunchAgents" / "com.ictframework.cyborg.plist")
                        ], check=False, capture_output=True)
                        log.info("Auto-recovered cyborg daemon")
                    except Exception as e:
                        log.error(f"Auto-recover failed: {e}")
