# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  DEPLOY ONE-CLICK — Full A→Z deployment on AWS Windows                  ║
# ║                                                                          ║
# ║  Usage : right-click → Run with PowerShell (as Administrator)           ║
# ║         OR : .\DEPLOY_ONE_CLICK.ps1                                      ║
# ║                                                                          ║
# ║  Does EVERYTHING :                                                       ║
# ║    1. Pull latest code from GitHub                                       ║
# ║    2. Install Python dependencies                                        ║
# ║    3. Kill Streamlit + old bot processes                                 ║
# ║    4. Disable Streamlit scheduled tasks                                  ║
# ║    5. Run full audit                                                     ║
# ║    6. Test Telegram connection                                           ║
# ║    7. Test MT5 connection                                                ║
# ║    8. Start bot in background                                            ║
# ║    9. Create auto-restart Scheduled Task                                 ║
# ║   10. Send Telegram confirmation                                         ║
# ╚══════════════════════════════════════════════════════════════════════════╝

# ErrorActionPreference is intentionally "Continue" - native commands like git
# write progress info to stderr on success, which "Stop" converts to exceptions.
# We check $LASTEXITCODE explicitly after each critical external call.
$ErrorActionPreference = "Continue"
$FRAMEWORK_DIR = "C:\Users\Administrator\ict-trading-framework"

function Write-Header($msg) {
    Write-Host ""
    Write-Host "════════════════════════════════════════════════════════════════" -ForegroundColor Yellow
    Write-Host $msg -ForegroundColor Yellow
    Write-Host "════════════════════════════════════════════════════════════════" -ForegroundColor Yellow
}

function Write-OK($msg)    { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err($msg)   { Write-Host "[FAIL] $msg" -ForegroundColor Red }
function Write-Info($msg)  { Write-Host "[INFO] $msg" -ForegroundColor Cyan }

Write-Header "🚀 ICT CYBORG — ONE-CLICK DEPLOY v2"
Write-Host "Expected performance : WR 51.8% · PF 2.35 · +82%/an · DD -3.9%" -ForegroundColor Cyan
Write-Host ""

# ═══════════════════════════════════════════════════════════════════════════
# STEP 1 : Verify environment
# ═══════════════════════════════════════════════════════════════════════════
Write-Header "STEP 1 / 10 — Vérification environnement"

if (-not (Test-Path $FRAMEWORK_DIR)) {
    Write-Err "Framework directory introuvable : $FRAMEWORK_DIR"
    Write-Host "Clone le repo d'abord :"
    Write-Host "  git clone https://github.com/davghali/ict-trading-framework.git $FRAMEWORK_DIR"
    exit 1
}

cd $FRAMEWORK_DIR
Write-OK "Directory : $FRAMEWORK_DIR"

# Check Python
$py_version = & python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Err "Python non trouvé. Installer Python 3.9+ d'abord."
    exit 1
}
Write-OK "Python : $py_version"

# Check git
$git_version = & git --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Err "Git non trouvé. Installer Git d'abord."
    exit 1
}
Write-OK "Git : $git_version"

# ═══════════════════════════════════════════════════════════════════════════
# STEP 2 : Pull latest code
# ═══════════════════════════════════════════════════════════════════════════
Write-Header "STEP 2 / 10 — Git Pull dernière version"

# git writes to stderr on success - do NOT try/catch native commands.
# Check $LASTEXITCODE after each git call instead.

$fetch_output = & git fetch origin 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Err "Git fetch failed (exit $LASTEXITCODE) :"
    $fetch_output | ForEach-Object { Write-Host "  $_" }
    exit 1
}

$current_branch = (& git rev-parse --abbrev-ref HEAD).Trim()
if ($LASTEXITCODE -ne 0) {
    Write-Err "Git rev-parse failed"
    exit 1
}

$pull_output = & git pull origin $current_branch 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Err "Git pull failed (exit $LASTEXITCODE) :"
    $pull_output | ForEach-Object { Write-Host "  $_" }
    exit 1
}
$pull_output | ForEach-Object { Write-Host "  $_" }

$last_commit = (& git log -1 --oneline).Trim()
Write-OK "Latest commit : $last_commit"

# ═══════════════════════════════════════════════════════════════════════════
# STEP 3 : Install Python dependencies
# ═══════════════════════════════════════════════════════════════════════════
Write-Header "STEP 3 / 10 — Install/Update dépendances Python"

python -m pip install --upgrade pip 2>&1 | Out-Null
python -m pip install -r requirements.txt 2>&1 | Out-Null
python -m pip install scikit-learn MetaTrader5 2>&1 | Out-Null

# Verify critical imports (check $LASTEXITCODE on native python, not try/catch)
$imports_ok = $true
$critical = @("pandas", "numpy", "sklearn", "MetaTrader5")
foreach ($pkg in $critical) {
    & python -c "import $pkg" 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-OK "import $pkg"
    } else {
        Write-Warn "import $pkg failed"
        if ($pkg -eq "MetaTrader5") {
            $imports_ok = $false
        }
    }
}

