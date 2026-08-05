<#
    Starts a second llama-server.exe instance hosting the embedding model,
    used by the RAG store to embed documents and queries. Runs alongside
    start_llm_server.ps1 on a different port (see config.yaml).
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

if (-not (Test-Path $cfgJson.embeddings_model_path)) {
    throw "Model file not found: $($cfgJson.embeddings_model_path). Download it and/or fix embeddings.model_path in config.yaml."
}

$uri = [System.Uri]$cfgJson.embeddings_base_url

Write-Host "Starting embedding model server on $($uri.Host):$($uri.Port) ..."
& $ServerExe `
    -m $cfgJson.embeddings_model_path `
    --host $uri.Host `
    --port $uri.Port `
    -c $cfgJson.embeddings_context_size `
    -ngl 999 `
    --embedding
