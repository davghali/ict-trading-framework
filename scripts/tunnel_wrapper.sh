#!/usr/bin/env bash
# tunnel_wrapper.sh — lance cloudflared tunnel et capture l'URL publique.
# L'URL est écrite dans user_data/public_url.txt et notifiée.

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
LOG="$ROOT/reports/logs/tunnel.log"
URL_FILE="$ROOT/user_data/public_url.txt"
CLOUDFLARED="$ROOT/bin/cloudflared"

mkdir -p "$(dirname "$LOG")"
mkdir -p "$(dirname "$URL_FILE")"

if [ ! -x "$CLOUDFLARED" ]; then
    echo "cloudflared not found at $CLOUDFLARED" >> "$LOG"
    exit 1
fi

# Wait for dashboard port to be up
for i in 1 2 3 4 5 6 7 8 9 10; do
    if curl -s -o /dev/null http://localhost:8501/_stcore/health 2>/dev/null; then
        break
    fi
    sleep 3
done

# Run tunnel — stream output to log, extract URL
(
    "$CLOUDFLARED" tunnel --url http://localhost:8501 --loglevel info 2>&1 | while IFS= read -r line; do
        echo "$line" >> "$LOG"
        # Extract trycloudflare.com URL from cloudflared output
        if [[ "$line" == *"trycloudflare.com"* ]]; then
            url=$(echo "$line" | grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" | head -1)
            if [ -n "$url" ]; then
                echo "$url" > "$URL_FILE"
                # macOS notification
                osascript -e "display notification \"$url\" with title \"ICT Dashboard public URL\" sound name \"Glass\"" 2>/dev/null || true
                # Copy to clipboard
                echo -n "$url" | pbcopy 2>/dev/null || true
            fi
        fi
    done
) &

wait
