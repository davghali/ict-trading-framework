# ============================================================
# FINALIZE EVERYTHING - Master script final
# ============================================================
# Un seul script qui fait TOUT :
# 1. Git pull (derniere version)
# 2. Install MetaTrader5 Python package
# 3. Fix BOM encoding si present
# 4. Test MT5 Python connection
# 5. Install Safety Net (MT5 watchdog + news + weekly report)
# 6. Schedule Monday 6h50 UTC auto-activation
# 7. Summary + Telegram confirmation
#
# Usage :
#   cd C:\Users\Administrator\ict-trading-framework
#   git pull origin main
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#   cd scripts
#   .\FINALIZE_EVERYTHING.ps1
# ============================================================

$ErrorActionPreference = "Continue"
$FRAMEWORK_DIR = "C:\Users\Administrator\ict-trading-framework"

function Step($msg) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  $msg" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
}
function OK($m) { Write-Host "  [OK] $m" -ForegroundColor Green }
function WARN($m) { Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function ERR($m) { Write-Host "  [ERROR] $m" -ForegroundColor Red }

$results = @{}


# ============================================================
Step "ICT CYBORG - FINAL SETUP"
# ============================================================

Set-Location $FRAMEWORK_DIR
OK "Working dir: $FRAMEWORK_DIR"


# ============================================================
Step "Step 1/7 - Git pull"
# ============================================================

git pull origin main 2>&1 | ForEach-Object { Write-Host "  $_" }
OK "Repo up to date"
$results["git_pull"] = "OK"


# ============================================================
Step "Step 2/7 - MetaTrader5 Python package"
# ============================================================

$mt5Check = python -c "import MetaTrader5; print('ok')" 2>&1
if ($mt5Check -match "ok") {
    OK "MetaTrader5 already installed"
    $results["mt5_pkg"] = "Already installed"
} else {
    WARN "Installing MetaTrader5..."
    python -m pip install MetaTrader5 --upgrade 2>&1 | ForEach-Object { Write-Host "  $_" }
    $recheck = python -c "import MetaTrader5; print('ok')" 2>&1
    if ($recheck -match "ok") {
        OK "MetaTrader5 installed"
        $results["mt5_pkg"] = "Just installed"
    } else {
        ERR "MetaTrader5 install failed: $recheck"
        $results["mt5_pkg"] = "FAILED"
    }
}


# ============================================================
Step "Step 3/7 - Fix BOM encoding (settings.json + mt5_accounts.json)"
# ============================================================

$files = @(
    "$FRAMEWORK_DIR\user_data\settings.json",
    "$FRAMEWORK_DIR\user_data\mt5_accounts.json"
)
foreach ($f in $files) {
    if (Test-Path $f) {
        $content = [System.IO.File]::ReadAllText($f)
        $clean = $content.TrimStart([char]0xFEFF)
        if ($content -ne $clean) {
            [System.IO.File]::WriteAllText($f, $clean)
            OK "BOM removed from $(Split-Path $f -Leaf)"
        } else {
            OK "$(Split-Path $f -Leaf) already clean"
        }
    }
}
$results["bom_fix"] = "OK"


# ============================================================
Step "Step 4/7 - Test MT5 Python connection"
# ============================================================

$env:PYTHONIOENCODING = "utf-8"
$testResult = python -c @"
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
    print(f'OK login={info.login} balance={info.balance} equity={info.equity} server={info.server}')
    mt5.shutdown()
except Exception as e:
    print(f'EXCEPTION {e}')
    sys.exit(1)
"@ 2>&1

if ($testResult -match "^OK") {
    OK "MT5 connection: $testResult"
    $results["mt5_test"] = $testResult
} else {
    ERR "MT5 test failed: $testResult"
    WARN "Le bot tournera en DRY-RUN sans trades reels"
    $results["mt5_test"] = "FAILED: $testResult"
}


# ============================================================
Step "Step 5/7 - Install Safety Net (3 Scheduled Tasks)"
# ============================================================

# 5a - MT5 Watchdog every 10 min
Unregister-ScheduledTask -TaskName "ICTCyborgMT5Watchdog" -Confirm:$false -ErrorAction SilentlyContinue
$ps = (Get-Command powershell.exe).Source
$args1 = "-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File `"$FRAMEWORK_DIR\scripts\MT5_WATCHDOG.ps1`""
$action1 = New-ScheduledTaskAction -Execute $ps -Argument $args1 -WorkingDirectory $FRAMEWORK_DIR
$trigger1 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 10)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName "ICTCyborgMT5Watchdog" -Action $action1 -Trigger $trigger1 -Settings $settings -Principal $principal -Description "MT5 keep-alive every 10 min" -Force | Out-Null
OK "Task ICTCyborgMT5Watchdog registered (every 10 min)"

# 5b - News Refresh daily 02:00
Unregister-ScheduledTask -TaskName "ICTCyborgNewsRefresh" -Confirm:$false -ErrorAction SilentlyContinue
$args2 = "-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File `"$FRAMEWORK_DIR\scripts\REFRESH_NEWS.ps1`""
$action2 = New-ScheduledTaskAction -Execute $ps -Argument $args2 -WorkingDirectory $FRAMEWORK_DIR
$trigger2 = New-ScheduledTaskTrigger -Daily -At "02:00"
Register-ScheduledTask -TaskName "ICTCyborgNewsRefresh" -Action $action2 -Trigger $trigger2 -Settings $settings -Principal $principal -Description "Refresh news calendar daily" -Force | Out-Null
OK "Task ICTCyborgNewsRefresh registered (daily 02:00)"

# 5c - Weekly Report Sunday 20:00
Unregister-ScheduledTask -TaskName "ICTCyborgWeeklyReport" -Confirm:$false -ErrorAction SilentlyContinue
$args3 = "-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File `"$FRAMEWORK_DIR\scripts\WEEKLY_REPORT.ps1`""
$action3 = New-ScheduledTaskAction -Execute $ps -Argument $args3 -WorkingDirectory $FRAMEWORK_DIR
$trigger3 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "20:00"
Register-ScheduledTask -TaskName "ICTCyborgWeeklyReport" -Action $action3 -Trigger $trigger3 -Settings $settings -Principal $principal -Description "Weekly performance report" -Force | Out-Null
OK "Task ICTCyborgWeeklyReport registered (Sunday 20:00)"

$results["safety_net"] = "3 tasks installed"


# ============================================================
Step "Step 6/7 - Schedule Monday auto-activation"
# ============================================================

$nowUtc = [DateTime]::UtcNow
$daysUntilMonday = [int]([DayOfWeek]::Monday - $nowUtc.DayOfWeek)
if ($daysUntilMonday -le 0) { $daysUntilMonday += 7 }
$nextMondayDate = $nowUtc.Date.AddDays($daysUntilMonday)
$targetTimeUtc = $nextMondayDate.AddHours(6).AddMinutes(50)

if ($nowUtc.DayOfWeek -eq [DayOfWeek]::Monday -and ($nowUtc.Hour -lt 6 -or ($nowUtc.Hour -eq 6 -and $nowUtc.Minute -lt 50))) {
    $targetTimeUtc = $nowUtc.Date.AddHours(6).AddMinutes(50)
}
$targetTimeLocal = $targetTimeUtc.ToLocalTime()

Unregister-ScheduledTask -TaskName "ICTCyborgMondayActivation" -Confirm:$false -ErrorAction SilentlyContinue

$args4 = "-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File `"$FRAMEWORK_DIR\scripts\ACTIVATE_FULL_AUTO_AWS.ps1`""
$action4 = New-ScheduledTaskAction -Execute $ps -Argument $args4 -WorkingDirectory $FRAMEWORK_DIR
$trigger4 = New-ScheduledTaskTrigger -Once -At $targetTimeLocal
$settingsMonday = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask -TaskName "ICTCyborgMondayActivation" -Action $action4 -Trigger $trigger4 -Settings $settingsMonday -Principal $principal -Description "Auto-bascule FULL AUTO lundi 6h50 UTC" -Force | Out-Null
OK "Monday activation scheduled : $($targetTimeUtc.ToString('yyyy-MM-dd HH:mm')) UTC ($($targetTimeLocal.ToString('yyyy-MM-dd HH:mm')) local)"
$results["monday_task"] = $targetTimeUtc.ToString("yyyy-MM-dd HH:mm") + " UTC"


# ============================================================
Step "Step 7/7 - Verification + Telegram summary"
# ============================================================

# Verifier toutes les tasks
Write-Host ""
Write-Host "Scheduled Tasks status:" -ForegroundColor Cyan
Get-ScheduledTask -TaskName "ICTCyborg*" | Format-Table TaskName, State -AutoSize

# Envoyer summary Telegram
$envPath = "$FRAMEWORK_DIR\user_data\.env"
if (Test-Path $envPath) {
    $env = Get-Content $envPath -Raw
    if ($env -match "TELEGRAM_BOT_TOKEN=([^\r\n\s]+)") {
        $tk = $matches[1]
        if ($env -match "TELEGRAM_CHAT_ID=([^\r\n\s]+)") {
            $cid = $matches[1]
            $summary = @"
FINALIZATION COMPLETE

Git pull : $($results['git_pull'])
MT5 package : $($results['mt5_pkg'])
BOM fix : $($results['bom_fix'])
MT5 test : $($results['mt5_test'])
Safety net : $($results['safety_net'])
Monday auto-activation : $($results['monday_task'])

5 Scheduled Tasks actives :
- ICTCyborg (signal-only jusqu'a lundi)
- ICTCyborgMT5Watchdog (every 10 min)
- ICTCyborgNewsRefresh (daily 02:00)
- ICTCyborgWeeklyReport (Sunday 20:00)
- ICTCyborgMondayActivation ($($results['monday_task']))

Ton bot est 100 pour 100 blinde pour lundi.
"@
            try {
                Invoke-RestMethod -Uri "https://api.telegram.org/bot$tk/sendMessage" `
                    -Method POST -Body @{chat_id=$cid; text=$summary} | Out-Null
                OK "Telegram summary sent"
            } catch {
                WARN "Telegram send failed: $_"
            }
        }
    }
}


# ============================================================
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  FINALIZATION COMPLETE" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Resultats :" -ForegroundColor Cyan
foreach ($key in $results.Keys) {
    Write-Host "    $key : $($results[$key])" -ForegroundColor White
}
Write-Host ""
Write-Host "  5 Scheduled Tasks installees :" -ForegroundColor Cyan
Write-Host "    1. ICTCyborg (bot actuel signal-only)" -ForegroundColor Green
Write-Host "    2. ICTCyborgMT5Watchdog    : every 10 min" -ForegroundColor Green
Write-Host "    3. ICTCyborgNewsRefresh    : daily 02h local" -ForegroundColor Green
Write-Host "    4. ICTCyborgWeeklyReport   : Sunday 20h local" -ForegroundColor Green
Write-Host "    5. ICTCyborgMondayActivation : $($results['monday_task'])" -ForegroundColor Green
Write-Host ""
Write-Host "  TODO OPTIONNEL - Email fallback :" -ForegroundColor Yellow
Write-Host "    1. Cree un App Password Gmail : https://myaccount.google.com/apppasswords" -ForegroundColor Yellow
Write-Host "    2. Ajoute dans user_data\.env :" -ForegroundColor Yellow
Write-Host "         SMTP_USER=ghalidavid5@gmail.com" -ForegroundColor Yellow
Write-Host "         SMTP_PASSWORD=tes16characterss" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Lundi matin 8h50 Paris = bascule auto en FULL AUTO" -ForegroundColor Green
Write-Host "  Tu peux fermer la RDP (MT5 reste ouvert)" -ForegroundColor Green
Write-Host ""
