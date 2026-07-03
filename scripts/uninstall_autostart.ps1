$ErrorActionPreference = "Continue"
$taskName = "Leha"
try {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop
    Write-Host "Removed scheduled task: $taskName"
} catch {
    Write-Host "Scheduled task not present or could not be removed."
}
$startup = [Environment]::GetFolderPath("Startup")
$launcher = Join-Path $startup "Leha Assistant.vbs"
if (Test-Path -LiteralPath $launcher) {
    Remove-Item -LiteralPath $launcher -Force
    Write-Host "Removed startup launcher: $launcher"
}
