"""Helper : delete any active Telegram webhook on the bot token (fixes 409 Conflict).

Called by DEPLOY_MASTER.ps1 before launching the bot.
Reading TELEGRAM_BOT_TOKEN from .env (or env var).
Also drops pending updates to start clean.
"""
from __future__ import annotations
import os
import sys
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env_file():
    """Load .env file into os.environ without overwriting existing vars."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except Exception as e:
        print("WARN: cannot parse .env ({0})".format(e))


load_env_file()
token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

if not token:
    print("WARN: no TELEGRAM_BOT_TOKEN in .env - skipping webhook cleanup")
    sys.exit(0)

url = "https://api.telegram.org/bot{0}/deleteWebhook?drop_pending_updates=true".format(token)

try:
    with urllib.request.urlopen(url, timeout=10) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    if body.get("ok"):
        print("Telegram webhook deleted (drop_pending_updates=true)")
        sys.exit(0)
    else:
        print("WARN: deleteWebhook returned {0}".format(body.get("description", "unknown")))
        sys.exit(0)  # non-fatal
except Exception as e:
    print("WARN: deleteWebhook call failed ({0}) - bot may still work".format(e))
    sys.exit(0)  # non-fatal
