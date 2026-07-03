$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "=== Leha Pro Health Check ==="
Write-Host "Root: $Root"
Write-Host ""

Write-Host "== Processes =="
$procs = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -like "python*" -and (
        $_.CommandLine -like "*jarvis_ai.supervisor*" -or
        $_.CommandLine -like "*jarvis_ai.listen*" -or
        $_.CommandLine -like "*jarvis_ai.webserver*" -or
        $_.CommandLine -like "*jarvis_ai.wake_dashboard*"
    )
}
if ($procs) {
    $procs | Select-Object ProcessId, CreationDate, CommandLine | Format-Table -AutoSize
} else {
    Write-Host "No Leha Python processes found."
}
Write-Host ""

Write-Host "== Core Health =="
python -m jarvis_ai.health --json
Write-Host ""

Write-Host "== Mic Self-Test =="
@'
import json
from jarvis_ai.health import mic_self_test
print(json.dumps(mic_self_test(0.35), indent=2))
'@ | python -
Write-Host ""

Write-Host "== Wake Dataset Audit =="
$wakeDirs = @(
    ".\jarvis_ai\voices\wake_leha",
    ".\jarvis_ai\voices\wake_leha_continuous",
    ".\jarvis_ai\voices\wake_leha_retry"
) | Where-Object { Test-Path $_ }
if ($wakeDirs.Count -gt 0) {
    python .\tools\audit_leha_wake_dataset.py @wakeDirs --report .\processed\wake_positive_audit.json
} else {
    Write-Host "No wake-positive directories found."
}
Write-Host ""

Write-Host "== Android ADB =="
try {
    $adb = @'
from jarvis_ai import config
print(config.ADB_PATH)
'@ | python -
    & $adb devices
} catch {
    Write-Host "ADB check failed: $($_.Exception.Message)"
}
Write-Host ""

Write-Host "== Dashboard =="
try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8001/dashboard" -TimeoutSec 5
    Write-Host "Dashboard HTTP: $($response.StatusCode)"
} catch {
    Write-Host "Dashboard HTTP: unavailable ($($_.Exception.Message))"
}
