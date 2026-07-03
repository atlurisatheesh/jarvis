$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$procs = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "python.exe" -and (
        $_.CommandLine -like "*jarvis_ai.supervisor*" -or
        $_.CommandLine -like "*jarvis_ai.listen*" -or
        $_.CommandLine -like "*jarvis_ai.webserver*" -or
        $_.CommandLine -like "*jarvis_ai.wake_dashboard*"
    )
}
if ($procs) {
    Write-Host "Leha processes:"
    $procs | Select-Object ProcessId, CreationDate, CommandLine | Format-Table -AutoSize
} else {
    Write-Host "Leha is not running."
}
Write-Host ""
python -m jarvis_ai.health --json
Write-Host ""
try {
    $code = (Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8001/dashboard" -TimeoutSec 5).StatusCode
    Write-Host "Dashboard HTTP: $code"
} catch {
    Write-Host "Dashboard HTTP: unavailable ($($_.Exception.Message))"
}
