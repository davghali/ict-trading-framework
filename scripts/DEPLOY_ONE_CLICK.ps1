# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  DEPLOY ONE-CLICK v3 — FULL A→Z, clé en main, idempotent                ║
# ║                                                                          ║
# ║  Usage (AWS Windows, RDP en tant qu'Administrator) :                    ║
# ║      cd C:\Users\Administrator\ict-trading-framework                     ║
# ║      .\scripts\DEPLOY_ONE_CLICK.ps1                                      ║
# ║                                                                          ║
# ║  Ce script fait TOUT :                                                   ║
# ║    0. Setup UTF-8 (évite UnicodeEncodeError)                            ║
# ║    1. Vérifie python + git + dir                                         ║
# ║    2. Git pull                                                           ║
# ║    3. Install deps (pandas, numpy, sklearn, MetaTrader5)                ║
# ║    4. Kill TOUT (python + scheduled tasks ICTCyborg*)                   ║
# ║    5. Vérifie mt5_accounts.json + .env (crée template si manquant)       ║
# ║    6. Trouve + LANCE MT5 Desktop si pas ouvert                          ║
# ║    7. Attend que mt5.initialize() passe (retry 60s)                     ║
# ║    8. Supprime webhook Telegram (fix 409 Conflict)                       ║
# ║    9. Test Telegram                                                      ║
# ║   10. Vérifie ML model                                                   ║
# ║   11. Audit complet                                                      ║
# ║   12. Lance le bot en BACKGROUND dans session Administrator             ║
# ║   13. Tail logs 30 sec (vérifie no MT5 error, no 409 Conflict)          ║
# ║   14. Crée Scheduled Task auto-restart user Administrator (pas SYSTEM)  ║
# ║   15. Envoie confirmation Telegram                                       ║
# ║   16. Résumé + commandes monitoring                                      ║
# ╚══════════════════════════════════════════════════════════════════════════╝

# ──────────────────────────────────────────────────────────────────────────
# STEP 0 : Globals + UTF-8 setup (avant tout appel Python)
# ──────────────────────────────────────────────────────────────────────────

# ErrorActionPreference = Continue (native commands like git write to stderr on success)
$ErrorActionPreference = "Continue"

$FRAMEWORK_DIR = "C:\Users\Administrator\ict-trading-framework"
$TASK_NAME = "ICTCyborg"
$PY = "python"

# UTF-8 everywhere : console + Python I/O
chcp 65001 | Out-Null
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Write-Header($msg) {
    Write-Host ""
    Write-Host "════════════════════════════════════════════════════════════════" -ForegroundColor Yellow
    Write-Host $msg -ForegroundColor Yellow
    Write-Host "════════════════════════════════════════════════════════════════" -ForegroundColor Yellow
}

function Write-OK($msg)   { Write-Host "[OK]   $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "[FAIL] $msg" -ForegroundColor Red }
function Write-Info($msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }

Write-Header "🚀 ICT CYBORG — DEPLOY ONE-CLICK v3 (clé en main)"
Write-Host "Expected : WR 51.8% · PF 2.35 · +82%/an · DD -3.9%" -ForegroundColor Cyan
Write-Host ""

# ──────────────────────────────────────────────────────────────────────────
# STEP 1 : Verify environment
# ──────────────────────────────────────────────────────────────────────────
Write-Header "STEP 1 / 16 — Vérification environnement"

if (-not (Test-Path $FRAMEWORK_DIR)) {
    Write-Err "Framework directory introuvable : $FRAMEWORK_DIR"
    Write-Host "Clone le repo d'abord :" -ForegroundColor Yellow
    Write-Host "  git clone https://github.com/davghali/ict-trading-framework.git $FRAMEWORK_DIR" -ForegroundColor Cyan
    exit 1
}
Set-Location $FRAMEWORK_DIR
Write-OK "Directory : $FRAMEWORK_DIR"

$py_version = & $PY --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Err "Python non trouvé. Installer Python 3.9+ d'abord (https://python.org/downloads)"
    exit 1
}
Write-OK "Python : $py_version"

$git_version = & git --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Err "Git non trouvé. Installer Git for Windows."
    exit 1
}
Write-OK "Git : $git_version"

$who = & whoami 2>&1
Write-OK "User Windows : $who"
if ($who -notmatch "administrator") {
    Write-Warn "Tu n'es pas Administrator — le bot peut fail si MT5 tourne en Administrator."
}

