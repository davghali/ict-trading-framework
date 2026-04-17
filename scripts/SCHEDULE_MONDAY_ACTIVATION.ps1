# ============================================================
# SCHEDULE MONDAY ACTIVATION - Auto-activate Full Auto Monday morning
# ============================================================
# Usage (a executer UNE FOIS maintenant, ce weekend) :
#   cd C:\Users\Administrator\ict-trading-framework\scripts
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#   .\SCHEDULE_MONDAY_ACTIVATION.ps1
#
# Ce script :
# 1. Installe une Scheduled Task one-shot "ICTCyborgMondayActivation"
# 2. Fixee au prochain lundi 6h50 UTC (8h50 Paris heure d'ete)
# 3. Au declenchement, lance ACTIVATE_FULL_AUTO_AWS.ps1
# 4. Bot passe automatiquement en full auto avant l'ouverture marches
#
# Tu n'as plus RIEN a faire lundi matin.
# ============================================================

$ErrorActionPreference = "Continue"
$FRAMEWORK_DIR = "C:\Users\Administrator\ict-trading-framework"
$TASK_NAME = "ICTCyborgMondayActivation"
$TARGET_SCRIPT = "$FRAMEWORK_DIR\scripts\ACTIVATE_FULL_AUTO_AWS.ps1"

function OK($m) { Write-Host "  [OK] $m" -ForegroundColor Green }
function WARN($m) { Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function ERR($m) { Write-Host "  [ERROR] $m" -ForegroundColor Red }


Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  SCHEDULE MONDAY ACTIVATION" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""


# Step 1: Git pull to ensure ACTIVATE_FULL_AUTO script exists
Set-Location $FRAMEWORK_DIR
Write-Host "Step 1/4 - Git pull to ensure latest scripts..." -ForegroundColor Cyan
git pull origin main 2>&1 | ForEach-Object { Write-Host "  $_" }

if (-not (Test-Path $TARGET_SCRIPT)) {
    ERR "ACTIVATE_FULL_AUTO_AWS.ps1 not found after pull"
    exit 1
}
OK "Script target found: $TARGET_SCRIPT"


# Step 2: Calculate next Monday 6h50 UTC
Write-Host ""
Write-Host "Step 2/4 - Calculate next Monday 6h50 UTC..." -ForegroundColor Cyan

$nowUtc = [DateTime]::UtcNow
$daysUntilMonday = [int]([DayOfWeek]::Monday - $nowUtc.DayOfWeek)
if ($daysUntilMonday -le 0) {
    $daysUntilMonday += 7
}

# Si on est dimanche et il est avant 6h50 UTC, fire demain
# Si on est lundi et il est avant 6h50 UTC, fire aujourd'hui
$nextMondayDate = $nowUtc.Date.AddDays($daysUntilMonday)
$targetTimeUtc = $nextMondayDate.AddHours(6).AddMinutes(50)

# If we're already Monday before 6h50 UTC, fire today
if ($nowUtc.DayOfWeek -eq [DayOfWeek]::Monday -and $nowUtc.Hour -lt 6 -or ($nowUtc.Hour -eq 6 -and $nowUtc.Minute -lt 50)) {
    $targetTimeUtc = $nowUtc.Date.AddHours(6).AddMinutes(50)
}

# Convert to local time for display
$targetTimeLocal = $targetTimeUtc.ToLocalTime()

OK "Target time UTC   : $($targetTimeUtc.ToString('yyyy-MM-dd HH:mm'))"
OK "Target time Local : $($targetTimeLocal.ToString('yyyy-MM-dd HH:mm'))"


# Step 3: Remove any existing scheduled activation
Write-Host ""
Write-Host "Step 3/4 - Remove existing activation task (if any)..." -ForegroundColor Cyan

$existing = Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false
    OK "Existing task removed"
} else {
    OK "No existing task to remove"
}


# Step 4: Create new Scheduled Task
Write-Host ""
Write-Host "Step 4/4 - Create Scheduled Task..." -ForegroundColor Cyan

