#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# HOT STANDBY FAILOVER — ICT CYBORG
# -----------------------------------------------------------------------------
# Objectif : si AWS Windows (primary) tombe, le VM GCP Linux (secondary)
# active automatiquement le scanner-only mode (alerts Telegram sans MT5 execution).
#
# MT5 execution reste exclusif à AWS (Windows). Mais les signaux/alertes
# continuent à tourner depuis GCP si AWS down.
#
# Usage : à lancer en cron /2min sur le VM GCP.
# -----------------------------------------------------------------------------

set -euo pipefail

PRIMARY_HEALTH_URL="${PRIMARY_HEALTH_URL:-https://ict-quant-david.streamlit.app}"
AWS_HEALTH_URL="${AWS_HEALTH_URL:-http://<AWS_IP>:8501/healthz}"   # à remplir
FRAMEWORK_DIR="${FRAMEWORK_DIR:-/home/davidghali/ict-trading-framework}"
LOG_FILE="${LOG_FILE:-/var/log/ict-failover.log}"
PID_FILE="/tmp/ict-failover.pid"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" >> "$LOG_FILE"; }

# Check if failover scanner already running
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        # Already running : check if AWS is back
        if curl -fsS --max-time 10 "$AWS_HEALTH_URL" > /dev/null 2>&1; then
            log "AWS recovered → stopping failover scanner (PID $PID)"
            kill "$PID" 2>/dev/null || true
            rm -f "$PID_FILE"
            # Send recovery notification
            if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
                curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
                    -d "chat_id=$TELEGRAM_CHAT_ID" \
                    -d "text=✅ AWS RECOVERED — failover scanner stopped" > /dev/null
            fi
        fi
        exit 0
    else
        rm -f "$PID_FILE"
    fi
fi

# Check AWS health
if curl -fsS --max-time 10 "$AWS_HEALTH_URL" > /dev/null 2>&1; then
    log "AWS healthy, no action needed"
    exit 0
fi

# Second check : confirm AWS down via Streamlit proxy
if curl -fsS --max-time 10 "$PRIMARY_HEALTH_URL" > /dev/null 2>&1; then
    # Streamlit up but direct AWS down → might be RDP whitelist issue, not real outage
    log "AWS direct unreachable but Streamlit up — likely network filter, no failover"
    exit 0
fi

# AWS is really down — activate failover
log "AWS DOWN confirmed — activating scanner-only failover"

if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
    curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
        -d "chat_id=$TELEGRAM_CHAT_ID" \
        -d "text=🟠 AWS DOWN — GCP failover activated (scanner-only, no MT5 exec)" > /dev/null
fi

# Launch scanner in scanner-only mode (no MT5 exec)
cd "$FRAMEWORK_DIR"
nohup python3 run_cyborg.py --scanner-only >> "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
log "Failover scanner started PID $(cat $PID_FILE)"
