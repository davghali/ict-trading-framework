"""Helper : find MetaTrader 5 terminal64.exe path on Windows (called by DEPLOY_MASTER.ps1)"""
from __future__ import annotations
import sys
from pathlib import Path

# Common install paths for MT5 (FTMO, ICMarkets, Pepperstone, default MQ, etc.)
CANDIDATES = [
    r"C:\Program Files\MetaTrader 5\terminal64.exe",
    r"C:\Program Files\FTMO MetaTrader 5\terminal64.exe",
    r"C:\Program Files\MetaTrader 5 - FTMO\terminal64.exe",
    r"C:\Program Files\FTMO MT5 Terminal\terminal64.exe",
    r"C:\Program Files\MetaTrader 5 IC Markets\terminal64.exe",
    r"C:\Program Files\MetaTrader 5 ICMarkets\terminal64.exe",
    r"C:\Program Files\MetaTrader 5 Pepperstone\terminal64.exe",
    r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe",
]


def scan_program_files():
    """Fallback : scan Program Files for any MT5 install."""
    results = []
    for pf in [r"C:\Program Files", r"C:\Program Files (x86)"]:
        p = Path(pf)
        if not p.exists():
            continue
        for sub in p.iterdir():
            if not sub.is_dir():
                continue
            name_upper = sub.name.upper()
            if "METATRADER 5" in name_upper or "MT5" in name_upper or "FTMO" in name_upper:
                term = sub / "terminal64.exe"
                if term.exists():
                    results.append(str(term))
    return results


# Try known paths first
for candidate in CANDIDATES:
    if Path(candidate).exists():
        print(candidate)
        sys.exit(0)

# Fallback scan
scanned = scan_program_files()
if scanned:
    print(scanned[0])
    sys.exit(0)

print("FAIL: MT5 terminal64.exe not found in any known path")
sys.exit(1)
