# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  FIX TELEGRAM + DEPLOY — le seul script à lancer                        ║
# ║                                                                          ║
# ║  Usage :                                                                 ║
# ║      cd C:\Users\Administrator\ict-trading-framework                     ║
# ║      git pull origin main                                                ║
# ║      .\scripts\FIX_TELEGRAM_AND_DEPLOY.ps1                               ║
# ║                                                                          ║
# ║  Ce script :                                                             ║
# ║   1. Lit TELEGRAM_BOT_TOKEN depuis .env existant                         ║
# ║   2. Appelle getUpdates Telegram pour récupérer ton chat_id auto         ║
# ║   3. Écrit .env + user_data/.env proprement (UTF-8 SANS BOM)             ║
# ║   4. Lance DEPLOY_ONE_CLICK.ps1                                          ║
# ║                                                                          ║
# ║  Prérequis : envoyer /start à @ICTCyborgTradingBot AVANT de lancer       ║
# ╚══════════════════════════════════════════════════════════════════════════╝

$ErrorActionPreference = "Continue"
chcp 65001 | Out-Null
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$FRAMEWORK_DIR = "C:\Users\Administrator\ict-trading-framework"
$ENV_ROOT      = Join-Path $FRAMEWORK_DIR ".env"
$ENV_USERDATA  = Join-Path $FRAMEWORK_DIR "user_data\.env"

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

Set-Location $FRAMEWORK_DIR

Write-Header "🔧 FIX TELEGRAM + DEPLOY (clé en main)"

# ──────────────────────────────────────────────────────────────────────────
# STEP 1 : Lire le token depuis .env existant
# ──────────────────────────────────────────────────────────────────────────
Write-Header "STEP 1 — Extraire TELEGRAM_BOT_TOKEN depuis .env"

$token = $null
foreach ($path in @($ENV_ROOT, $ENV_USERDATA)) {
    if (Test-Path $path) {
        # read with UTF-8 tolerant encoding (handles BOM)
        $content = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
        foreach ($line in $content -split "`r?`n") {
            $clean = $line.TrimStart([char]0xFEFF).Trim()  # strip BOM + whitespace
            if ($clean -match '^TELEGRAM_BOT_TOKEN\s*=\s*(.+)$') {
                $token = $Matches[1].Trim().Trim('"').Trim("'")
                if ($token) {
                    Write-OK "Token trouvé dans $path"
                    break
                }
            }
        }
        if ($token) { break }
    }
}

if (-not $token -or $token -eq "PASTE_YOUR_BOT_TOKEN_HERE") {
    Write-Err "TELEGRAM_BOT_TOKEN introuvable ou template"
    Write-Host ""
    Write-Host "Édite .env et mets ton token @ICTCyborgTradingBot :" -ForegroundColor Yellow
    Write-Host "  notepad $ENV_ROOT" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Contenu attendu :" -ForegroundColor Yellow
    Write-Host "  TELEGRAM_BOT_TOKEN=8709392873:AAGr_GNxNjyS2prG7Lp7HkOcRiZohQjRHJE" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Puis relance ce script." -ForegroundColor Yellow
    exit 1
}

$tokenPreview = $token.Substring(0, [Math]::Min(15, $token.Length)) + "..."
Write-OK "Token : $tokenPreview (length $($token.Length))"

# ──────────────────────────────────────────────────────────────────────────
# STEP 2 : Call Telegram getUpdates to fetch chat_id
# ──────────────────────────────────────────────────────────────────────────
Write-Header "STEP 2 — Récupérer chat_id via Telegram getUpdates"

Write-Info "Appel https://api.telegram.org/bot.../getUpdates ..."
$tgUrl = "https://api.telegram.org/bot$token/getUpdates"
try {
    $resp = Invoke-WebRequest -Uri $tgUrl -UseBasicParsing -TimeoutSec 15
    $data = $resp.Content | ConvertFrom-Json
} catch {
    Write-Err "Appel Telegram failed : $_"
    Write-Host "Vérifie que le token est correct + connection internet OK." -ForegroundColor Yellow
    exit 1
}

if (-not $data.ok) {
    Write-Err "Telegram a retourné : $($data.description)"
    if ($data.error_code -eq 401) {
        Write-Host ""
        Write-Host "Token INVALIDE. Soit tu l'as révoqué via BotFather," -ForegroundColor Yellow
        Write-Host "soit c'est pas le bon. Récupère-le via @BotFather → /mybots." -ForegroundColor Yellow
    }
    exit 1
}

