param(
    [string]$Kernel = "satheeshatluri/leha-wake-oww-training",
    [int]$PollSeconds = 60,
    [int]$MaxMinutes = 240,
    [string]$OutputDir = "kaggle_wake_job\final_outputs",
    [string]$ExpectedModelsCsv = "leha.onnx,hey_leha.onnx",
    [string]$PositiveEvalDir = "processed\leha_wake_dataset_guided_20260708_222645\heldout\positive",
    [string]$NegativeEvalDir = "processed\leha_wake_dataset_guided_20260708_222645\heldout\negative"
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$LogDir = Join-Path $Root "logs"
$OutDir = Join-Path $Root $OutputDir
$VoicesDir = Join-Path $Root "jarvis_ai\voices"
$ConfigPath = Join-Path $Root "jarvis_ai\config.py"
$Log = Join-Path $LogDir "kaggle_wake_install_watch.log"
$ExpectedModels = @($ExpectedModelsCsv.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$CandidateModels = @{}

New-Item -ItemType Directory -Path $LogDir,$OutDir,$VoicesDir -Force | Out-Null

function Write-WatchLog([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date).ToString("s"), $Message
    Add-Content -Path $Log -Value $line -Encoding UTF8
    Write-Output $line
}

function Find-Model([string]$Name) {
    Get-ChildItem -Path $OutDir -Recurse -File -Filter $Name -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}

function Test-WakeModels {
    $rootEsc = $Root -replace "\\", "\\"
    $modelPaths = @($ExpectedModels | ForEach-Object { $CandidateModels[$_] })
    $modelsJson = $modelPaths | ConvertTo-Json -Compress
    if ($ExpectedModels.Count -eq 1) {
        $modelsJson = "[$modelsJson]"
    }
    $code = @"
import sys
sys.path.insert(0, r"$rootEsc")
from openwakeword.model import Model
import numpy as np
models = $modelsJson
m = Model(wakeword_models=models, inference_framework="onnx")
silence = np.zeros(1280, dtype=np.int16)
scores = {}
for _ in range(13):
    scores = m.predict(silence)
print("LOADED", sorted(scores.keys()))
"@
    $out = python -c $code 2>&1
    Write-WatchLog "Smoke test output: $out"
    return ($LASTEXITCODE -eq 0 -and ($out -match "LOADED"))
}

function Test-TransientKaggleError([string]$StatusText) {
    return ($StatusText -match "Traceback|ConnectionError|NameResolutionError|Failed to establish|getaddrinfo|api\.kaggle\.com|temporarily unavailable|timed out|Read timed out|Max retries exceeded")
}

function Test-WakeQuality {
    $logFiles = Get-ChildItem -Path $OutDir -Recurse -File -Include "*.log" -ErrorAction SilentlyContinue
    if ($logFiles) {
        $text = ($logFiles | ForEach-Object { Get-Content -Raw -Path $_.FullName -ErrorAction SilentlyContinue }) -join "`n"
        $recallMatches = [regex]::Matches($text, "Final Model Recall:\s*([0-9.]+)")
        $falsePositiveMatches = [regex]::Matches($text, "Final Model False Positives per Hour:\s*([0-9.]+)")
        if ($recallMatches.Count -gt 0 -and $falsePositiveMatches.Count -gt 0) {
            $recalls = @($recallMatches | ForEach-Object { [double]$_.Groups[1].Value })
            $fprs = @($falsePositiveMatches | ForEach-Object { [double]$_.Groups[1].Value })
            $minRecall = ($recalls | Measure-Object -Minimum).Minimum
            $maxFpr = ($fprs | Measure-Object -Maximum).Maximum
            Write-WatchLog ("Synthetic metrics: min recall={0:N3}, max false positives/hour={1:N3}" -f $minRecall, $maxFpr)
        }
    }

    $positive = Join-Path $Root $PositiveEvalDir
    $negative = Join-Path $Root $NegativeEvalDir
    if (-not (Test-Path $positive) -or -not (Test-Path $negative)) {
        Write-WatchLog "Owner held-out wake evaluation directories are missing."
        return $false
    }
    foreach ($model in $ExpectedModels) {
        $modelPath = $CandidateModels[$model]
        $report = Join-Path $OutDir ($model + ".owner_eval.json")
        $evalOut = & python -m jarvis_ai.wake_evaluator --model $modelPath --positive $positive --negative $negative --threshold 0.5 --report $report 2>&1
        Write-WatchLog "Owner held-out evaluation for ${model}: $evalOut"
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $report)) {
            return $false
        }
        $result = Get-Content -Raw -Path $report | ConvertFrom-Json
        if (-not $result.approved) {
            Write-WatchLog "Owner held-out quality gate rejected $model. Live model remains unchanged."
            return $false
        }
    }
    return $true
}

