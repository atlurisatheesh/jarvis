# Register Leha to start automatically at Windows logon (with auto-restart).
# Run once in a normal PowerShell (no admin needed for a per-user logon task):
#   powershell -ExecutionPolicy Bypass -File D:\jarvis\scripts\install_autostart.ps1
#
# Remove later with:
#   Unregister-ScheduledTask -TaskName "Leha" -Confirm:$false

$ErrorActionPreference = "Stop"
$work = "D:\jarvis"
$startScript = Join-Path $work "scripts\start_leha.ps1"

$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -File `"$startScript`"" -WorkingDirectory $work
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

try {
    Register-ScheduledTask -TaskName "Leha" -Action $action -Trigger $trigger `
        -Settings $settings -Description "Leha voice assistant (auto-restart supervisor)" -Force
    Write-Host "Leha registered to start at logon."
    Write-Host "Start now with: powershell -ExecutionPolicy Bypass -File D:\jarvis\scripts\start_leha.ps1"
    Write-Host "Remove later with: powershell -ExecutionPolicy Bypass -File D:\jarvis\scripts\uninstall_autostart.ps1"
}
catch {
    # Some Windows editions deny Scheduled Tasks to standard user accounts.
    # Use the current user's Startup folder instead; supervisor still handles
    # listener restarts and this route needs no administrator permission.
    $startup = [Environment]::GetFolderPath("Startup")
    $launcher = Join-Path $startup "Leha Assistant.vbs"
    $workEscaped = $work.Replace('"', '""')
    $startEscaped = $startScript.Replace('"', '""')
    $vbs = @"
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = "$workEscaped"
shell.Run "powershell -ExecutionPolicy Bypass -File ""$startEscaped""", 0, False
"@
    Set-Content -LiteralPath $launcher -Value $vbs -Encoding ASCII
    Write-Host "Scheduled Task access was denied. Installed per-user startup launcher: $launcher"
}