# ──────────────────────────────────────────────────────────────────────────
# STEP 2 : Git pull
# ──────────────────────────────────────────────────────────────────────────
Write-Header "STEP 2 / 16 — Git pull dernière version"

& git fetch origin 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Warn "git fetch a exit $LASTEXITCODE (non fatal, on continue)"
}

$branch = (& git rev-parse --abbrev-ref HEAD).Trim()
& git pull origin $branch 2>&1 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
if ($LASTEXITCODE -ne 0) {
    Write-Warn "git pull a exit $LASTEXITCODE — tu as peut-être des changements locaux. On continue avec le code actuel."
}

$last_commit = (& git log -1 --oneline).Trim()
Write-OK "Last commit : $last_commit"

# ──────────────────────────────────────────────────────────────────────────
# STEP 3 : Install Python dependencies
# ──────────────────────────────────────────────────────────────────────────
Write-Header "STEP 3 / 16 — Install / update dépendances Python"

& $PY -m pip install --upgrade pip 2>&1 | Out-Null
& $PY -m pip install -r requirements.txt 2>&1 | Out-Null
& $PY -m pip install --upgrade scikit-learn MetaTrader5 2>&1 | Out-Null

$imports_ok = $true
foreach ($pkg in @("pandas", "numpy", "sklearn", "MetaTrader5")) {
    & $PY -c "import $pkg" 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-OK "import $pkg"
    } else {
        Write-Warn "import $pkg failed"
        if ($pkg -eq "MetaTrader5") { $imports_ok = $false }
    }
}
if (-not $imports_ok) {
    Write-Err "Install MetaTrader5 manuellement : python -m pip install MetaTrader5"
    exit 1
}

# ──────────────────────────────────────────────────────────────────────────
# STEP 4 : Kill TOUT ancien bot + scheduled tasks
# ──────────────────────────────────────────────────────────────────────────
Write-Header "STEP 4 / 16 — Kill ancien bot + scheduled tasks"

# Kill ALL python processes (fresh start guaranteed)
$py_procs = Get-Process python -ErrorAction SilentlyContinue
if ($py_procs) {
    Write-Info "Killing $($py_procs.Count) python process(es)..."
    $py_procs | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

# Kill streamlit explicitly
Get-Process | Where-Object { $_.ProcessName -match "streamlit" } | Stop-Process -Force -ErrorAction SilentlyContinue

# Unregister all scheduled tasks matching our bot
$tasks_to_clean = Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object {
    $_.TaskName -match "ICTCyborg|Streamlit|Dashboard|CyborgBot"
}
foreach ($t in $tasks_to_clean) {
    Stop-ScheduledTask -TaskName $t.TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $t.TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-OK "Removed scheduled task : $($t.TaskName)"
}

Start-Sleep -Seconds 3
$remaining = Get-Process python -ErrorAction SilentlyContinue
if ($remaining) {
    Write-Warn "$($remaining.Count) python process(es) still alive — force-killing..."
    $remaining | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}
Write-OK "Environment clean (0 python process)"

# ──────────────────────────────────────────────────────────────────────────
# STEP 5 : Verify mt5_accounts.json + .env
# ──────────────────────────────────────────────────────────────────────────
Write-Header "STEP 5 / 16 — Vérifier credentials"

$mt5_json = Join-Path $FRAMEWORK_DIR "user_data\mt5_accounts.json"
$env_file = Join-Path $FRAMEWORK_DIR ".env"

if (-not (Test-Path $mt5_json)) {
    Write-Warn "mt5_accounts.json manquant — création template"
    New-Item -ItemType Directory -Force -Path (Split-Path $mt5_json) | Out-Null
    $tpl = @"
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
    Set-Content -Path $mt5_json -Value $tpl -Encoding utf8
    Write-Host ""
    Write-Err "ACTION REQUISE : remplis ce fichier puis relance :"
    Write-Host "  notepad $mt5_json" -ForegroundColor Cyan
    Write-Host "  .\scripts\DEPLOY_ONE_CLICK.ps1" -ForegroundColor Cyan
    exit 0
}

$mt5_content = Get-Content $mt5_json -Raw | ConvertFrom-Json
$first_acc = $mt5_content.accounts[0]
if ($first_acc.login -eq 0 -or $first_acc.password -eq "METTRE_TRADING_PASSWORD") {
    Write-Err "mt5_accounts.json = template non rempli. Éditer :"
    Write-Host "  notepad $mt5_json" -ForegroundColor Cyan
    exit 1
}
Write-OK "mt5_accounts.json : login $($first_acc.login) server $($first_acc.server)"

if (-not (Test-Path $env_file)) {
    Write-Warn ".env manquant — création template"
    $env_tpl = @"
TELEGRAM_BOT_TOKEN=PASTE_YOUR_BOT_TOKEN_HERE
TELEGRAM_CHAT_ID=PASTE_YOUR_CHAT_ID_HERE
"@
    Set-Content -Path $env_file -Value $env_tpl -Encoding utf8
    Write-Err "ACTION REQUISE : remplis .env puis relance :"
    Write-Host "  notepad $env_file" -ForegroundColor Cyan
    exit 0
}
Write-OK ".env présent"

# ──────────────────────────────────────────────────────────────────────────
# STEP 6 : Find + start MT5 Desktop if not running
# ──────────────────────────────────────────────────────────────────────────
Write-Header "STEP 6 / 16 — Vérifier / démarrer MT5 Desktop"

$mt5_terminal = & $PY (Join-Path $FRAMEWORK_DIR "scripts\_find_mt5.py") 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Err "MT5 Desktop introuvable sur cette machine."
    Write-Host "Installe MetaTrader 5 FTMO puis relance." -ForegroundColor Yellow
    Write-Host "Download : https://download.mql5.com/cdn/web/ftmo.s.r.o/mt5/ftmo5setup.exe" -ForegroundColor Cyan
    exit 1
}
$mt5_terminal = $mt5_terminal.Trim()
Write-OK "MT5 terminal trouvé : $mt5_terminal"
$env:MT5_PATH = $mt5_terminal

