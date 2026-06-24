# Leha unified test runner (Phase 9).
# Runs every phase suite plus the safe end-to-end suites and prints a
# phase-by-phase pass/fail summary. Power/destructive actions never run here
# (the safe suites mock all skill execution).
#
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\run_tests.ps1

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$suites = @(
    "test_phase0.py",
    "test_phase1.py",
    "test_phase2.py",
    "test_phase3.py",
    "test_phase4.py",
    "test_phase5.py",
    "test_phase6.py",
    "test_phase7.py",
    "test_phase8.py",
    "test_phase9.py",
    "test_e2e_safe.py",
    "test_mobile_safe.py",
    "test_wake_model.py"
)

$version = (Get-Content "jarvis_ai\VERSION" -ErrorAction SilentlyContinue | Select-Object -First 1)
Write-Host ""
Write-Host "Leha test runner - version $version" -ForegroundColor Cyan
Write-Host ("=" * 50)

$results = @()
$anyFail = $false

foreach ($suite in $suites) {
    if (-not (Test-Path $suite)) {
        $results += [pscustomobject]@{ Suite = $suite; Status = "MISSING" }
        continue
    }
    python -m pytest $suite -q 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $results += [pscustomobject]@{ Suite = $suite; Status = "PASS" }
    } else {
        $results += [pscustomobject]@{ Suite = $suite; Status = "FAIL" }
        $anyFail = $true
    }
}

Write-Host ""
Write-Host "Summary" -ForegroundColor Cyan
Write-Host ("-" * 50)
foreach ($r in $results) {
    $color = switch ($r.Status) { "PASS" { "Green" } "FAIL" { "Red" } default { "Yellow" } }
    Write-Host ("{0,-22} {1}" -f $r.Suite, $r.Status) -ForegroundColor $color
}
Write-Host ("-" * 50)

if ($anyFail) {
    Write-Host "RESULT: FAIL" -ForegroundColor Red
    exit 1
} else {
    Write-Host "RESULT: ALL GREEN" -ForegroundColor Green
    exit 0
}
