<#
    Starts llama-server.exe hosting the chat/coding model on the GPU
    (Vulkan, all layers offloaded). Reads model path / port from
    config.yaml. Run scripts/setup_llamacpp.ps1 first, and make sure
    config.yaml's llm.model_path points at a .gguf file you've downloaded
    into .\models\.
#>

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ServerExe = Join-Path $RepoRoot "vendor\llama.cpp\llama-server.exe"
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$PythonExe = if (Test-Path $VenvPython) { $VenvPython } else { "python" }

if (-not (Test-Path $ServerExe)) {
    throw "llama-server.exe not found at $ServerExe. Run install.ps1 (or scripts\setup_llamacpp.ps1) first."
}

$cfgJson = & $PythonExe (Join-Path $PSScriptRoot "_read_config.py") | ConvertFrom-Json

if (-not (Test-Path $cfgJson.llm_model_path)) {
    throw "Model file not found: $($cfgJson.llm_model_path). Download it and/or fix llm.model_path in config.yaml."
}

$uri = [System.Uri]$cfgJson.llm_base_url

Write-Host "Starting chat model server on $($uri.Host):$($uri.Port) ..."
& $ServerExe `
    -m $cfgJson.llm_model_path `
    --host $uri.Host `
    --port $uri.Port `
    -c $cfgJson.llm_context_size `
    -ngl 999 `
    --jinja `
    --reasoning-format deepseek
