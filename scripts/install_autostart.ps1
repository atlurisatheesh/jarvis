# Register Leha to start automatically at Windows logon (with auto-restart).
# Run once in a normal PowerShell (no admin needed for a per-user logon task):
#   powershell -ExecutionPolicy Bypass -File D:\jarvis\scripts\install_autostart.ps1
#
# Remove later with:
#   Unregister-ScheduledTask -TaskName "Leha" -Confirm:$false

$ErrorActionPreference = "Stop"
$python = (Get-Command python).Source
$work = "D:\jarvis"

$action  = New-ScheduledTaskAction -Execute $python `
    -Argument "-u -m jarvis_ai.supervisor" -WorkingDirectory $work
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

try {
    Register-ScheduledTask -TaskName "Leha" -Action $action -Trigger $trigger `
        -Settings $settings -Description "Leha voice assistant (auto-restart supervisor)" -Force
    Write-Host "Leha registered to start at logon. Start now with: Start-ScheduledTask -TaskName Leha"
}
catch {
    # Some Windows editions deny Scheduled Tasks to standard user accounts.
    # Use the current user's Startup folder instead; supervisor still handles
    # listener restarts and this route needs no administrator permission.
    $startup = [Environment]::GetFolderPath("Startup")
    $launcher = Join-Path $startup "Leha Assistant.vbs"
    $pythonEscaped = $python.Replace('"', '""')
    $workEscaped = $work.Replace('"', '""')
    $vbs = @"
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = "$workEscaped"
shell.Run """$pythonEscaped"" -u -m jarvis_ai.supervisor", 0, False
"@
    Set-Content -LiteralPath $launcher -Value $vbs -Encoding ASCII
    Write-Host "Scheduled Task access was denied. Installed per-user startup launcher: $launcher"
}
