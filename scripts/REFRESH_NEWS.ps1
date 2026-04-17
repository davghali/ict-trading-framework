# REFRESH_NEWS.ps1 - Daily refresh of economic news calendar
$FRAMEWORK_DIR = "C:\Users\Administrator\ict-trading-framework"
$LOG = "$FRAMEWORK_DIR\news_refresh.log"
Set-Location $FRAMEWORK_DIR

$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content $LOG "[$ts] News refresh START"

$env:PYTHONIOENCODING = "utf-8"
$result = python -c @"
import sys
sys.path.insert(0, '.')
from src.news_calendar import NewsCalendar
cal = NewsCalendar()
try:
    cal.refresh()
    print('OK refreshed')
except Exception as e:
    print(f'FAIL {e}')
    sys.exit(1)
"@ 2>&1

Add-Content $LOG "[$ts] Result: $result"

if ($result -match "FAIL") {
    $envPath = "$FRAMEWORK_DIR\user_data\.env"
    if (Test-Path $envPath) {
        $env = Get-Content $envPath -Raw
        if ($env -match "TELEGRAM_BOT_TOKEN=([^\r\n\s]+)") {
            $tk = $matches[1]
            if ($env -match "TELEGRAM_CHAT_ID=([^\r\n\s]+)") {
                $cid = $matches[1]
                Invoke-RestMethod -Uri "https://api.telegram.org/bot$tk/sendMessage" `
                    -Method POST -Body @{chat_id=$cid; text="⚠️ News refresh failed: $result"} | Out-Null
            }
        }
    }
}