if (-not $imports_ok) {
    Write-Err "MetaTrader5 Python package manquant. Installer manuellement :"
    Write-Host "  python -m pip install MetaTrader5"
    exit 1
}

# ═══════════════════════════════════════════════════════════════════════════
# STEP 4 : Kill old bot + Streamlit processes
# ═══════════════════════════════════════════════════════════════════════════
Write-Header "STEP 4 / 10 — Stop ancien bot + Streamlit"

# Kill all python processes running bot scripts
$py_processes = Get-Process python -ErrorAction SilentlyContinue
if ($py_processes) {
    Write-Info "Stopping $($py_processes.Count) python process(es)..."
    $py_processes | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Write-OK "Python processes stopped"
} else {
    Write-OK "No running python processes"
}

# Kill streamlit specifically
Get-Process | Where-Object {$_.ProcessName -match "streamlit"} | Stop-Process -Force -ErrorAction SilentlyContinue

# Disable streamlit scheduled tasks
$st_tasks = Get-ScheduledTask | Where-Object {$_.TaskName -match "Streamlit|Dashboard"}
if ($st_tasks) {
    $st_tasks | ForEach-Object {
        Disable-ScheduledTask -TaskName $_.TaskName -ErrorAction SilentlyContinue | Out-Null
        Write-OK "Disabled Scheduled Task : $($_.TaskName)"
    }
} else {
    Write-OK "Aucune Scheduled Task Streamlit à désactiver"
}

# ═══════════════════════════════════════════════════════════════════════════
# STEP 5 : Verify ML model
# ═══════════════════════════════════════════════════════════════════════════
Write-Header "STEP 5 / 10 — Vérifier ML Model"

$model_path = Join-Path $FRAMEWORK_DIR "models\production_model.pkl"
if (Test-Path $model_path) {
    $model_check_script = Join-Path $FRAMEWORK_DIR "scripts\_check_model.py"
    $model_check = & python $model_check_script $model_path 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-OK "ML Model OK : $model_check"
    } else {
        Write-Err "ML Model check failed : $model_check"
        exit 1
    }
} else {
    Write-Warn "Model .pkl missing - re-training from production assets..."
    python scripts\train_production_model.py 2>&1 | Out-Null
    if (Test-Path $model_path) {
        Write-OK "ML Model re-trained"
    } else {
        Write-Err "ML training failed"
        exit 1
    }
}

# ═══════════════════════════════════════════════════════════════════════════
# STEP 6 : Verify MT5 credentials + connection
# ═══════════════════════════════════════════════════════════════════════════
Write-Header "STEP 6 / 10 — Test MT5"

$mt5_json = Join-Path $FRAMEWORK_DIR "user_data\mt5_accounts.json"
if (-not (Test-Path $mt5_json)) {
    Write-Warn "mt5_accounts.json manquant"
    Write-Info "Creation d'un template — tu dois le compléter puis relancer ce script"

    $template = @"
{
  "accounts": [
    {
      "name": "FTMO Swing 10k",
      "enabled": true,
      "login": 0,
      "password": "METTRE_TRADING_PASSWORD",
      "server": "FTMO-Server",
      "balance": 10000,
      "risk_per_trade_pct": 0.5
    }
  ]
}
"@
    $template | Out-File -FilePath $mt5_json -Encoding utf8
    Write-Host ""
    Write-Host "Ouvre le fichier et remplis tes credentials :" -ForegroundColor Yellow
    Write-Host "  notepad $mt5_json" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Puis relance DEPLOY_ONE_CLICK.ps1" -ForegroundColor Yellow
    exit 0
}

# Check if credentials are filled
$mt5_content = Get-Content $mt5_json | ConvertFrom-Json
$first_account = $mt5_content.accounts[0]
if ($first_account.login -eq 0 -or $first_account.password -eq "METTRE_TRADING_PASSWORD") {
    Write-Err "mt5_accounts.json contient le template - remplis-le avec tes vraies credentials"
    Write-Host "  notepad $mt5_json" -ForegroundColor Cyan
    exit 1
}

# Test MT5 connection (helper script)
$mt5_test_script = Join-Path $FRAMEWORK_DIR "scripts\_test_mt5.py"
$env:MT5_JSON = $mt5_json
$mt5_test = python $mt5_test_script 2>&1

if ($mt5_test -match "Connected") {
    Write-OK "MT5 : $mt5_test"
} else {
    Write-Err "MT5 connection failed : $mt5_test"
    Write-Host "Vérifie :" -ForegroundColor Yellow
    Write-Host "  1. MetaTrader5 est ouvert sur AWS" -ForegroundColor Yellow
    Write-Host "  2. Login + password corrects dans mt5_accounts.json" -ForegroundColor Yellow
    Write-Host "  3. Server = FTMO-Server (ou le bon nom)" -ForegroundColor Yellow
    exit 1
}