function Enable-OpenWakeWord {
    if (-not (Test-Path $ConfigPath)) {
        Write-WatchLog "Config file missing: $ConfigPath"
        return $false
    }
    $text = Get-Content -Raw -Path $ConfigPath
    if ($text -notmatch "OWW_ENABLED\s*=\s*True") {
        $newText = [regex]::Replace($text, "OWW_ENABLED\s*=\s*False", "OWW_ENABLED = True", 1)
        if ($newText -eq $text) {
            Write-WatchLog "Could not find OWW_ENABLED = False to update."
            return $false
        }
        Set-Content -Path $ConfigPath -Value $newText -Encoding UTF8
        Write-WatchLog "Enabled OWW in jarvis_ai\config.py"
    } else {
        Write-WatchLog "OWW already enabled in jarvis_ai\config.py"
    }
    return $true
}

function Restart-LehaSafely {
    $restart = Join-Path $Root "scripts\restart_leha.ps1"
    if (Test-Path $restart) {
        Write-WatchLog "Restarting Leha to load new wake models..."
        & powershell -ExecutionPolicy Bypass -File $restart 2>&1 | ForEach-Object { Write-WatchLog $_ }
    } else {
        Write-WatchLog "restart_leha.ps1 not found; manual restart needed."
    }
}

Write-WatchLog "Watching Kaggle kernel: $Kernel"
$deadline = (Get-Date).AddMinutes($MaxMinutes)

while ((Get-Date) -lt $deadline) {
    $statusText = (& kaggle kernels status $Kernel 2>&1 | Out-String).Trim()
    Write-WatchLog $statusText

    if (Test-TransientKaggleError $statusText) {
        Write-WatchLog "Transient Kaggle API/network error; retrying after poll interval."
        Start-Sleep -Seconds $PollSeconds
        continue
    }

    if ($statusText -match "COMPLETE|SUCCEEDED|SUCCESS") {
        Write-WatchLog "Kernel complete. Downloading final outputs to $OutDir"
        & kaggle kernels output $Kernel -p $OutDir --force 2>&1 | ForEach-Object { Write-WatchLog $_ }

        Get-ChildItem -Path $OutDir -Recurse -File -Filter "*.zip" -ErrorAction SilentlyContinue | ForEach-Object {
            $extractDir = Join-Path $_.DirectoryName ($_.BaseName + "_unzipped")
            New-Item -ItemType Directory -Path $extractDir -Force | Out-Null
            try {
                Expand-Archive -LiteralPath $_.FullName -DestinationPath $extractDir -Force
                Write-WatchLog "Expanded $($_.FullName)"
            } catch {
                Write-WatchLog "Zip expand failed for $($_.FullName): $_"
            }
        }

        $candidateCount = 0
        foreach ($model in $ExpectedModels) {
            $src = Find-Model $model
            if ($src) {
                $CandidateModels[$model] = $src.FullName
                Write-WatchLog "Staged candidate $model from $($src.FullName)"
                $candidateCount++
            } else {
                Write-WatchLog "Missing expected model: $model"
            }
        }

        if ($candidateCount -eq $ExpectedModels.Count) {
            Write-WatchLog "Expected wake model candidates found. Running smoke test."
            if (Test-WakeModels) {
                if (-not (Test-WakeQuality)) {
                    Write-WatchLog "Smoke passed, but quality gate blocked deployment. Live model remains unchanged."
                    exit 6
                }
                foreach ($model in $ExpectedModels) {
                    $dst = Join-Path $VoicesDir $model
                    Copy-Item -LiteralPath $CandidateModels[$model] -Destination $dst -Force
                    $size = (Get-Item $dst).Length
                    Write-WatchLog "Installed approved $model to $dst ($size bytes)"
                }
                if (Enable-OpenWakeWord) {
                    Restart-LehaSafely
                    Write-WatchLog "DONE: wake models installed, OWW enabled, Leha restarted."
                    exit 0
                }
                Write-WatchLog "Smoke passed, but enabling OWW failed."
                exit 4
            }
            Write-WatchLog "Smoke test failed. OWW remains disabled for safety."
            exit 5
        }

        Write-WatchLog "Kernel finished but expected models were not all present."
        exit 2
    }

    if ($statusText -match "ERROR|FAILED|CANCEL") {
        Write-WatchLog "Kernel failed or was cancelled. Not installing anything."
        exit 1
    }

    Start-Sleep -Seconds $PollSeconds
}

Write-WatchLog "Timed out after $MaxMinutes minutes."
exit 3
