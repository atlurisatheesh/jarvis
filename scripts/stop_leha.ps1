$ErrorActionPreference = "Stop"
$targets = Get-CimInstance Win32_Process | Where-Object {
    (
        $_.Name -eq "python.exe" -and (
            $_.CommandLine -like "*jarvis_ai.supervisor*" -or
            $_.CommandLine -like "*jarvis_ai.listen*" -or
            $_.CommandLine -like "*jarvis_ai.webserver*"
        )
    ) -or (
        $_.Name -eq "cmd.exe" -and $_.CommandLine -like "*Start Leha Production.bat*"
    )
}
if (-not $targets) {
    Write-Host "Leha is not running."
    exit 0
}
foreach ($p in $targets) {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
Write-Host "Stopped Leha processes: $($targets.ProcessId -join ', ')"
