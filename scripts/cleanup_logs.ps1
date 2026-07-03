$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$result = python -c "from jarvis_ai import log_manager; print(log_manager.cleanup_old_logs())"

Write-Host "Removed old log files: $result"
