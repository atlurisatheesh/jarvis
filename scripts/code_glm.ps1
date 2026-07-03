# Launch the NVIDIA GLM coding assistant.
# Requires D:\jarvis\.nvidia_key or NVIDIA_API_KEY.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
python "$Root\tools\code_glm.py" @args
