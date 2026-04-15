"""
Desktop notifications natives (macOS via osascript, Linux via notify-send).
Pas de dépendance externe.
"""
from __future__ import annotations

import subprocess
import platform
import shutil


def notify(title: str, message: str, sound: bool = True) -> bool:
    """Affiche une notification native. Retourne True si envoyée."""
    system = platform.system()
    try:
        if system == "Darwin":
            # macOS — osascript
            escaped_msg = message.replace('"', '\\"').replace("\n", " ")
            escaped_title = title.replace('"', '\\"')
            sound_clause = ' sound name "Glass"' if sound else ""
            script = f'display notification "{escaped_msg}" with title "{escaped_title}"{sound_clause}'
            subprocess.run(["osascript", "-e", script], check=True, capture_output=True, timeout=5)
            return True
        elif system == "Linux":
            if shutil.which("notify-send"):
                subprocess.run(
                    ["notify-send", "-u", "normal", title, message],
                    check=True, capture_output=True, timeout=5,
                )
                return True
        elif system == "Windows":
            # Fallback Windows via PowerShell toast (Win10+)
            script = f"""
$title='{title}'; $msg='{message}';
Add-Type -AssemblyName System.Windows.Forms;
$notify = New-Object System.Windows.Forms.NotifyIcon;
$notify.Icon = [System.Drawing.SystemIcons]::Information;
$notify.Visible = $true;
$notify.ShowBalloonTip(5000, $title, $msg, [System.Windows.Forms.ToolTipIcon]::Info);
"""
            subprocess.run(
                ["powershell", "-Command", script],
                check=True, capture_output=True, timeout=5,
            )
            return True
    except Exception:
        pass
    return False


def notify_signal(signal) -> bool:
    """Envoie une notification pour un LiveSignal."""
    tier = signal.tier
    side_emoji = "🟢" if signal.side == "long" else "🔴"
    title = f"{tier} • {signal.symbol} {signal.ltf}"
    p = f"{signal.ml_prob_win:.0%}" if signal.ml_prob_win else "n/a"
    msg = (f"{side_emoji} {signal.side.upper()} @ {signal.entry:.4f}  "
           f"RR {signal.risk_reward:.1f}  P(win) {p}  {signal.killzone}")
    return notify(title, msg)


if __name__ == "__main__":
    ok = notify("ICT Framework", "Notification test — tout fonctionne ✓")
    print(f"Notification sent: {ok}")