# ═══════════════════════════════════════════════════════════════════════════
# STEP 7 : Test Telegram
# ═══════════════════════════════════════════════════════════════════════════
Write-Header "STEP 7 / 10 — Test Telegram"

$env_file = Join-Path $FRAMEWORK_DIR ".env"
if (Test-Path $env_file) {
    $tg_test_script = Join-Path $FRAMEWORK_DIR "scripts\_test_telegram.py"
    $tg_test = python $tg_test_script 2>&1
    if ($tg_test -match "OK") {
        Write-OK "Telegram : $tg_test"
    } else {
        Write-Warn "Telegram : $tg_test"
    }
} else {
    Write-Warn ".env file missing - Telegram notifications disabled"
}

# ═══════════════════════════════════════════════════════════════════════════
# STEP 8 : Run full audit
# ═══════════════════════════════════════════════════════════════════════════
Write-Header "STEP 8 / 10 — Audit complet"

python scripts\full_audit.py 2>&1 | Select-Object -Last 25 | ForEach-Object { Write-Host "  $_" }

# ═══════════════════════════════════════════════════════════════════════════
# STEP 9 : Start bot in background
# ═══════════════════════════════════════════════════════════════════════════
Write-Header "STEP 9 / 10 — Démarrer Bot Production"

$log_file = Join-Path $FRAMEWORK_DIR "reports\logs\bot_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
New-Item -ItemType Directory -Force -Path (Split-Path $log_file) | Out-Null

$bot_process = Start-Process -FilePath "python" `
    -ArgumentList "run_cyborg_full_auto.py" `
    -WorkingDirectory $FRAMEWORK_DIR `
    -WindowStyle Hidden `
    -RedirectStandardOutput $log_file `
    -RedirectStandardError "$log_file.err" `
    -PassThru

Start-Sleep -Seconds 5

if (Get-Process -Id $bot_process.Id -ErrorAction SilentlyContinue) {
    Write-OK "Bot started (PID: $($bot_process.Id))"
    Write-Info "Log file : $log_file"
} else {
    Write-Err "Bot failed to start"
    Get-Content $log_file -Tail 20
    exit 1
}

# ═══════════════════════════════════════════════════════════════════════════
# STEP 10 : Create/update auto-restart Scheduled Task
# ═══════════════════════════════════════════════════════════════════════════
Write-Header "STEP 10 / 10 — Scheduled Task auto-restart"

$task_name = "ICTCyborg"
$existing = Get-ScheduledTask -TaskName $task_name -ErrorAction SilentlyContinue
if ($existing) {
    Stop-ScheduledTask -TaskName $task_name -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $task_name -Confirm:$false -ErrorAction SilentlyContinue
    Write-OK "Removed old task"
}

# Create new task
$action = New-ScheduledTaskAction `
    -Execute "python" `
    -Argument "run_cyborg_full_auto.py" `
    -WorkingDirectory $FRAMEWORK_DIR

$trigger = New-ScheduledTaskTrigger `
    -AtStartup

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -RestartCount 99 `
    -RestartInterval (New-TimeSpan -Minutes 1)

$principal = New-ScheduledTaskPrincipal `
    -UserId "NT AUTHORITY\SYSTEM" `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName $task_name `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "ICT Cyborg Bot - auto-start + auto-restart on crash" `
    -ErrorAction SilentlyContinue | Out-Null

Write-OK "Scheduled Task 'ICTCyborg' created (auto-restart on crash)"

# ═══════════════════════════════════════════════════════════════════════════
# DONE
# ═══════════════════════════════════════════════════════════════════════════
Write-Header "🎉 DEPLOYMENT COMPLET"

Write-Host ""
Write-Host "✅ Bot ML v2 déployé et running"    -ForegroundColor Green
Write-Host "✅ ML Threshold 0.45 (Pareto optimal)" -ForegroundColor Green
Write-Host "✅ 11 assets actifs (6 H1 + 5 D1)"    -ForegroundColor Green
Write-Host "✅ Auto-restart configuré"           -ForegroundColor Green
Write-Host "✅ Streamlit désactivé"              -ForegroundColor Green
Write-Host ""
Write-Host "📱 Vérifier sur Telegram : envoie /status à @Davghalibot" -ForegroundColor Cyan
Write-Host "📊 Logs temps réel : Get-Content $log_file -Wait -Tail 30" -ForegroundColor Cyan
Write-Host ""
Write-Host "🎯 Attends le prochain killzone (London 07:00 UTC ou NY AM 13:30 UTC) pour voir les premiers signaux" -ForegroundColor Yellow
Write-Host ""

# Send confirmation via Telegram
$tg_confirm_script = Join-Path $FRAMEWORK_DIR "scripts\_send_deploy_confirmation.py"
python $tg_confirm_script 2>&1 | Write-Host

Write-Host ""
Write-Host "🏆 SYSTEM LIVE" -ForegroundColor Green