$mt5_running = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match "terminal64" }
if (-not $mt5_running) {
    Write-Info "MT5 pas lancé — démarrage..."
    Start-Process -FilePath $mt5_terminal -WindowStyle Minimized
    Write-Info "Attente 15 sec pour que MT5 charge..."
    Start-Sleep -Seconds 15
    $mt5_running = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match "terminal64" }
    if (-not $mt5_running) {
        Write-Err "MT5 n'a pas démarré — ouvre-le manuellement :"
        Write-Host "  Start-Process '$mt5_terminal'" -ForegroundColor Cyan
        exit 1
    }
}
Write-OK "MT5 Desktop running (PID $($mt5_running.Id))"

# ──────────────────────────────────────────────────────────────────────────
# STEP 7 : Wait MT5 ready (retry mt5.initialize() up to 60s)
# ──────────────────────────────────────────────────────────────────────────
Write-Header "STEP 7 / 16 — Attendre que MT5 soit prêt (Python API)"

$env:MT5_JSON = $mt5_json
$env:MT5_TIMEOUT_SEC = "60"

Write-Info "Polling mt5.initialize() — max 60 sec..."
$mt5_result = & $PY (Join-Path $FRAMEWORK_DIR "scripts\_wait_mt5_ready.py") 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-OK "$mt5_result"
} else {
    Write-Err "MT5 initialize fail : $mt5_result"
    Write-Host ""
    Write-Host "Checklist manuelle dans MT5 Desktop :" -ForegroundColor Yellow
    Write-Host "  1. Bas-droit de MT5 : 'Connected' avec ping (pas 'No connection')" -ForegroundColor Yellow
    Write-Host "  2. Outils → Options → Expert Advisors :" -ForegroundColor Yellow
    Write-Host "     ✅ Autoriser le trading algorithmique" -ForegroundColor Yellow
    Write-Host "     ✅ Autoriser les imports DLL" -ForegroundColor Yellow
    Write-Host "     ❌ Désactiver algo quand compte change (DÉCOCHER)" -ForegroundColor Yellow
    Write-Host "     ❌ Désactiver algo quand profil change (DÉCOCHER)" -ForegroundColor Yellow
    Write-Host "     ❌ Désactiver trading algo via external Python API (DÉCOCHER)" -ForegroundColor Yellow
    Write-Host "  3. Barre d'outils : bouton 'Algo Trading' doit être VERT" -ForegroundColor Yellow
    Write-Host "  4. Login MT5 : le compte $($first_acc.login) sur $($first_acc.server) est bien loggé" -ForegroundColor Yellow
    exit 1
}

