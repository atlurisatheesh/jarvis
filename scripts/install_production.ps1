$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "Installing Leha production runtime..."

& (Join-Path $Root "scripts\install_autostart.ps1")
& (Join-Path $Root "scripts\start_leha.ps1")

try {
    & (Join-Path $Root "scripts\start_tray.ps1")
} catch {
    Write-Host "Tray start skipped: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "Running validation..."
& (Join-Path $Root "scripts\validate_startup.ps1")

Write-Host ""
Write-Host "Production install complete."
Write-Host "Dashboard: http://127.0.0.1:8001/dashboard"
