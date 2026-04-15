#!/usr/bin/env bash
# ICT Institutional Framework — installer one-shot
# Usage: bash setup.sh

set -e

cd "$(dirname "$0")"

echo "═══════════════════════════════════════════════════════════════"
echo "  ICT Institutional Framework — Installation"
echo "═══════════════════════════════════════════════════════════════"

# 1. Check Python 3.9+
echo ""
echo "[1/5] Checking Python..."
python3 --version || { echo "✗ Python 3 not found"; exit 1; }
echo "   ✓ Python $(python3 --version | cut -d' ' -f2)"

# 2. Install dependencies
echo ""
echo "[2/5] Installing Python dependencies..."
python3 -m pip install --quiet --upgrade pip 2>/dev/null || true
python3 -m pip install --quiet -r requirements.txt streamlit 2>&1 | tail -5
echo "   ✓ Dependencies installed"

# 3. Initialize directories
echo ""
echo "[3/5] Creating directories..."
mkdir -p data/raw data/processed data/features reports/logs reports/ml_models user_data
echo "   ✓ Directory structure ready"

# 4. Download market data
echo ""
echo "[4/5] Downloading market data (may take 1-2 min)..."
python3 -c "
import sys, warnings; sys.path.insert(0, '.')
warnings.filterwarnings('ignore')
from src.data_engine import download_asset
from src.utils.types import Timeframe
from src.utils.config import list_instruments
for sym in list_instruments():
    for tf in [Timeframe.D1, Timeframe.H1]:
        try:
            download_asset(sym, tf, save=True)
        except Exception:
            pass
" 2>&1 | tail -5
echo "   ✓ Data downloaded"

# 5. Initialize user settings
echo ""
echo "[5/5] Initializing user preferences..."
python3 -c "
import sys; sys.path.insert(0, '.')
from src.utils.user_settings import UserSettings
s = UserSettings.load()
s.save()
"
echo "   ✓ Settings initialized in user_data/"

# Final check
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  VERIFICATION"
echo "═══════════════════════════════════════════════════════════════"
python3 run_verify.py 2>&1 | grep -v "^20" | tail -20

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  ✓ INSTALLATION TERMINÉE"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  Lance maintenant :"
echo ""
echo "    ./ict dashboard            # Interface visuelle (browser)"
echo "    ./ict scan                 # Scan one-shot CLI"
echo "    ./ict daemon               # Scanner continu + alertes"
echo "    ./ict status               # Health check"
echo "    ./ict install-autostart    # Auto-start au login macOS"
echo ""
echo "  Documentation : docs/QUICKSTART.md"
echo ""
