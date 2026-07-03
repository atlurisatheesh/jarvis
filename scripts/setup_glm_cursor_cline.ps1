# Configure NVIDIA GLM-5.2 for Cursor chat (Option B) and Cline (Option C).
# API key is read from D:\jarvis\.nvidia_key (never printed).
param(
    [switch]$SkipApiTest,
    [switch]$SkipOpenCursor,
    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$KeyFile = Join-Path $Root ".nvidia_key"
$BaseUrl = "https://integrate.api.nvidia.com/v1"
$Model = "z-ai/glm-5.2"

function Write-Step([string]$Number, [string]$Text) {
    Write-Host ""
    Write-Host "[$Number] $Text" -ForegroundColor Cyan
}

function Set-ClipboardText([string]$Text) {
    Set-Clipboard -Value $Text
}

function Wait-Step([string]$Prompt) {
    if ($NonInteractive) { return }
    Read-Host $Prompt | Out-Null
}

if (-not (Test-Path $KeyFile)) {
    Write-Host "Missing $KeyFile" -ForegroundColor Red
    Write-Host "Create it with your nvapi-... key on one line, then rerun:"
    Write-Host "  .\scripts\setup_glm_cursor_cline.ps1"
    exit 1
}

$ApiKey = (Get-Content $KeyFile -Raw).Trim()
if (-not $ApiKey) {
    Write-Host ".nvidia_key is empty." -ForegroundColor Red
    exit 1
}

Write-Host "NVIDIA GLM coding setup" -ForegroundColor Green
Write-Host "Model: $Model"
Write-Host "Base URL: $BaseUrl"

if (-not $SkipApiTest) {
    Write-Step "0" "Testing NVIDIA API..."
    $testScript = @"
import json, sys, requests
key = open(r'$KeyFile', encoding='utf-8').read().strip()
r = requests.post(
    '$BaseUrl/chat/completions',
    headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
    json={'model': '$Model', 'messages': [{'role': 'user', 'content': 'Reply OK only.'}], 'max_tokens': 8},
    timeout=60,
)
if r.status_code == 429:
    print('RATE_LIMIT')
    sys.exit(0)
if not r.ok:
    print(f'HTTP {r.status_code}: {r.text[:200]}')
    sys.exit(1)
print('OK')
"@
    $result = python -c $testScript 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host $result -ForegroundColor Red
        exit 1
    }
    if ($result -match "RATE_LIMIT") {
        Write-Host "API key valid but rate-limited (429). Continuing setup anyway." -ForegroundColor Yellow
    } else {
        Write-Host "API test passed." -ForegroundColor Green
    }
}

Write-Step "1" "Ensuring Cline extension is installed..."
$extList = & cursor --list-extensions 2>&1 | Out-String
$cline = $extList | Select-String "saoudrizwan.claude-dev"
if (-not $cline) {
    & cursor --install-extension saoudrizwan.claude-dev 2>&1 | Out-Host
} else {
    Write-Host "Cline already installed."
}

if (-not $SkipOpenCursor) {
    Write-Step "2" "Opening Cursor on D:\jarvis..."
    Start-Process "cursor" -ArgumentList "`"$Root`""
    Start-Sleep -Seconds 3
}

Write-Host ""
Write-Host "======== OPTION B: Cursor Chat ========" -ForegroundColor Yellow
Write-Step "B1" "In Cursor: press Ctrl+Shift+J (Cursor Settings) -> Models"
Write-Step "B2" "Enable OpenAI API key -> paste key from clipboard -> Verify"
Set-ClipboardText $ApiKey
Write-Host "API key copied to clipboard." -ForegroundColor Green
Wait-Step "Press Enter after you pasted and verified the OpenAI API key"

Write-Step "B3" "Enable Override OpenAI Base URL -> paste base URL -> Save"
Set-ClipboardText $BaseUrl
Write-Host "Base URL copied to clipboard." -ForegroundColor Green
Wait-Step "Press Enter after you saved the base URL"

Write-Step "B4" "Click + Add model -> paste model id -> enable it in chat picker"
Set-ClipboardText $Model
Write-Host "Model id copied to clipboard." -ForegroundColor Green
Wait-Step "Press Enter after you added the model"

Write-Host ""
Write-Host "======== OPTION C: Cline Agent ========" -ForegroundColor Yellow
Write-Step "C1" "Click the Cline icon in the left sidebar (robot icon)"
Write-Step "C2" "Click the gear icon in the Cline panel -> API Provider: OpenAI Compatible"
Write-Step "C3" "Paste Base URL, API Key, and Model from clipboard in order"

Set-ClipboardText $BaseUrl
Write-Host "Base URL copied." -ForegroundColor Green
Wait-Step "Press Enter after Base URL is pasted in Cline"

Set-ClipboardText $ApiKey
Write-Host "API key copied." -ForegroundColor Green
Wait-Step "Press Enter after API key is pasted in Cline"

Set-ClipboardText $Model
Write-Host "Model id copied." -ForegroundColor Green
Wait-Step "Press Enter after model id is pasted in Cline"

Write-Step "C4" "Click Verify/Save in Cline, then start a task in Act mode"
Write-Host ""
Write-Host "Done. Use Ctrl+L chat with z-ai/glm-5.2 (Cursor) or Cline sidebar for full coding agent." -ForegroundColor Green
