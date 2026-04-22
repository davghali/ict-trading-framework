# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  FINALIZE.ps1 — LE SCRIPT FINAL CLÉ EN MAIN                             ║
# ║                                                                          ║
# ║  Usage :                                                                 ║
# ║      cd C:\Users\Administrator\ict-trading-framework                     ║
# ║      git pull origin main                                                ║
# ║      .\scripts\FINALIZE.ps1                                              ║
# ║                                                                          ║
# ║  Fait tout en une fois :                                                 ║
# ║    1. Setup UTF-8 (évite charmap errors)                                 ║
# ║    2. Écrit .env + user_data/.env avec les 3 vars (sans BOM) :          ║
# ║         - TELEGRAM_BOT_TOKEN                                             ║
# ║         - TELEGRAM_CHAT_ID (admin)                                       ║
# ║         - TELEGRAM_BROADCAST_CHANNEL_ID (canal membres)                  ║
# ║    3. Kill bot + scheduled tasks                                         ║
# ║    4. Relance DEPLOY_ONE_CLICK.ps1 (16 étapes)                           ║
# ║    5. Envoie un message test dans LES 2 (chat privé + canal)             ║
# ╚══════════════════════════════════════════════════════════════════════════╝

param(
    [string]$Token   = "8709392873:AAGr_GNxNjyS2prG7Lp7HkOcRiZohQjRHJE",
    [string]$ChatId  = "1050705899",
    [string]$Channel = "-1003971706379"
)

$ErrorActionPreference = "Continue"
chcp 65001 | Out-Null
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$FRAMEWORK_DIR = "C:\Users\Administrator\ict-trading-framework"
Set-Location $FRAMEWORK_DIR

