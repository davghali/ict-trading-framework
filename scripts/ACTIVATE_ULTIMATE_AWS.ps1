# ============================================================
# ACTIVATE ULTIMATE - One-click deployment for ICT Cyborg
# ============================================================
# Usage:
#   cd C:\Users\Administrator\ict-trading-framework
#   git pull origin main
#   cd scripts
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#   .\ACTIVATE_ULTIMATE_AWS.ps1
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


# ============================================================
Step "ICT CYBORG ULTIMATE - AWS Activation"
# ============================================================

if (-not (Test-Path $FRAMEWORK_DIR)) {
    ERR "Framework dir not found: $FRAMEWORK_DIR"
    exit 1
}
Set-Location $FRAMEWORK_DIR
OK "Framework dir: $FRAMEWORK_DIR"


# ============================================================
Step "Step 1/5 - Git pull"
# ============================================================

$currentCommit = git rev-parse HEAD 2>&1
OK "Current commit: $($currentCommit.Substring(0, 8))"

git pull origin main 2>&1 | ForEach-Object { Write-Host "  $_" }

$newCommit = git rev-parse HEAD 2>&1
if ($newCommit -eq $currentCommit) {
    WARN "Already up to date"
} else {
    OK "Updated to: $($newCommit.Substring(0, 8))"
}


# ============================================================
Step "Step 2/5 - Settings.json migration"
# ============================================================

$settingsPath = Join-Path $FRAMEWORK_DIR "user_data\settings.json"
$examplePath = Join-Path $FRAMEWORK_DIR "user_data\settings.json.example"

if (-not (Test-Path $examplePath)) {
    ERR "settings.json.example not found - git pull may have failed"
    exit 1
}

if (Test-Path $settingsPath) {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $backupPath = Join-Path $FRAMEWORK_DIR "user_data\settings.backup.$stamp.json"
    Copy-Item $settingsPath $backupPath
    OK "Backup created: settings.backup.$stamp.json"

    try {
        $current = Get-Content $settingsPath -Raw | ConvertFrom-Json
        $template = Get-Content $examplePath -Raw | ConvertFrom-Json
    } catch {
        ERR "JSON parse failed, overwriting with template"
        Copy-Item $examplePath $settingsPath -Force
        OK "Fresh settings.json from template"
        $current = $null
    }

    if ($current -ne $null) {
        $newKeys = @(
            "use_multi_partial_exits",
            "partial_exit_levels",
            "runner_trailing_atr_mult",
            "runner_target_min_r",
            "use_confluence_filter",
            "confluence_min_score",
            "confluence_require_smt",
            "confluence_require_multi_tf",
            "use_dynamic_risk",
            "dynamic_risk_base",
            "dynamic_risk_max",
            "dynamic_risk_min",
            "dynamic_risk_hot_streak_boost",
            "dynamic_risk_cold_streak_penalty",
            "use_news_ride",
            "news_ride_wait_minutes",
            "news_ride_retracement_pct",
            "news_ride_risk_multiplier",
            "use_pyramid",
            "pyramid_max_adds",
            "pyramid_add_at_r",
            "pyramid_add_risk_pct",
            "ml_retrain_frequency",
            "ml_use_regime_detection",
            "min_grade_sniper"
        )

        $added = 0
        foreach ($key in $newKeys) {
            $has = $false
            foreach ($prop in $current.PSObject.Properties) {
                if ($prop.Name -eq $key) { $has = $true; break }
            }
            if (-not $has) {
                $value = $template.$key
                $current | Add-Member -NotePropertyName $key -NotePropertyValue $value -Force
                $added++
            }
        }
        OK "Added $added new Phase 1/2/3 keys to settings.json"

        if ($current.assets_h1.Count -lt 9) {
            $current.assets_h1 = $template.assets_h1
            OK "Extended assets_h1 to $($template.assets_h1.Count)"
        }
        if ($current.assets_d1.Count -lt 10) {
            $current.assets_d1 = $template.assets_d1
            OK "Extended assets_d1 to $($template.assets_d1.Count)"
        }

        $json = $current | ConvertTo-Json -Depth 10
        [System.IO.File]::WriteAllText($settingsPath, $json)
        OK "settings.json saved (no BOM)"
    }
} else {
    WARN "settings.json missing, copying from template"
    Copy-Item $examplePath $settingsPath
    OK "settings.json created"
}


