#!/usr/bin/env bash
# VPS DEPLOYMENT — déploie ICT Cyborg sur un serveur Linux (Oracle Cloud Free / AWS / etc.)
# À exécuter UNE FOIS sur le VPS (SSH) après clone du repo.
#
# Usage sur le VPS :
#   git clone https://github.com/davghali/ict-trading-framework.git
#   cd ict-trading-framework
#   bash deployment/vps/setup_vps.sh

set -e

echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║  🔴 ICT CYBORG — VPS DEPLOYMENT                              ║"
echo "╚═══════════════════════════════════════════════════════════════╝"

cd "$(dirname "$0")/../.."
ROOT="$(pwd)"

# ─── Detect OS / pkg manager
if command -v apt-get &>/dev/null; then
    PKG="apt-get"
    sudo apt-get update -qq
    sudo apt-get install -y python3 python3-pip python3-venv git curl jq cron
elif command -v yum &>/dev/null; then
    PKG="yum"
    sudo yum install -y python3 python3-pip git curl jq cronie
    sudo systemctl enable crond
    sudo systemctl start crond
fi

echo "✓ System packages installed"

# ─── Python env
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

echo "✓ Python dependencies installed"

# ─── Create user_data with secrets template
mkdir -p user_data reports/logs reports/ml_models
if [ ! -f "user_data/.env" ]; then
    cat > user_data/.env <<'EOF'
# Copy credentials from local Mac install
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
DISCORD_WEBHOOK_URL=
ANTHROPIC_API_KEY=
EOF
    echo "⚠️  Please fill user_data/.env with your credentials"
fi

if [ ! -f "user_data/settings.json" ]; then
    cat > user_data/settings.json <<'EOF'
{
  "firm": "ftmo",
  "variant": "classic_challenge",
  "account_balance": 100000,
  "risk_per_trade_pct": 0.5,
  "assets_h1": ["XAUUSD", "XAGUSD", "BTCUSD", "NAS100", "DOW30", "SPX500"],
  "assets_d1": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "ETHUSD"],
  "default_tier": "balanced",
  "min_alert_tier": "BALANCED",
  "scan_interval_minutes": 15,
  "skip_news_minutes_before": 30,
  "skip_news_minutes_after": 30,
  "skip_news_impact": "high"
}
EOF
fi

echo "✓ User data directories ready"

# ─── systemd services (Linux equivalent of macOS LaunchAgents)
SYSTEMD_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_DIR"

# Service 1 : Cyborg daemon
cat > "$SYSTEMD_DIR/ict-cyborg.service" <<EOF
[Unit]
Description=ICT Cyborg Trading Daemon
After=network.target

[Service]
Type=simple
WorkingDirectory=$ROOT
ExecStart=$ROOT/venv/bin/python $ROOT/run_cyborg.py
Restart=always
RestartSec=30
StandardOutput=append:$ROOT/reports/logs/cyborg.log
StandardError=append:$ROOT/reports/logs/cyborg.err

[Install]
WantedBy=default.target
EOF

# Service 2 : Supervisor
cat > "$SYSTEMD_DIR/ict-supervisor.service" <<EOF
[Unit]
Description=ICT Supervisor (recap + health + trade manager)
After=network.target

[Service]
Type=simple
WorkingDirectory=$ROOT
ExecStart=$ROOT/venv/bin/python $ROOT/run_supervisor.py
Restart=always
RestartSec=30
StandardOutput=append:$ROOT/reports/logs/supervisor.log
StandardError=append:$ROOT/reports/logs/supervisor.err

[Install]
WantedBy=default.target
EOF

# Reload + enable + start
systemctl --user daemon-reload
systemctl --user enable ict-cyborg.service
systemctl --user enable ict-supervisor.service
systemctl --user start ict-cyborg.service
systemctl --user start ict-supervisor.service

# Allow services to run when user not logged in
sudo loginctl enable-linger $USER 2>/dev/null || true

echo ""
echo "✓ systemd services installed and started"
systemctl --user status ict-cyborg.service --no-pager -l | head -5
echo ""
systemctl --user status ict-supervisor.service --no-pager -l | head -5
echo ""

# ─── Cron : weekly ML retrain (Sunday 21h UTC)
(crontab -l 2>/dev/null; echo "0 21 * * 0 cd $ROOT && $ROOT/venv/bin/python -m src.ml_retrain.retrainer >> $ROOT/reports/logs/ml_retrain.log 2>&1") | crontab -

echo "✓ Weekly ML retrain cron installed (Sunday 21h UTC)"

echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║  ✅ CYBORG VPS DEPLOYED — 24/7 ACTIVE                        ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""
echo "  📌 Services :"
echo "    systemctl --user status ict-cyborg"
echo "    systemctl --user status ict-supervisor"
echo ""
echo "  📌 Logs :"
echo "    tail -f $ROOT/reports/logs/cyborg.log"
echo "    tail -f $ROOT/reports/logs/supervisor.log"
echo ""
echo "  ⚠️  CRITICAL : edit user_data/.env with your credentials"
echo "     Then restart : systemctl --user restart ict-cyborg ict-supervisor"
