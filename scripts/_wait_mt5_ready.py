"""Helper : poll mt5.initialize() with credentials until OK or timeout (called by DEPLOY_MASTER.ps1)

Handles the classic IPC timeout when MT5 Desktop is still loading.
Retries every 2 seconds up to MT5_TIMEOUT_SEC (default 60).
"""
from __future__ import annotations
import os
import sys
import json
import time
from pathlib import Path

try:
    import MetaTrader5 as mt5
except ImportError:
    print("FAIL: MetaTrader5 package not installed")
    sys.exit(1)

mt5_json = os.environ.get("MT5_JSON", "user_data/mt5_accounts.json")
timeout = int(os.environ.get("MT5_TIMEOUT_SEC", "60"))
mt5_path = os.environ.get("MT5_PATH", "")  # optional explicit terminal64.exe path

try:
    with open(mt5_json) as f:
        data = json.load(f)
    acc = data["accounts"][0]
except Exception as e:
    print("FAIL: cannot read {0} ({1})".format(mt5_json, e))
    sys.exit(1)

start = time.time()
attempt = 0
last_err = "unknown"

while time.time() - start < timeout:
    attempt += 1
    try:
        init_kwargs = dict(
            login=int(acc["login"]),
            password=acc["password"],
            server=acc["server"],
            timeout=10000,  # 10 sec per attempt
        )
        if mt5_path:
            init_kwargs["path"] = mt5_path

        ok = mt5.initialize(**init_kwargs)
        if ok:
            info = mt5.account_info()
            if info:
                print("Connected {0} balance=${1:.2f} server={2} (attempt {3})".format(
                    info.login, info.balance, info.server, attempt
                ))
                mt5.shutdown()
                sys.exit(0)
            else:
                last_err = "initialize OK but account_info() empty"
        else:
            last_err = str(mt5.last_error())
    except Exception as e:
        last_err = "{0}: {1}".format(type(e).__name__, e)

    # cleanup before retry
    try:
        mt5.shutdown()
    except Exception:
        pass

    time.sleep(2)

print("FAIL: MT5 not ready after {0}s, {1} attempts (last err: {2})".format(
    timeout, attempt, last_err
))
sys.exit(1)