# ============================================================
Step "Step 3/5 - Syntax check"
# ============================================================

$scriptPath = Join-Path $FRAMEWORK_DIR "run_cyborg_ultimate.py"
if (-not (Test-Path $scriptPath)) {
    ERR "run_cyborg_ultimate.py not found - git pull failed"
    exit 1
}

$pyCheck = python -c "import ast; ast.parse(open('run_cyborg_ultimate.py').read()); print('OK')" 2>&1
if ($pyCheck -match "OK") {
    OK "run_cyborg_ultimate.py syntax valid"
} else {
    ERR "Syntax error: $pyCheck"
    exit 1
}


# ============================================================
Step "Step 4/5 - Switch Scheduled Task"
# ============================================================

$task = Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue
if (-not $task) {
    ERR "Scheduled Task '$TASK_NAME' not found"
    WARN "Create it manually or run install_autostart.sh"
    exit 1
}
OK "Task '$TASK_NAME' found"

Stop-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue
OK "Task stopped"
Start-Sleep -Seconds 3

$pythonPath = (Get-Command python.exe).Source
$action = New-ScheduledTaskAction `
    -Execute $pythonPath `
    -Argument "`"$scriptPath`"" `
    -WorkingDirectory $FRAMEWORK_DIR

Set-ScheduledTask -TaskName $TASK_NAME -Action $action
OK "Task action updated to run_cyborg_ultimate.py"

Start-ScheduledTask -TaskName $TASK_NAME
OK "Task started"
Start-Sleep -Seconds 5

$info = Get-ScheduledTaskInfo -TaskName $TASK_NAME
OK "LastRunTime: $($info.LastRunTime)"
OK "LastResult: $($info.LastTaskResult) (0 = success)"


# ============================================================
Step "Step 5/5 - Verification"
# ============================================================

Start-Sleep -Seconds 8

$procs = Get-Process python -ErrorAction SilentlyContinue
if ($procs) {
    OK "Python processes running: $($procs.Count)"
    foreach ($p in $procs) {
        $mem = [math]::Round($p.WorkingSet / 1MB, 0)
        OK "  PID $($p.Id)  Mem $($mem)MB"
    }
} else {
    WARN "No Python process found"
}

$logPath = Join-Path $FRAMEWORK_DIR "cyborg.log"
$altLogPath = Join-Path $FRAMEWORK_DIR "reports\logs\cyborg.log"
if (Test-Path $logPath) {
    OK "Recent log lines:"
    Get-Content $logPath -Tail 8 | ForEach-Object { Write-Host "    $_" }
} elseif (Test-Path $altLogPath) {
    OK "Recent log lines (reports/logs):"
    Get-Content $altLogPath -Tail 8 | ForEach-Object { Write-Host "    $_" }
} else {
    WARN "Log file not found yet (wait 60 sec for first scan)"
}


# ============================================================
Step "DONE - Ultimate activated"
# ============================================================

Write-Host ""
Write-Host "  Next steps:" -ForegroundColor Green
Write-Host "  1. Check Telegram within 60 sec for: ICT CYBORG ULTIMATE" -ForegroundColor Green
Write-Host "  2. Dashboard: https://ict-quant-david.streamlit.app" -ForegroundColor Green
Write-Host "  3. Monitor 24h - logs should show signal scans" -ForegroundColor Green
Write-Host ""
Write-Host "  Rollback if needed:" -ForegroundColor Yellow
Write-Host "  .\ROLLBACK_AWS.ps1" -ForegroundColor Yellow
Write-Host ""