function Write-Header($msg) {
    Write-Host ""
    Write-Host "════════════════════════════════════════════════════════════════" -ForegroundColor Yellow
    Write-Host $msg -ForegroundColor Yellow
    Write-Host "════════════════════════════════════════════════════════════════" -ForegroundColor Yellow
}
function Write-OK($msg)   { Write-Host "[OK]   $msg" -ForegroundColor Green }
function Write-Info($msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Err($msg)  { Write-Host "[FAIL] $msg" -ForegroundColor Red }

Write-Header "🏁 FINALIZE — Setup final clé en main"
Write-Host "Token : $($Token.Substring(0, [Math]::Min(15, $Token.Length)))..." -ForegroundColor Gray
Write-Host "Chat admin : $ChatId" -ForegroundColor Gray
Write-Host "Canal broadcast : $Channel" -ForegroundColor Gray

# ──────────────────────────────────────────────────────────────────────────
# STEP A : Write .env + user_data/.env (UTF-8 no BOM)
# ──────────────────────────────────────────────────────────────────────────
Write-Header "A — Écrire .env + user_data/.env (UTF-8 sans BOM)"

$envContent = "TELEGRAM_BOT_TOKEN=$Token`nTELEGRAM_CHAT_ID=$ChatId`nTELEGRAM_BROADCAST_CHANNEL_ID=$Channel`n"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

$envRoot = Join-Path $FRAMEWORK_DIR ".env"
$envUserData = Join-Path $FRAMEWORK_DIR "user_data\.env"

if (-not (Test-Path (Split-Path $envUserData))) {
    New-Item -ItemType Directory -Force -Path (Split-Path $envUserData) | Out-Null
}

[System.IO.File]::WriteAllText($envRoot, $envContent, $utf8NoBom)
[System.IO.File]::WriteAllText($envUserData, $envContent, $utf8NoBom)

Write-OK "Écrit : $envRoot"
Write-OK "Écrit : $envUserData"

Write-Info "Contenu user_data/.env :"
Get-Content $envUserData | ForEach-Object { Write-Host "  $_" -ForegroundColor Gray }

# ──────────────────────────────────────────────────────────────────────────
# STEP B : Test admin chat + broadcast channel
# ──────────────────────────────────────────────────────────────────────────
Write-Header "B — Test Telegram (admin + channel)"

# Admin test
Write-Info "Test admin chat ($ChatId)..."
try {
    $adminBody = @{ chat_id = $ChatId; text = "🧪 Test ADMIN : setup final OK. Chat privé actif." }
    $r1 = Invoke-WebRequest "https://api.telegram.org/bot$Token/sendMessage" `
        -Method POST -Body $adminBody -UseBasicParsing -TimeoutSec 10
    $d1 = $r1.Content | ConvertFrom-Json
    if ($d1.ok) {
        Write-OK "Admin : message test envoyé dans ton chat privé"
    } else {
        Write-Err "Admin : $($d1.description)"
    }
} catch {
    Write-Err "Admin : $_"
}

# Broadcast test
Write-Info "Test broadcast channel ($Channel)..."
try {
    $broadcastBody = @{
        chat_id = $Channel
        text = "📢 Test CANAL : ICT Cyborg Signals actif.`nLes signaux A+ arriveront ici automatiquement."
    }
    $r2 = Invoke-WebRequest "https://api.telegram.org/bot$Token/sendMessage" `
        -Method POST -Body $broadcastBody -UseBasicParsing -TimeoutSec 10
    $d2 = $r2.Content | ConvertFrom-Json
    if ($d2.ok) {
        Write-OK "Canal : message test envoyé dans ICT Cyborg Signals"
    } else {
        Write-Err "Canal : $($d2.description)"
        if ($d2.error_code -eq 400 -or $d2.error_code -eq 403) {
            Write-Host ""
            Write-Host "IMPORTANT : vérifie que @ICTCyborgTradingBot est ADMIN du canal" -ForegroundColor Yellow
            Write-Host "  1. Ouvre le canal ICT Cyborg Signals sur Telegram" -ForegroundColor Yellow
            Write-Host "  2. Gérer le canal -> Administrateurs -> Ajouter admin" -ForegroundColor Yellow
            Write-Host "  3. Cherche ICTCyborgTradingBot -> coche 'Publier des messages'" -ForegroundColor Yellow
            Write-Host "  4. Relance ce script" -ForegroundColor Yellow
        }
    }
} catch {
    Write-Err "Canal : $_"
}

# ──────────────────────────────────────────────────────────────────────────
# STEP C : Kill bot + scheduled tasks, then launch DEPLOY_ONE_CLICK
# ──────────────────────────────────────────────────────────────────────────
Write-Header "C — Lancer DEPLOY_ONE_CLICK.ps1 (full master 16 steps)"

$mainScript = Join-Path $FRAMEWORK_DIR "scripts\DEPLOY_ONE_CLICK.ps1"
if (-not (Test-Path $mainScript)) {
    Write-Err "DEPLOY_ONE_CLICK.ps1 introuvable : $mainScript"
    Write-Host "As-tu fait 'git pull origin main' avant ?" -ForegroundColor Yellow
    exit 1
}

Write-Info "Handover to DEPLOY_ONE_CLICK.ps1..."
Write-Host ""
& $mainScript

# ──────────────────────────────────────────────────────────────────────────
# STEP D : Summary
# ──────────────────────────────────────────────────────────────────────────
Write-Header "🏆 FINALIZATION TERMINÉE"

Write-Host ""
Write-Host "📱 Teste maintenant sur Telegram :" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Dans TON CHAT PRIVÉ avec @ICTCyborgTradingBot :" -ForegroundColor White
Write-Host "    /status      → état système" -ForegroundColor Gray
Write-Host "    /positions   → positions ouvertes" -ForegroundColor Gray
Write-Host "    /pause       → suspendre auto-exec" -ForegroundColor Gray
Write-Host "    /close_all   → URGENCE fermer tout" -ForegroundColor Gray
Write-Host ""
Write-Host "  Dans le CANAL ICT Cyborg Signals :" -ForegroundColor White
Write-Host "    Les signaux A+ arrivent automatiquement (avec boutons)" -ForegroundColor Gray
Write-Host "    TP1 / TP2 / SL hits broadcast aux membres" -ForegroundColor Gray
Write-Host "    Positions fermées notifiées" -ForegroundColor Gray
Write-Host ""
Write-Host "👥 Invite tes membres :" -ForegroundColor Cyan
Write-Host "  Ouvre le canal -> Gérer -> Liens d'invitation -> Créer" -ForegroundColor Gray
Write-Host ""
Write-Host "🎯 Prochain killzone : London 07:00 UTC (09h Paris)" -ForegroundColor Yellow
Write-Host ""
Write-Host "🛌 Tu peux aller dormir. Le bot bosse." -ForegroundColor Green