if (-not $data.result -or $data.result.Count -eq 0) {
    Write-Err "Aucun update Telegram trouvé."
    Write-Host ""
    Write-Host "Tu dois d'abord ACTIVER la conversation avec ton bot :" -ForegroundColor Yellow
    Write-Host "  1. Ouvre Telegram" -ForegroundColor Cyan
    Write-Host "  2. Cherche @ICTCyborgTradingBot (ou ton username de bot)" -ForegroundColor Cyan
    Write-Host "  3. Envoie-lui /start" -ForegroundColor Cyan
    Write-Host "  4. Relance ce script" -ForegroundColor Cyan
    exit 1
}

# Prendre le premier message valide avec un chat.id
$chatId = $null
foreach ($update in $data.result) {
    if ($update.message -and $update.message.chat -and $update.message.chat.id) {
        $chatId = $update.message.chat.id
        break
    }
}

if (-not $chatId) {
    Write-Err "Pas de chat.id trouvé dans les updates."
    Write-Host "Envoie un message texte (/start ou autre) à ton bot puis relance." -ForegroundColor Yellow
    exit 1
}

Write-OK "Chat ID détecté : $chatId"

# ──────────────────────────────────────────────────────────────────────────
# STEP 3 : Write .env + user_data/.env in pure UTF-8 (NO BOM)
# ──────────────────────────────────────────────────────────────────────────
Write-Header "STEP 3 — Écrire .env + user_data/.env (UTF-8 sans BOM)"

$content = "TELEGRAM_BOT_TOKEN=$token`nTELEGRAM_CHAT_ID=$chatId`n"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

[System.IO.File]::WriteAllText($ENV_ROOT, $content, $utf8NoBom)
Write-OK "Écrit : $ENV_ROOT"

# Ensure user_data directory exists
$userDataDir = Split-Path $ENV_USERDATA
if (-not (Test-Path $userDataDir)) {
    New-Item -ItemType Directory -Force -Path $userDataDir | Out-Null
}
[System.IO.File]::WriteAllText($ENV_USERDATA, $content, $utf8NoBom)
Write-OK "Écrit : $ENV_USERDATA"

# Verify
Write-Host ""
Write-Info "Contenu de user_data/.env :"
Get-Content $ENV_USERDATA | ForEach-Object { Write-Host "  $_" -ForegroundColor Gray }

# Verify no BOM
$firstBytes = [System.IO.File]::ReadAllBytes($ENV_USERDATA) | Select-Object -First 3
$hex = ($firstBytes | ForEach-Object { $_.ToString("X2") }) -join " "
if ($hex -eq "EF BB BF") {
    Write-Warn "Le fichier contient encore un BOM (bizarre) — le fix Python du commit 76e7f24 le gère"
} else {
    Write-OK "Pas de BOM — encoding propre ($hex...)"
}

# ──────────────────────────────────────────────────────────────────────────
# STEP 4 : Test Telegram live
# ──────────────────────────────────────────────────────────────────────────
Write-Header "STEP 4 — Test envoi Telegram"

$testMsg = "🧪 Test du bot ICT Cyborg — setup OK"
$sendUrl = "https://api.telegram.org/bot$token/sendMessage"
try {
    $body = @{ chat_id = $chatId; text = $testMsg }
    $sendResp = Invoke-WebRequest -Uri $sendUrl -Method POST -Body $body -UseBasicParsing -TimeoutSec 15
    $sendData = $sendResp.Content | ConvertFrom-Json
    if ($sendData.ok) {
        Write-OK "Message de test envoyé → check ton Telegram maintenant"
    } else {
        Write-Warn "Message test non envoyé : $($sendData.description)"
    }
} catch {
    Write-Warn "Test envoi failed : $_ (on continue quand même)"
}

# ──────────────────────────────────────────────────────────────────────────
# STEP 5 : Launch main deploy
# ──────────────────────────────────────────────────────────────────────────
Write-Header "STEP 5 — Lancer DEPLOY_ONE_CLICK.ps1"

$mainScript = Join-Path $FRAMEWORK_DIR "scripts\DEPLOY_ONE_CLICK.ps1"
if (-not (Test-Path $mainScript)) {
    Write-Err "DEPLOY_ONE_CLICK.ps1 introuvable : $mainScript"
    exit 1
}

Write-Info "Launching $mainScript ..."
Write-Host ""
& $mainScript
