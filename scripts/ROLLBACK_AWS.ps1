# =============================================================================
# ROLLBACK — revenir à run_cyborg.py en cas de problème
# =============================================================================
# Usage : .\ROLLBACK_AWS.ps1
# =============================================================================

$FRAMEWORK_DIR = "C:\Users\Administrator\ict-trading-framework"
$taskName = "ICTCyborg"

Write-Host "=== ROLLBACK vers run_cyborg.py (stable) ===" -ForegroundColor Yellow

Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Start-Sleep 3

$pythonPath = (Get-Command python.exe).Source
$scriptPath = "$FRAMEWORK_DIR\run_cyborg.py"
$action = New-ScheduledTaskAction `
    -Execute $pythonPath `
    -Argument "`"$scriptPath`"" `
    -WorkingDirectory $FRAMEWORK_DIR

Set-ScheduledTask -TaskName $taskName -Action $action
Start-ScheduledTask -TaskName $taskName

Write-Host "[OK] Rollback effectué — run_cyborg.py actif" -ForegroundColor Green
Write-Host "Pour désactiver une phase sans rollback complet :" -ForegroundColor Yellow
Write-Host '  → Éditer user_data\settings.json : mettre "use_X": false' -ForegroundColor Yellow