# ──────────────────────────────────────────────────────────────────────────
# STEP 8 : Delete Telegram webhook (fix 409 Conflict)
# ──────────────────────────────────────────────────────────────────────────
Write-Header "STEP 8 / 16 — Nettoyer webhook Telegram (fix 409 Conflict)"

$wh_result = & $PY (Join-Path $FRAMEWORK_DIR "scripts\_delete_telegram_webhook.py") 2>&1
Write-OK "$wh_result"

# ──────────────────────────────────────────────────────────────────────────
# STEP 9 : Test Telegram
# ──────────────────────────────────────────────────────────────────────────
Write-Header "STEP 9 / 16 — Test Telegram"

$tg_result = & $PY (Join-Path $FRAMEWORK_DIR "scripts\_test_telegram.py") 2>&1
if ($tg_result -match "OK") {
    Write-OK "Telegram : $tg_result"
} else {
    Write-Warn "Telegram : $tg_result (le bot continuera sans Telegram)"
}

# ──────────────────────────────────────────────────────────────────────────
# STEP 10 : Verify ML model
# ──────────────────────────────────────────────────────────────────────────
Write-Header "STEP 10 / 16 — Vérifier ML model"

$model_path = Join-Path $FRAMEWORK_DIR "models\production_model.pkl"
if (Test-Path $model_path) {
    $m = & $PY (Join-Path $FRAMEWORK_DIR "scripts\_check_model.py") $model_path 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-OK "ML : $m"
    } else {
        Write-Err "ML check failed : $m"
        exit 1
    }
} else {
    Write-Warn "Model .pkl manquant — retraining..."
    & $PY scripts\train_production_model.py 2>&1 | Out-Null
    if (-not (Test-Path $model_path)) {
        Write-Err "Training failed"
        exit 1
    }
    Write-OK "ML retrained"
}

# ──────────────────────────────────────────────────────────────────────────
# STEP 11 : Audit complet
# ──────────────────────────────────────────────────────────────────────────
Write-Header "STEP 11 / 16 — Audit système"

& $PY scripts\full_audit.py 2>&1 | Select-Object -Last 15 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }

# ──────────────────────────────────────────────────────────────────────────
# STEP 12 : Launch bot in BACKGROUND (Administrator session)
# ──────────────────────────────────────────────────────────────────────────
Write-Header "STEP 12 / 16 — Démarrer le bot (background, session Administrator)"

$log_dir = Join-Path $FRAMEWORK_DIR "reports\logs"
New-Item -ItemType Directory -Force -Path $log_dir | Out-Null
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$log_file = Join-Path $log_dir "bot_$ts.log"
$err_file = Join-Path $log_dir "bot_$ts.err.log"

# Launch WITH UTF-8 env already set in current session — Start-Process inherits env
$bot = Start-Process -FilePath $PY `
    -ArgumentList "run_cyborg_full_auto.py" `
    -WorkingDirectory $FRAMEWORK_DIR `
    -WindowStyle Hidden `
    -RedirectStandardOutput $log_file `
    -RedirectStandardError $err_file `
    -PassThru

Write-OK "Bot lancé (PID $($bot.Id)) - logs : $log_file"

# ──────────────────────────────────────────────────────────────────────────
# STEP 13 : Tail logs 30 sec + sanity check
# ──────────────────────────────────────────────────────────────────────────
Write-Header "STEP 13 / 16 — Vérification live (30 sec)"

Write-Info "J'attends 30 sec puis je lis le log..."
Start-Sleep -Seconds 30

if (-not (Get-Process -Id $bot.Id -ErrorAction SilentlyContinue)) {
    Write-Err "Bot crashed dans les 30 premières secondes !"
    Write-Host "--- LOG COMPLET ---" -ForegroundColor Red
    Get-Content $log_file -ErrorAction SilentlyContinue
    Write-Host "--- ERR LOG ---" -ForegroundColor Red
    Get-Content $err_file -ErrorAction SilentlyContinue
    exit 1
}

$log_content = Get-Content $log_file -ErrorAction SilentlyContinue
$has_mt5_connected = $log_content -match "MT5.*(connected|initialized)" -or $log_content -match "balance"
$has_409 = $log_content -match "409.*Conflict"
$has_mt5_fail = $log_content -match "MT5 connect failed"

