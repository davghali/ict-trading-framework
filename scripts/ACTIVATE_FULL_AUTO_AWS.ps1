# ============================================================
# ACTIVATE FULL AUTO - Bascule vers run_cyborg_full_auto.py
# ============================================================
# Usage:
#   cd C:\Users\Administrator\ict-trading-framework\scripts
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#   .\ACTIVATE_FULL_AUTO_AWS.ps1
#
# Prerequisites:
# - MetaTrader5 terminal installed on Windows
# - user_data/mt5_accounts.json configured with FTMO credentials
# - settings.json: auto_execute=true
# ============================================================

$ErrorActionPreference = "Continue"
$FRAMEWORK_DIR = "C:\Users\Administrator\ict-trading-framework"
$TASK_NAME = "ICTCyborg"

function Step($msg) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  $msg" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
}
function OK($msg) { Write-Host "  [OK] $msg" -ForegroundColor Green }
function WARN($msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function ERR($msg) { Write-Host "  [ERROR] $msg" -ForegroundColor Red }


Step "ICT CYBORG FULL AUTO - Bascule Scheduled Task"
Set-Location $FRAMEWORK_DIR


Step "Step 1/5 - Git pull"
git pull origin main 2>&1 | ForEach-Object { Write-Host "  $_" }


Step "Step 2/5 - Install MetaTrader5 Python package"
$mt5Installed = python -c "import MetaTrader5; print('ok')" 2>&1
if ($mt5Installed -match "ok") {
    OK "MetaTrader5 package already installed"
} else {
    WARN "Installing MetaTrader5 package..."
    python -m pip install MetaTrader5 --upgrade 2>&1 | ForEach-Object { Write-Host "  $_" }
    $check = python -c "import MetaTrader5; print('ok')" 2>&1
    if ($check -match "ok") {
        OK "MetaTrader5 package installed"
    } else {
        ERR "Failed to install MetaTrader5: $check"
        WARN "Continue anyway - bot will run in DRY-RUN until MT5 available"
    }
}


Step "Step 3/5 - Verify mt5_accounts.json"
$accPath = Join-Path $FRAMEWORK_DIR "user_data\mt5_accounts.json"
if (-not (Test-Path $accPath)) {
    ERR "mt5_accounts.json NOT FOUND"
    WARN "Create it from mt5_accounts.json.example with your FTMO credentials"
    WARN "Then re-run this script"
    exit 1
}

try {
    $accounts = Get-Content $accPath -Raw | ConvertFrom-Json
    $enabledCount = ($accounts.accounts | Where-Object { $_.enabled -eq $true -and $_.login -gt 0 }).Count
    if ($enabledCount -eq 0) {
        ERR "No enabled account in mt5_accounts.json"
        exit 1
    }
    OK "$enabledCount enabled account(s) found"
} catch {
    ERR "Failed to parse mt5_accounts.json"
    exit 1
}


Step "Step 4/5 - Verify settings.json auto_execute=true"
$settingsPath = Join-Path $FRAMEWORK_DIR "user_data\settings.json"
if (-not (Test-Path $settingsPath)) {
    ERR "settings.json missing - run ACTIVATE_ULTIMATE_AWS.ps1 first"
    exit 1
}

$s = Get-Content $settingsPath -Raw | ConvertFrom-Json
$hasAutoExec = $false
foreach ($prop in $s.PSObject.Properties) {
    if ($prop.Name -eq "auto_execute") { $hasAutoExec = $true }
}

if (-not $hasAutoExec -or $s.auto_execute -ne $true) {
    WARN "auto_execute not true in settings.json - forcing to true"
    $s | Add-Member -NotePropertyName "auto_execute" -NotePropertyValue $true -Force
    $json = $s | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText($settingsPath, $json)
    OK "auto_execute set to true"
} else {
    OK "auto_execute=true confirmed"
}


Step "Step 5/5 - Switch Scheduled Task to run_cyborg_full_auto.py"
$task = Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue
if (-not $task) {
    ERR "Scheduled Task '$TASK_NAME' not found"
    exit 1
}

Stop-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue
OK "Task stopped"
Start-Sleep -Seconds 3

$pythonPath = (Get-Command python.exe).Source
$scriptPath = Join-Path $FRAMEWORK_DIR "run_cyborg_full_auto.py"

if (-not (Test-Path $scriptPath)) {
    ERR "run_cyborg_full_auto.py not found - git pull failed"
    exit 1
}

$action = New-ScheduledTaskAction `
    -Execute $pythonPath `
    -Argument "`"$scriptPath`"" `
    -WorkingDirectory $FRAMEWORK_DIR

Set-ScheduledTask -TaskName $TASK_NAME -Action $action
OK "Task reconfigured for run_cyborg_full_auto.py"

Start-ScheduledTask -TaskName $TASK_NAME
OK "Task started"
Start-Sleep -Seconds 8

$procs = Get-Process python -ErrorAction SilentlyContinue
if ($procs) {
    OK "Python processes running: $($procs.Count)"
    foreach ($p in $procs) {
        $mem = [math]::Round($p.WorkingSet / 1MB, 0)
        OK "  PID $($p.Id)  Mem $($mem)MB"
    }
}


Step "Step 6/5 - Install Safety Net (MT5 watchdog + news refresh + weekly report)"
$safetyScript = Join-Path $FRAMEWORK_DIR "scripts\INSTALL_SAFETY_NET.ps1"
if (Test-Path $safetyScript) {
    & $safetyScript
    OK "Safety net installed"
} else {
    WARN "Safety net script not found (git pull may be needed)"
}


Step "FULL AUTO ACTIVATED"

Write-Host ""
Write-Host "  The bot will now PLACE ORDERS AUTOMATICALLY on MT5" -ForegroundColor Yellow
Write-Host "  Trading days: Monday to Friday UTC" -ForegroundColor Green
Write-Host "  Friday cutoff: 15:00 UTC (no new trade after)" -ForegroundColor Green
Write-Host "  Max concurrent positions: 5" -ForegroundColor Green
Write-Host "  Daily loss cap: 3.5%" -ForegroundColor Green
Write-Host ""
Write-Host "  Telegram commands available:" -ForegroundColor Cyan
Write-Host "    /auto_status  - View current state" -ForegroundColor Cyan
Write-Host "    /pause        - Pause auto-execution" -ForegroundColor Cyan
Write-Host "    /resume       - Resume auto-execution" -ForegroundColor Cyan
Write-Host "    /positions    - List open positions" -ForegroundColor Cyan
Write-Host "    /close_all    - EMERGENCY close all" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Rollback to signal-only mode:" -ForegroundColor Yellow
Write-Host "    .\ACTIVATE_ULTIMATE_AWS.ps1" -ForegroundColor Yellow
Write-Host ""
