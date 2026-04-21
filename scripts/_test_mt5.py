"""Helper : test MT5 connection using credentials from mt5_accounts.json (env var MT5_JSON)"""
import os
import sys
import json

try:
    import MetaTrader5 as mt5
except ImportError:
    print("FAIL: MetaTrader5 package not installed")
    sys.exit(1)

mt5_json = os.environ.get("MT5_JSON", "user_data/mt5_accounts.json")

try:
    with open(mt5_json) as f:
        data = json.load(f)
    acc = data["accounts"][0]
    ok = mt5.initialize(
        login=int(acc["login"]),
        password=acc["password"],
        server=acc["server"]
    )
    if ok:
        info = mt5.account_info()
        print("Connected {0} balance=${1:.2f}".format(info.login, info.balance))
    else:
        print("FAIL: {0}".format(mt5.last_error()))
    mt5.shutdown()
except Exception as e:
    print("FAIL: {0}".format(e))
    sys.exit(1)
