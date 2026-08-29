<#
    Starts whisper-server.exe hosting the speech-to-text model. Reads
    model path / port from config.yaml. Run scripts/setup_whispercpp.ps1
    first, and make sure config.yaml's speech_to_text.model_path points at
    a ggml .bin file you've downloaded into .\models\.
#>

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ServerExe = Join-Path $RepoRoot "vendor\whisper.cpp\Release\whisper-server.exe"
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$PythonExe = if (Test-Path $VenvPython) { $VenvPython } else { "python" }

if (-not (Test-Path $ServerExe)) {
    throw "whisper-server.exe not found at $ServerExe. Run install.ps1 (or scripts\setup_whispercpp.ps1) first."
}

$cfgJson = & $PythonExe (Join-Path $PSScriptRoot "_read_config.py") | ConvertFrom-Json

if (-not (Test-Path $cfgJson.speech_to_text_model_path)) {
    throw "Model file not found: $($cfgJson.speech_to_text_model_path). Download it and/or fix speech_to_text.model_path in config.yaml."
}

$uri = [System.Uri]$cfgJson.speech_to_text_base_url

Write-Host "Starting speech-to-text server on $($uri.Host):$($uri.Port) ..."
& $ServerExe `
    -m $cfgJson.speech_to_text_model_path `
    --host $uri.Host `
    --port $uri.Port
