# ============================================================
# MT5 WATCHDOG - Keep MT5 terminal connected 24/7
# ============================================================
# Runs every 10 min via Scheduled Task.
# Verifies MT5 terminal is running + connected via Python MT5 API.
# If not: tries reconnect; if fail: kills + restarts MT5 terminal.
# Sends Telegram alert on state changes.
# ============================================================

$ErrorActionPreference = "Continue"
$FRAMEWORK_DIR = "C:\Users\Administrator\ict-trading-framework"
$LOG = "$FRAMEWORK_DIR\mt5_watchdog.log"
$STATE_FILE = "$FRAMEWORK_DIR\user_data\mt5_watchdog_state.json"
$MT5_TERMINAL = "${env:ProgramFiles}\MetaTrader 5\terminal64.exe"
if (-not (Test-Path $MT5_TERMINAL)) {
    $MT5_TERMINAL = "${env:ProgramFiles}\FTMO MetaTrader 5\terminal64.exe"
}
if (-not (Test-Path $MT5_TERMINAL)) {
    $MT5_TERMINAL = "${env:ProgramFiles(x86)}\MetaTrader 5\terminal64.exe"
}

function Log($m) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content $LOG "[$ts] $m"
}

function Send-TelegramAlert($msg) {
    $envPath = "$FRAMEWORK_DIR\user_data\.env"
    if (-not (Test-Path $envPath)) { return }
    $env = Get-Content $envPath -Raw
    if ($env -match "TELEGRAM_BOT_TOKEN=([^\r\n\s]+)") {
        $tk = $matches[1]
        if ($env -match "TELEGRAM_CHAT_ID=([^\r\n\s]+)") {
            $cid = $matches[1]
            try {
                Invoke-RestMethod -Uri "https://api.telegram.org/bot$tk/sendMessage" `
                    -Method POST -Body @{chat_id=$cid; text=$msg} | Out-Null
            } catch {}
        }
    }
}

function Test-MT5Connection {
    $pyCheck = python -c @"
import json, sys
try:
    import MetaTrader5 as mt5
    with open(r'$FRAMEWORK_DIR\user_data\mt5_accounts.json', encoding='utf-8-sig') as f:
        a = json.load(f)['accounts'][0]
    ok = mt5.initialize(login=int(a['login']), password=a['password'], server=a['server'])
    if not ok:
        print('FAIL_INIT')
        sys.exit(1)
    info = mt5.account_info()
    if info is None:
        print('FAIL_NOINFO')
        sys.exit(1)
    print(f'OK_{info.login}_{info.balance}')
    mt5.shutdown()
except Exception as e:
    print(f'FAIL_EXC_{e}')
    sys.exit(1)
"@ 2>&1
    return $pyCheck
}

Log "=== Watchdog check ==="

# Read previous state
$prevState = "UNKNOWN"
if (Test-Path $STATE_FILE) {
    try {
        $prevState = (Get-Content $STATE_FILE | ConvertFrom-Json).state
    } catch {}
}

$result = Test-MT5Connection
Log "Check result: $result"

if ($result -match "^OK_") {
    # Connected
    if ($prevState -ne "OK") {
        Send-TelegramAlert "✅ MT5 reconnected : $result"
    }
    @{state="OK"; last_check=(Get-Date).ToString("o"); last_result=$result} |
        ConvertTo-Json | Set-Content $STATE_FILE
    exit 0
}

# Connection failed
Log "MT5 disconnected - attempting recovery"

# Step 1: Check if terminal64.exe process exists
$mt5Proc = Get-Process terminal64 -ErrorAction SilentlyContinue
if (-not $mt5Proc) {
    Log "MT5 terminal not running - starting..."
    if (Test-Path $MT5_TERMINAL) {
        Start-Process $MT5_TERMINAL
        Start-Sleep -Seconds 30
    } else {
        Log "MT5 executable not found at expected paths"
        Send-TelegramAlert "🔴 MT5 WATCHDOG : terminal64.exe introuvable - intervention manuelle requise"
        @{state="FAIL_NOEXE"; last_check=(Get-Date).ToString("o")} |
            ConvertTo-Json | Set-Content $STATE_FILE
        exit 1
    }
}

# Step 2: Retry connection after restart
Start-Sleep -Seconds 5
$retry = Test-MT5Connection
Log "Retry result: $retry"

if ($retry -match "^OK_") {
    Send-TelegramAlert "✅ MT5 RECOVERED après reconnexion auto"
    @{state="OK"; last_check=(Get-Date).ToString("o"); last_result=$retry} |
        ConvertTo-Json | Set-Content $STATE_FILE
    exit 0
}

# Step 3: Kill + restart if still KO
Log "Kill + restart MT5..."
Get-Process terminal64 -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 3
Start-Process $MT5_TERMINAL
Start-Sleep -Seconds 45

$final = Test-MT5Connection
Log "Final result: $final"

if ($final -match "^OK_") {
    Send-TelegramAlert "✅ MT5 RECOVERED après kill+restart"
    @{state="OK"; last_check=(Get-Date).ToString("o"); last_result=$final} |
        ConvertTo-Json | Set-Content $STATE_FILE
    exit 0
}

# Total failure
if ($prevState -ne "FAIL_PERSISTENT") {
    Send-TelegramAlert "🚨 MT5 DOWN - watchdog impossible de relancer. Intervention manuelle requise. Détails: $final"
}
@{state="FAIL_PERSISTENT"; last_check=(Get-Date).ToString("o"); last_result=$final} |
    ConvertTo-Json | Set-Content $STATE_FILE
exit 1
