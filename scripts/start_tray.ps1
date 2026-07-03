$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$existing = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "python.exe" -and $_.CommandLine -like "*jarvis_ai.wake_dashboard*"
}
if ($existing) {
    Write-Host "Leha tray is already running:"
    $existing | Select-Object ProcessId, CommandLine | Format-Table -AutoSize
    exit 0
}
$python = (Get-Command python).Source
Start-Process -FilePath $python -ArgumentList @("-m","jarvis_ai.wake_dashboard") `
    -WorkingDirectory $Root -WindowStyle Hidden
Write-Host "Leha tray dashboard start requested."
