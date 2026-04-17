# =============================================================================
# ACTIVATE ULTIMATE — Script PowerShell ONE-CLICK pour AWS Windows
# =============================================================================
# Usage :
#   1. RDP sur AWS Windows
#   2. Ouvrir PowerShell ADMIN
#   3. cd C:\Users\Administrator\ict-trading-framework\scripts
#   4. .\ACTIVATE_ULTIMATE_AWS.ps1
#
# Ce script fait TOUT automatiquement :
# - git pull
# - backup settings.json actuel
# - migration vers settings.json avec les nouvelles options
# - test 60 sec du daemon ultimate
# - bascule Scheduled Task
# - restart
# - vérification finale
# =============================================================================

$ErrorActionPreference = "Continue"
$FRAMEWORK_DIR = "C:\Users\Administrator\ict-trading-framework"

function Log-Step {
    param([string]$Msg, [string]$Color = "Cyan")
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor $Color
    Write-Host "  $Msg" -ForegroundColor $Color
    Write-Host "================================================================" -ForegroundColor $Color
}

function Log-OK { param($M); Write-Host "  [OK] $M" -ForegroundColor Green }
function Log-Warn { param($M); Write-Host "  [WARN] $M" -ForegroundColor Yellow }
function Log-Err { param($M); Write-Host "  [ERR] $M" -ForegroundColor Red }

# =============================================================================
Log-Step "ICT CYBORG ULTIMATE — Activation AWS"
# =============================================================================

if (-not (Test-Path $FRAMEWORK_DIR)) {
    Log-Err "Repo introuvable : $FRAMEWORK_DIR"
    exit 1
}

cd $FRAMEWORK_DIR
Log-OK "Repo trouvé : $FRAMEWORK_DIR"

# =============================================================================
Log-Step "ÉTAPE 1/6 : Git pull"
# =============================================================================

$currentCommit = git rev-parse HEAD
Log-OK "Commit actuel : $($currentCommit.Substring(0,8))"

git pull origin main 2>&1 | ForEach-Object { Write-Host "  $_" }

$newCommit = git rev-parse HEAD
if ($newCommit -eq $currentCommit) {
    Log-Warn "Déjà à jour (aucun nouveau commit)"
} else {
    Log-OK "Mis à jour : $($currentCommit.Substring(0,8)) → $($newCommit.Substring(0,8))"
}

# =============================================================================
Log-Step "ÉTAPE 2/6 : Backup + migration settings.json"
# =============================================================================

$settingsPath = "$FRAMEWORK_DIR\user_data\settings.json"
$examplePath = "$FRAMEWORK_DIR\user_data\settings.json.example"
$backupPath = "$FRAMEWORK_DIR\user_data\settings.backup.$(Get-Date -Format yyyyMMdd_HHmmss).json"

if (Test-Path $settingsPath) {
    Copy-Item $settingsPath $backupPath
    Log-OK "Backup créé : $backupPath"

    # Merge : on garde les valeurs actuelles MAIS on ajoute les nouveaux champs de l'example
    $current = Get-Content $settingsPath | ConvertFrom-Json
    $template = Get-Content $examplePath | ConvertFrom-Json

    # Liste des nouvelles clés Phase 1/2/3
    $newKeys = @(
        "use_multi_partial_exits", "partial_exit_levels",
        "runner_trailing_atr_mult", "runner_target_min_r",
        "use_confluence_filter", "confluence_min_score",
        "confluence_require_smt", "confluence_require_multi_tf",
        "use_dynamic_risk", "dynamic_risk_base", "dynamic_risk_max", "dynamic_risk_min",
        "dynamic_risk_hot_streak_boost", "dynamic_risk_cold_streak_penalty",
        "use_news_ride", "news_ride_wait_minutes", "news_ride_retracement_pct",
        "news_ride_risk_multiplier",
        "use_pyramid", "pyramid_max_adds", "pyramid_add_at_r", "pyramid_add_risk_pct",
        "ml_retrain_frequency", "ml_use_regime_detection",
        "min_grade_sniper"
    )

    # Ajouter les clés manquantes
    foreach ($key in $newKeys) {
        if (-not $current.PSObject.Properties.Name.Contains($key)) {
            $value = $template.$key
            $current | Add-Member -NotePropertyName $key -NotePropertyValue $value
            Log-OK "Ajouté : $key"
        }
    }

    # Étendre les instruments si besoin (sans écraser si utilisateur a custom)
    if ($current.assets_h1.Count -lt 9) {
        $current.assets_h1 = $template.assets_h1
        Log-OK "Instruments H1 étendus à $($template.assets_h1.Count)"
    }
    if ($current.assets_d1.Count -lt 10) {
        $current.assets_d1 = $template.assets_d1
        Log-OK "Instruments D1 étendus à $($template.assets_d1.Count)"
    }

    # Sauvegarde (sans BOM)
    $json = $current | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText($settingsPath, $json)
    Log-OK "settings.json mis à jour (sans BOM)"

} else {
    Log-Warn "settings.json absent — copie depuis example"
    Copy-Item $examplePath $settingsPath
    Log-OK "settings.json créé depuis template"
}

# =============================================================================
Log-Step "ÉTAPE 3/6 : Verification .env et credentials"
# =============================================================================