# Action: run PowerShell with our script
$powershellPath = (Get-Command powershell.exe).Source
$arguments = "-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File `"$TARGET_SCRIPT`""

$action = New-ScheduledTaskAction `
    -Execute $powershellPath `
    -Argument $arguments `
    -WorkingDirectory $FRAMEWORK_DIR

# Trigger: one-shot at target time
$trigger = New-ScheduledTaskTrigger -Once -At $targetTimeLocal

# Settings: run even if user not logged in, allow parallel
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable:$false `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

# Principal: SYSTEM for full privileges
$principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

try {
    Register-ScheduledTask `
        -TaskName $TASK_NAME `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "Auto-activate ICT Cyborg FULL AUTO Monday 6h50 UTC" `
        -Force | Out-Null
    OK "Task '$TASK_NAME' registered successfully"
} catch {
    ERR "Failed to register task: $_"
    exit 1
}


# Verify
Write-Host ""
$task = Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue
if ($task) {
    $info = Get-ScheduledTaskInfo -TaskName $TASK_NAME
    OK "NextRunTime: $($info.NextRunTime)"
    OK "State: $($task.State)"
}


# Send Telegram notification (optional)
Write-Host ""
Write-Host "Step 5/5 - Send Telegram confirmation..." -ForegroundColor Cyan
$envPath = Join-Path $FRAMEWORK_DIR "user_data\.env"
if (Test-Path $envPath) {
    $envContent = Get-Content $envPath -Raw
    if ($envContent -match "TELEGRAM_BOT_TOKEN=([^\s]+)") {
        $token = $matches[1]
        if ($envContent -match "TELEGRAM_CHAT_ID=([^\s]+)") {
            $chatId = $matches[1]
            $msg = "Monday activation SCHEDULED for $($targetTimeUtc.ToString('yyyy-MM-dd HH:mm')) UTC. Bot passera en FULL AUTO automatiquement."
            try {
                $body = @{ chat_id = $chatId; text = $msg } | ConvertTo-Json
                Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/sendMessage" `
                    -Method POST -Body $body -ContentType "application/json" | Out-Null
                OK "Telegram confirmation sent"
            } catch {
                WARN "Telegram send failed (not critical)"
            }
        }
    }
}


Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  AUTO-ACTIVATION MONDAY SCHEDULED" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Target time : $($targetTimeUtc.ToString('yyyy-MM-dd HH:mm')) UTC" -ForegroundColor Green
Write-Host "  Local time  : $($targetTimeLocal.ToString('yyyy-MM-dd HH:mm'))" -ForegroundColor Green
Write-Host ""
Write-Host "  Ce qui va se passer automatiquement lundi :" -ForegroundColor Cyan
Write-Host "  1. git pull (derniere version du code)" -ForegroundColor Cyan
Write-Host "  2. pip install MetaTrader5 (si pas installe)" -ForegroundColor Cyan
Write-Host "  3. Verification mt5_accounts.json + settings.json" -ForegroundColor Cyan
Write-Host "  4. Bascule Scheduled Task vers run_cyborg_full_auto.py" -ForegroundColor Cyan
Write-Host "  5. Bot demarre en FULL AUTO mode" -ForegroundColor Cyan
Write-Host "  6. Telegram message de confirmation" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Pour annuler :" -ForegroundColor Yellow
Write-Host "  Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:`$false" -ForegroundColor Yellow
Write-Host ""
Write-Host "  IMPORTANT AVANT LUNDI :" -ForegroundColor Yellow
Write-Host "  1. Verifier mt5_accounts.json a le bon password FTMO" -ForegroundColor Yellow
Write-Host "  2. Ouvrir MT5 terminal sur AWS et login (reste ouvert)" -ForegroundColor Yellow
Write-Host "  3. Reset password FTMO si pas encore fait (trader.ftmo.com)" -ForegroundColor Yellow
Write-Host ""
