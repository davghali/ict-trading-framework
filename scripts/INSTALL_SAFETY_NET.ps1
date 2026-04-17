# ============================================================
# INSTALL SAFETY NET - All P0/P1 recurring tasks
# ============================================================
# Installe 3 Scheduled Tasks Windows :
# 1. ICTCyborgMT5Watchdog    - every 10 min
# 2. ICTCyborgNewsRefresh    - daily at 02:00 UTC
# 3. ICTCyborgWeeklyReport   - every Sunday 20:00 UTC
# ============================================================

$ErrorActionPreference = "Continue"
$FRAMEWORK_DIR = "C:\Users\Administrator\ict-trading-framework"
$SCRIPTS = "$FRAMEWORK_DIR\scripts"

function Register-Task($name, $script, $trigger, $description) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    $powershellPath = (Get-Command powershell.exe).Source
    $action = New-ScheduledTaskAction `
        -Execute $powershellPath `
        -Argument "-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File `"$script`"" `
        -WorkingDirectory $FRAMEWORK_DIR
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Description $description -Force | Out-Null
    Write-Host "  [OK] $name registered" -ForegroundColor Green
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  SAFETY NET INSTALLATION" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

Set-Location $FRAMEWORK_DIR
git pull origin main 2>&1 | ForEach-Object { Write-Host "  $_" }

# Task 1: MT5 Watchdog every 10 min
Write-Host "Task 1/3 - MT5 Watchdog (every 10 min)..." -ForegroundColor Cyan
$script1 = "$SCRIPTS\MT5_WATCHDOG.ps1"
$trigger1 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Minutes 10)
Register-Task "ICTCyborgMT5Watchdog" $script1 $trigger1 "Keep MT5 connected 24/7"

# Task 2: News Calendar Refresh (daily 02:00 local)
Write-Host "Task 2/3 - News Calendar Auto-Refresh (daily 02:00)..." -ForegroundColor Cyan
$script2 = "$SCRIPTS\REFRESH_NEWS.ps1"
$trigger2 = New-ScheduledTaskTrigger -Daily -At "02:00"
Register-Task "ICTCyborgNewsRefresh" $script2 $trigger2 "Refresh economic news calendar daily"

# Task 3: Weekly Report (Sunday 20:00 local)
Write-Host "Task 3/3 - Weekly Report (Sunday 20:00)..." -ForegroundColor Cyan
$script3 = "$SCRIPTS\WEEKLY_REPORT.ps1"
$trigger3 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "20:00"
Register-Task "ICTCyborgWeeklyReport" $script3 $trigger3 "Send weekly performance report"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  SAFETY NET ACTIVE" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Tasks installed:" -ForegroundColor Green
Write-Host "  - ICTCyborgMT5Watchdog    : every 10 min" -ForegroundColor Green
Write-Host "  - ICTCyborgNewsRefresh    : daily 02:00" -ForegroundColor Green
Write-Host "  - ICTCyborgWeeklyReport   : Sunday 20:00" -ForegroundColor Green
Write-Host ""
Get-ScheduledTask -TaskName "ICTCyborg*" | Format-Table TaskName, State -AutoSize