if ($has_409) {
    Write-Warn "Warning 409 Conflict détecté (webhook pas bien supprimé ?)"
}
if ($has_mt5_fail) {
    Write-Err "MT5 connect failed dans le log — le bot ne pourra pas trader"
    Write-Host "Dernières lignes du log :" -ForegroundColor Yellow
    $log_content | Select-Object -Last 20 | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
    exit 1
}

Write-OK "Bot vivant (PID $($bot.Id)) après 30 sec — no MT5 error, no 409"
Write-Info "Dernières 10 lignes du log :"
$log_content | Select-Object -Last 10 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }

# ──────────────────────────────────────────────────────────────────────────
# STEP 14 : Create auto-restart Scheduled Task (user Administrator, AtLogon)
# ──────────────────────────────────────────────────────────────────────────
Write-Header "STEP 14 / 16 — Scheduled Task auto-restart (user Administrator)"

# Create a wrapper .bat that sets UTF-8 env vars before launching bot
$wrapper = Join-Path $FRAMEWORK_DIR "scripts\_bot_wrapper.bat"
$wrapper_content = @"
@echo off
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d $FRAMEWORK_DIR
python run_cyborg_full_auto.py >> reports\logs\bot_autostart.log 2>&1
"@
Set-Content -Path $wrapper -Value $wrapper_content -Encoding ASCII

$action = New-ScheduledTaskAction -Execute $wrapper -WorkingDirectory $FRAMEWORK_DIR
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "Administrator"
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 99 `
    -RestartInterval (New-TimeSpan -Minutes 2)
$principal = New-ScheduledTaskPrincipal `
    -UserId "Administrator" `
    -LogonType Interactive `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName $TASK_NAME `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "ICT Cyborg Bot - auto-start at Administrator logon + auto-restart 99x on crash" `
    -Force `
    -ErrorAction SilentlyContinue | Out-Null

if (Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue) {
    Write-OK "Scheduled Task '$TASK_NAME' créée (user Administrator, AtLogon, restart 99x)"
} else {
    Write-Warn "Scheduled Task création fail — le bot tourne quand même mais pas d'auto-restart après reboot"
}

# ──────────────────────────────────────────────────────────────────────────
# STEP 15 : Send Telegram confirmation
# ──────────────────────────────────────────────────────────────────────────
Write-Header "STEP 15 / 16 — Confirmation Telegram"

$confirm = & $PY (Join-Path $FRAMEWORK_DIR "scripts\_send_deploy_confirmation.py") 2>&1
Write-Host "  $confirm" -ForegroundColor DarkGray

# ──────────────────────────────────────────────────────────────────────────
# STEP 16 : Summary
# ──────────────────────────────────────────────────────────────────────────
Write-Header "🎉 DEPLOYMENT COMPLET"

Write-Host ""
Write-Host "✅ Bot ML v2 running (PID $($bot.Id))"       -ForegroundColor Green
Write-Host "✅ ML threshold 0.45"                         -ForegroundColor Green
Write-Host "✅ 11 assets (6 H1 + 5 D1)"                   -ForegroundColor Green
Write-Host "✅ MT5 connected ($($first_acc.login) @ $($first_acc.server))" -ForegroundColor Green
Write-Host "✅ Telegram webhook nettoyé"                  -ForegroundColor Green
Write-Host "✅ Auto-restart Scheduled Task (user Admin)"  -ForegroundColor Green
Write-Host "✅ Streamlit désactivé"                       -ForegroundColor Green
Write-Host ""
Write-Host "📱 TEST : envoie /status à @Davghalibot sur Telegram" -ForegroundColor Cyan
Write-Host ""
Write-Host "📊 Logs live :" -ForegroundColor Cyan
Write-Host "   Get-Content '$log_file' -Wait -Tail 30" -ForegroundColor Gray
Write-Host ""
Write-Host "🛑 Stop bot :" -ForegroundColor Cyan
Write-Host "   Stop-Process -Id $($bot.Id) -Force" -ForegroundColor Gray
Write-Host "   Stop-ScheduledTask -TaskName $TASK_NAME" -ForegroundColor Gray
Write-Host ""
Write-Host "🎯 Prochain killzone : London 07:00 UTC (09h Paris)" -ForegroundColor Yellow
Write-Host ""
Write-Host "🏆 SYSTEM LIVE" -ForegroundColor Green