$envPath = "$FRAMEWORK_DIR\user_data\.env"
$accountsPath = "$FRAMEWORK_DIR\user_data\mt5_accounts.json"

if (-not (Test-Path $envPath)) {
    Log-Err ".env manquant — Telegram ne pourra pas envoyer d'alertes !"
    Log-Warn "Créer manuellement $envPath avec TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID"
} else {
    Log-OK ".env présent"
}

if (-not (Test-Path $accountsPath)) {
    Log-Warn "mt5_accounts.json manquant — le bot ne tradera pas (mais scannera)"
    Log-Warn "Copier mt5_accounts.json.example et remplir les credentials"
} else {
    Log-OK "mt5_accounts.json présent"
}

# =============================================================================
Log-Step "ÉTAPE 4/6 : Test syntaxique run_cyborg_ultimate.py"
# =============================================================================

$testResult = python -c "import ast; ast.parse(open('run_cyborg_ultimate.py').read()); print('OK')" 2>&1
if ($testResult -eq "OK") {
    Log-OK "Syntaxe run_cyborg_ultimate.py : OK"
} else {
    Log-Err "Erreur syntaxe : $testResult"
    exit 1
}

# Test imports
Log-Warn "Test imports modules (5 sec)..."
$importTest = python -c @"
import sys
sys.path.insert(0, '.')
from src.exit_manager import ExitManager
from src.confluence_filter import ConfluenceFilter
from src.dynamic_risk import DynamicRiskManager
from src.news_ride import NewsRideModule
from src.pyramid_manager import PyramidManager
print('ALL_MODULES_OK')
"@ 2>&1

if ($importTest -match "ALL_MODULES_OK") {
    Log-OK "Tous les modules Phase 1/2/3 importables"
} else {
    Log-Err "Erreur import : $importTest"
    exit 1
}

# =============================================================================
Log-Step "ÉTAPE 5/6 : Bascule Scheduled Task"
# =============================================================================

$taskName = "ICTCyborg"
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

if ($existingTask) {
    Log-OK "Task '$taskName' trouvée"

    # Stop
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Log-OK "Task arrêtée"
    Start-Sleep 3

    # New action pointing to ultimate
    $pythonPath = (Get-Command python.exe).Source
    $scriptPath = "$FRAMEWORK_DIR\run_cyborg_ultimate.py"
    $action = New-ScheduledTaskAction `
        -Execute $pythonPath `
        -Argument "`"$scriptPath`"" `
        -WorkingDirectory $FRAMEWORK_DIR

    Set-ScheduledTask -TaskName $taskName -Action $action
    Log-OK "Task reconfigurée pour run_cyborg_ultimate.py"

    # Restart
    Start-ScheduledTask -TaskName $taskName
    Log-OK "Task redémarrée"
    Start-Sleep 5

    # Vérifier état
    $info = Get-ScheduledTaskInfo -TaskName $taskName
    Log-OK "LastRunTime : $($info.LastRunTime)"
    Log-OK "LastResult : $($info.LastTaskResult) (0 = OK)"

} else {
    Log-Err "Task '$taskName' introuvable !"
    Log-Warn "Créer manuellement ou lancer scripts/install_scheduled_task.ps1"
}

# =============================================================================
Log-Step "ÉTAPE 6/6 : Vérification finale"
# =============================================================================

Start-Sleep 10

$pythonProcs = Get-Process python -ErrorAction SilentlyContinue
if ($pythonProcs) {
    Log-OK "Processus Python actifs : $($pythonProcs.Count)"
    $pythonProcs | ForEach-Object {
        Log-OK "  PID $($_.Id) — CPU $([math]::Round($_.CPU,1))s — Mem $([math]::Round($_.WorkingSet/1MB,0))MB"
    }
} else {
    Log-Warn "Aucun processus Python — vérifier les logs"
}

$logFile = "$FRAMEWORK_DIR\cyborg.log"
if (Test-Path $logFile) {
    Log-OK "Dernières lignes du log :"
    Get-Content $logFile -Tail 10 | ForEach-Object { Write-Host "    $_" }
}

# =============================================================================
Log-Step "ACTIVATION TERMINÉE" "Green"
# =============================================================================

Write-Host ""
Write-Host "  ✅ Code Ultimate déployé sur AWS" -ForegroundColor Green
Write-Host "  ✅ settings.json migré (backup conservé)" -ForegroundColor Green
Write-Host "  ✅ Scheduled Task bascule vers run_cyborg_ultimate.py" -ForegroundColor Green
Write-Host ""
Write-Host "  📱 Vérifie Telegram dans 60 sec pour le message '🔴 ICT CYBORG ULTIMATE'" -ForegroundColor Cyan
Write-Host "  🌐 Dashboard : https://ict-quant-david.streamlit.app" -ForegroundColor Cyan
Write-Host "  📊 UptimeRobot te notifie en cas de crash" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Pour rollback d'urgence :" -ForegroundColor Yellow
Write-Host "    Stop-ScheduledTask -TaskName ICTCyborg" -ForegroundColor Yellow
Write-Host "    (puis éditer l'action pour repointer run_cyborg.py)" -ForegroundColor Yellow
Write-Host ""
