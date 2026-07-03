$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$App = Join-Path $Root "android-app"
$Gradlew = Join-Path $App "gradlew.bat"

if (Test-Path -LiteralPath $Gradlew) {
    & $Gradlew -p $App assembleDebug
    exit $LASTEXITCODE
}

$Gradle = Get-Command gradle -ErrorAction SilentlyContinue
if ($Gradle) {
    & $Gradle.Source -p $App assembleDebug
    exit $LASTEXITCODE
}

$Studio = Join-Path $env:ProgramFiles "Android\Android Studio\bin\studio64.exe"
if (Test-Path -LiteralPath $Studio) {
    Write-Host "Gradle wrapper is not present. Opening Android Studio for first sync/build."
    Write-Host "After Android Studio syncs, use Build > Build APK(s), or add a Gradle wrapper."
    Start-Process -FilePath $Studio -ArgumentList "`"$App`""
    exit 0
}

Write-Host "Android SDK is present, but Gradle/Android Studio launcher was not found."
Write-Host "Install Android Studio or add Gradle wrapper files to android-app."
exit 1
