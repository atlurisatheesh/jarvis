$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Out = Join-Path $Root "logs\leha-supervisor.out.log"
$Err = Join-Path $Root "logs\leha-supervisor.err.log"
$WebOut = Join-Path $Root "logs\leha-webserver.out.log"
$WebErr = Join-Path $Root "logs\leha-webserver.err.log"
New-Item -ItemType Directory -Force -Path (Join-Path $Root "logs") | Out-Null

$existing = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "python.exe" -and ($_.CommandLine -like "*jarvis_ai.supervisor*" -or $_.CommandLine -like "*jarvis_ai.listen*")
}
if ($existing) {
    Write-Host "Leha is already running:"
    $existing | Select-Object ProcessId, CommandLine | Format-Table -AutoSize
}
else {
    $python = (Get-Command python).Source
    Start-Process -FilePath $python -ArgumentList @("-u","-m","jarvis_ai.supervisor") `
        -WorkingDirectory $Root -RedirectStandardOutput $Out -RedirectStandardError $Err `
        -WindowStyle Hidden
}

$web = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "python.exe" -and $_.CommandLine -like "*jarvis_ai.webserver*"
}
if (-not $web) {
    if (-not $python) { $python = (Get-Command python).Source }
    Start-Process -FilePath $python -ArgumentList @("-u","-m","jarvis_ai.webserver") `
        -WorkingDirectory $Root -RedirectStandardOutput $WebOut -RedirectStandardError $WebErr `
        -WindowStyle Hidden
} else {
    Write-Host "Leha dashboard server is already running."
}
Start-Sleep -Seconds 3
Write-Host "Leha start requested. Check status with scripts\status_leha.ps1"
