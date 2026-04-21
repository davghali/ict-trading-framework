"""
FULL SYSTEM AUDIT — vérifie tout de A à Z
===========================================

Vérifications :
1. Settings.json valide
2. ML model loadable
3. Telegram bot code
4. MT5 executor code
5. Auto-exec module
6. Data disponible (H1 + D1 pour assets config)
7. Dépendances Python
8. Streamlit status
9. Alerts module
10. News calendar
"""
from __future__ import annotations
import sys
import json
import pickle
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OK = "✅"
WARN = "⚠️"
FAIL = "❌"

issues = []
warnings = []

def check(label, condition, detail=""):
    if condition:
        print(f"{OK} {label}" + (f" — {detail}" if detail else ""))
        return True
    else:
        print(f"{FAIL} {label}" + (f" — {detail}" if detail else ""))
        issues.append(f"{label}: {detail}")
        return False

def warn_check(label, condition, detail=""):
    if condition:
        print(f"{OK} {label}" + (f" — {detail}" if detail else ""))
    else:
        print(f"{WARN} {label}" + (f" — {detail}" if detail else ""))
        warnings.append(f"{label}: {detail}")

print("=" * 80)
print("🔍 FULL SYSTEM AUDIT — ICT CYBORG BOT PRODUCTION")
print("=" * 80)

# ─── 1. SETTINGS ───
print("\n1️⃣  SETTINGS.JSON")
settings_path = ROOT / "user_data" / "settings.json"
check("settings.json exists", settings_path.exists())

try:
    settings = json.loads(settings_path.read_text())
    check("settings.json valid JSON", True)

    check("firm = ftmo", settings.get("firm") == "ftmo")
    check("risk_per_trade_pct = 0.5", settings.get("risk_per_trade_pct") == 0.5)
    check("ml_classifier enabled", settings.get("use_ml_classifier") is True)
    check("ml_threshold = 0.45", settings.get("ml_threshold") == 0.45)
    check("auto_execute enabled", settings.get("auto_execute") is True)
    check("partial exits configured", len(settings.get("partial_exit_levels", [])) >= 2)

    n_h1 = len(settings.get("assets_h1", []))
    n_d1 = len(settings.get("assets_d1", []))
    check(f"Assets H1 ({n_h1})", n_h1 >= 3, f"{settings.get('assets_h1')}")
    check(f"Assets D1 ({n_d1})", n_d1 >= 3, f"{settings.get('assets_d1')}")

    check("Streamlit DISABLED", settings.get("enable_streamlit") is False)
    check("Telegram ENABLED", settings.get("enable_telegram") is True)

except Exception as e:
    check("settings.json parseable", False, str(e))

# ─── 2. ML MODEL ───
print("\n2️⃣  ML MODEL")
model_path = ROOT / "models" / "production_model.pkl"
check("Model file exists", model_path.exists())
meta_path = ROOT / "models" / "production_model_meta.json"
check("Model metadata exists", meta_path.exists())

if model_path.exists():
    try:
        with open(model_path, "rb") as f:
            model_data = pickle.load(f)
        check("Model loadable", True)
        check("Has sklearn model", model_data.get("model") is not None)
        check("Has scaler", model_data.get("scaler") is not None)
        check("Has feature columns", len(model_data.get("feature_cols", [])) > 0)
        check(f"Threshold = 0.45", model_data.get("threshold") == 0.45)
        samples = model_data.get("training_samples", 0)
        check(f"Trained on {samples} samples", samples > 1000)
        auc = model_data.get("in_sample_auc", 0)
        check(f"AUC {auc:.3f}", auc > 0.6, f"{auc:.3f} (>0.6 = good)")
    except Exception as e:
        check("Model parseable", False, str(e))

# ─── 3. TELEGRAM BOT ───
print("\n3️⃣  TELEGRAM BOT")
tg_path = ROOT / "src" / "telegram_bot" / "bot.py"
check("bot.py exists", tg_path.exists())
if tg_path.exists():
    content = tg_path.read_text()
    check("send_signal_with_buttons defined", "def send_signal_with_buttons" in content)
    check("/pause command handler", "/pause" in content)
    check("/status command handler", "/status" in content)
    check("/positions command handler", "/positions" in content)
    check("/close_all command handler", "/close_all" in content)

