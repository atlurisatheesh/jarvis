<#
.SYNOPSIS
  Installs custom-trained "Leha" openWakeWord models after downloading them
  from the Google Colab training notebook.

.DESCRIPTION
  Run this after downloading leha.onnx and hey_leha.onnx from the Colab
  notebook (kaggle_wake_job/train_leha_oww.ipynb).

  This script:
    1. Looks for the .onnx files in common download locations
    2. Copies them into jarvis_ai\voices\
    3. Smoke-tests that openWakeWord can load them
    4. Reports which wake engine is active

  It does NOT edit config.py — the config already points to these paths.
  Missing files are skipped safely, so OWW falls back to "hey_jarvis" until
  both models are present.

.EXAMPLE
  .\scripts\install_leha_wake_model.ps1
  .\scripts\install_leha_wake_model.ps1 -DownloadDir "$env:USERPROFILE\Downloads"
#>
param(
    [string]$DownloadDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$VoicesDir = Join-Path $Root "jarvis_ai\voices"

# --- Search locations for downloaded .onnx files ---
if (-not $DownloadDir) {
    $DownloadDir = Join-Path $env:USERPROFILE "Downloads"
}
$SearchDirs = @(
    $DownloadDir,
    (Get-Location).Path,
    $Root,
    $VoicesDir
) | Select-Object -Unique

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Leha Wake Model Installer" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Target directory: $VoicesDir"
Write-Host ""

# --- Ensure voices dir exists ---
if (-not (Test-Path $VoicesDir)) {
    New-Item -ItemType Directory -Path $VoicesDir -Force | Out-Null
    Write-Host "Created voices directory." -ForegroundColor Yellow
}

# --- Find and copy each model ---
$Models = @("leha.onnx", "hey_leha.onnx")
$Found = @{}

foreach ($model in $Models) {
    $target = Join-Path $VoicesDir $model

    # Already installed?
    if (Test-Path $target) {
        $sizeKB = [math]::Round((Get-Item $target).Length / 1KB)
        Write-Host "[skip] $model already in voices\ ($sizeKB KB)" -ForegroundColor Green
        $Found[$model] = $target
        continue
    }

    # Search for it
    $src = $null
    foreach ($dir in $SearchDirs) {
        if (Test-Path $dir) {
            $candidate = Join-Path $dir $model
            if (Test-Path $candidate) {
                $src = $candidate
                break
            }
        }
    }

    if ($src) {
        Copy-Item -Path $src -Destination $target -Force
        $sizeKB = [math]::Round((Get-Item $target).Length / 1KB)
        Write-Host "[ok]   Installed $model ($sizeKB KB)" -ForegroundColor Green
        $Found[$model] = $target
    } else {
        Write-Host "[miss] $model not found in Downloads, project root, or voices\" -ForegroundColor Yellow
        Write-Host "       Download it from the Colab notebook first." -ForegroundColor DarkGray
    }
}

Write-Host ""

# --- Smoke test: load whatever models are present ---
if ($Found.Count -eq 0) {
    Write-Host "No custom models found. openWakeWord will use the built-in" -ForegroundColor Yellow
    Write-Host "'hey_jarvis' fallback. Train models with the Colab notebook:" -ForegroundColor Yellow
    Write-Host "  kaggle_wake_job\train_leha_oww.md"
    exit 0
}

Write-Host "Smoke-testing model load..." -ForegroundColor Cyan
$foundPaths = $Found.Values | ForEach-Object { $_ }
$foundJson = $foundPaths -join "','"
$testCode = @"
import sys
sys.path.insert(0, '$($Root -replace '\\','\\')')
try:
    from openwakeword.model import Model
    import numpy as np
    models = ['$foundJson'.split(',') if '$foundJson' else []]
    m = Model(wakeword_models=models, inference_framework='onnx')
    silence = np.zeros(1280, dtype=np.int16)
    for _ in range(13):
        scores = m.predict(silence)
    print('LOADED:', list(scores.keys()))
    print('OK')
except Exception as e:
    print('ERROR:', repr(e))
    sys.exit(1)
"@

try {
    $output = python -c $testCode 2>&1
    if ($output -match "OK") {
        Write-Host "  Models load and predict successfully." -ForegroundColor Green
        Write-Host "  $output" -ForegroundColor DarkGray
    } else {
        Write-Host "  Smoke test failed:" -ForegroundColor Red
        Write-Host "  $output" -ForegroundColor DarkGray
        Write-Host "  The files may be corrupted. Re-download from Colab." -ForegroundColor Yellow
        exit 1
    }
} catch {
    Write-Host "  Could not run smoke test: $_" -ForegroundColor Red
    Write-Host "  Make sure Python and openwakeword are on PATH." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Status" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
if ($Found.Count -eq 2) {
    Write-Host "Both custom models installed. Say 'Leha' or 'Hey Leha' to wake." -ForegroundColor Green
} elseif ($Found.Count -eq 1) {
    $missing = ($Models | Where-Object { $_ -notin $Found.Keys }) -join ", "
    Write-Host "1 of 2 models installed. Missing: $missing" -ForegroundColor Yellow
    Write-Host "openWakeWord will use the installed model + 'hey_jarvis' fallback." -ForegroundColor Yellow
}
Write-Host ""
Write-Host "RESTART Leha for the new models to take effect:" -ForegroundColor Cyan
Write-Host "  .\scripts\restart_leha.ps1" -ForegroundColor White
Write-Host ""
Write-Host "To revert to 'hey_jarvis' only:" -ForegroundColor DarkGray
Write-Host "  Delete jarvis_ai\voices\leha.onnx and hey_leha.onnx" -ForegroundColor DarkGray
