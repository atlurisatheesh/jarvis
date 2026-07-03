$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
& (Join-Path $Root "scripts\stop_leha.ps1")
Start-Sleep -Seconds 2
& (Join-Path $Root "scripts\start_leha.ps1")
