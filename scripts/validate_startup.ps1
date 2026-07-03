$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "== Leha startup validation =="

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "FAIL: python not found on PATH"
    exit 1
}
Write-Host "OK: python = $($python.Source)"

Write-Host ""
Write-Host "== Compile check =="
python -m compileall -q jarvis_ai
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: compileall failed"
    exit 1
}
Write-Host "OK: compileall passed"

Write-Host ""
Write-Host "== Health =="
python -m jarvis_ai.health --json
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: health command failed"
    exit 1
}

Write-Host ""
Write-Host "== Dashboard =="
try {
    $code = (Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8001/dashboard" -TimeoutSec 5).StatusCode
    Write-Host "OK: dashboard HTTP $code"
} catch {
    Write-Host "WARN: dashboard not reachable. Start with scripts\start_leha.ps1"
}

Write-Host ""
Write-Host "== Autostart task =="
try {
    $task = Get-ScheduledTask -TaskName "Leha" -ErrorAction Stop
    Write-Host "OK: scheduled task present ($($task.State))"
} catch {
    Write-Host "INFO: scheduled task not installed"
}

Write-Host ""
Write-Host "Validation complete."