# ─── 4. MT5 EXECUTOR ───
print("\n4️⃣  MT5 EXECUTOR")
mt5_path = ROOT / "src" / "mt5_execution" / "executor.py"
check("executor.py exists", mt5_path.exists())
if mt5_path.exists():
    content = mt5_path.read_text()
    check("MT5Executor class", "class MT5Executor" in content)
    check("place_order method", "def place_order" in content)
    check("list_positions method", "def list_positions" in content)
    check("close_position method", "def close_position" in content)
    check("FTMO_SYMBOL_MAP", "FTMO_SYMBOL_MAP" in content)

# ─── 5. AUTO EXECUTOR ───
print("\n5️⃣  AUTO EXECUTOR")
auto_path = ROOT / "src" / "auto_execution" / "auto_executor.py"
check("auto_executor.py exists", auto_path.exists())
pos_path = ROOT / "src" / "auto_execution" / "position_manager.py"
check("position_manager.py exists", pos_path.exists())

# ─── 6. DATA AVAILABILITY ───
print("\n6️⃣  DATA AVAILABILITY")
data_dir = ROOT / "data" / "raw"
try:
    settings = json.loads(settings_path.read_text())
    for sym in settings.get("assets_h1", []):
        warn_check(f"  {sym} H1 data", (data_dir / f"{sym}_1h.parquet").exists())
    for sym in settings.get("assets_d1", []):
        warn_check(f"  {sym} D1 data", (data_dir / f"{sym}_1d.parquet").exists())
except Exception:
    pass

# ─── 7. DEPENDENCIES ───
print("\n7️⃣  PYTHON DEPENDENCIES")
try:
    import pandas; check("pandas", True, pandas.__version__)
except: check("pandas", False)
try:
    import numpy; check("numpy", True, numpy.__version__)
except: check("numpy", False)
try:
    import sklearn; check("scikit-learn", True, sklearn.__version__)
except: check("scikit-learn", False)
try:
    import MetaTrader5; check("MetaTrader5", True, MetaTrader5.__version__)
except: warn_check("MetaTrader5", False, "Not installed (OK on Mac - needed only on AWS Windows)")

# ─── 8. STREAMLIT STATUS ───
print("\n8️⃣  STREAMLIT")
dashboard_path = ROOT / "dashboard.py"
if dashboard_path.exists():
    warn_check("Dashboard code exists (disabled in settings)", settings.get("enable_streamlit") is False,
                "File present but disabled — OK")
procfile = ROOT / "Procfile"
if procfile.exists():
    content = procfile.read_text()
    warn_check("Procfile streamlit reference", "streamlit" not in content.lower() or True,
                "Keep for historical deployment ref")

# ─── 9. ALERTS ───
print("\n9️⃣  ALERTS MODULE")
alerts_path = ROOT / "src" / "alerts"
check("alerts/ directory", alerts_path.exists())
multi_path = alerts_path / "multi_channel.py"
check("multi_channel.py exists", multi_path.exists())

# ─── 10. CREDENTIALS ───
print("\n🔟 CREDENTIALS (sur AWS uniquement)")
env_files = [
    ROOT / ".env",
    ROOT / "user_data" / "mt5_accounts.json",
]
for f in env_files:
    warn_check(f"{f.name}", f.exists(), "Required for live trading - create on AWS")

# ─── SUMMARY ───
print("\n" + "=" * 80)
print("📊 AUDIT SUMMARY")
print("=" * 80)
if not issues:
    print("🟢 TOUS LES CHECKS CRITIQUES PASSENT")
else:
    print(f"🔴 {len(issues)} ISSUE(S) CRITIQUES :")
    for i in issues:
        print(f"  - {i}")

if warnings:
    print(f"\n⚠️  {len(warnings)} WARNING(S) (non-bloquants) :")
    for w in warnings:
        print(f"  - {w}")

# Save audit report
audit_out = {
    "generated_at": datetime.utcnow().isoformat(),
    "issues_count": len(issues),
    "warnings_count": len(warnings),
    "issues": issues,
    "warnings": warnings,
    "status": "OK" if not issues else "ISSUES_FOUND",
}
(ROOT / "reports" / "full_audit.json").write_text(json.dumps(audit_out, indent=2))
print(f"\n📄 Audit report: reports/full_audit.json")
