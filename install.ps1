<#
    One-shot setup for the whole project: Python venv + dependencies,
    llama.cpp (Vulkan build), and both default GGUF models.

    Run it with:
        powershell -ExecutionPolicy Bypass -File .\install.ps1

    Safe to re-run - anything already downloaded/installed is skipped,
    so if a step fails partway (e.g. network drop mid-download) you can
    just run it again.
#>

$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot

function Test-CommandExists($name) {
    return $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

function Get-FileRobust($Url, $OutFile, $MinBytes) {
    if ((Test-Path $OutFile) -and (Get-Item $OutFile).Length -ge $MinBytes) {
        Write-Host "  already present: $(Split-Path $OutFile -Leaf)"
        return
    }

    Write-Host "  downloading $(Split-Path $OutFile -Leaf) ..."
    New-Item -ItemType Directory -Force -Path (Split-Path $OutFile) | Out-Null

    if (Test-CommandExists "Start-BitsTransfer") {
        Start-BitsTransfer -Source $Url -Destination $OutFile -DisplayName (Split-Path $OutFile -Leaf)
    }
    else {
        $prevProgressPreference = $ProgressPreference
        $ProgressPreference = "SilentlyContinue"  # Invoke-WebRequest is drastically slower with the progress bar on
        try {
            Invoke-WebRequest -Uri $Url -OutFile $OutFile
        }
        finally {
            $ProgressPreference = $prevProgressPreference
        }
    }

    if ((Get-Item $OutFile).Length -lt $MinBytes) {
        throw "Downloaded file looks too small: $OutFile ($((Get-Item $OutFile).Length) bytes). The download likely failed - re-run this script to retry."
    }
}

Write-Host "== Local Assistant setup ==" -ForegroundColor Cyan

# ---- 1. Python ------------------------------------------------------------

Write-Host "`n[1/5] Checking for Python..."

if (-not (Test-CommandExists "python")) {
    if (Test-CommandExists "winget") {
        Write-Host "  Python not found. Installing via winget..."
        winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements

        # Pick up the newly-installed PATH entry without needing a new shell.
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                    [System.Environment]::GetEnvironmentVariable("Path", "User")

        if (-not (Test-CommandExists "python")) {
            throw "Python was installed but isn't on PATH in this session. Close this terminal, open a new one, and re-run install.ps1."
        }
    }
    else {
        throw "Python 3.11+ is required and winget isn't available to auto-install it. Install it from https://www.python.org/downloads/ (check 'Add python.exe to PATH') and re-run this script."
    }
}

$pyVersionOutput = & python --version 2>&1
if ($pyVersionOutput -notmatch "Python 3") {
    throw "'python' didn't report a Python 3.x version (got: '$pyVersionOutput'). If you're on Windows 11, this can happen when the Microsoft Store's python.exe alias shadows a real install - check Settings > Apps > Advanced app settings > App execution aliases and disable the Python ones, then re-run this script."
}
Write-Host "  found $pyVersionOutput"

# ---- 2. Virtual environment + dependencies --------------------------------

Write-Host "`n[2/5] Setting up the Python virtual environment..."

$VenvDir = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "  creating .venv ..."
    python -m venv $VenvDir
}
else {
    Write-Host "  .venv already exists"
}

Write-Host "  installing dependencies (this can take a minute)..."
& $VenvPython -m pip install --upgrade pip --quiet
& $VenvPython -m pip install -r (Join-Path $RepoRoot "requirements.txt") --quiet

# ---- 3. llama.cpp (Vulkan build) ------------------------------------------

Write-Host "`n[3/5] Setting up llama.cpp (Vulkan build)..."
& (Join-Path $RepoRoot "scripts\setup_llamacpp.ps1")

# ---- 4. whisper.cpp (speech-to-text) ---------------------------------------

Write-Host "`n[4/6] Setting up whisper.cpp (CPU/BLAS build)..."
& (Join-Path $RepoRoot "scripts\setup_whispercpp.ps1")

# ---- 5. Piper (text-to-speech) ---------------------------------------------

Write-Host "`n[5/6] Setting up Piper (text-to-speech)..."
& (Join-Path $RepoRoot "scripts\setup_piper.ps1")

# ---- 6. Models --------------------------------------------------------------

Write-Host "`n[6/6] Downloading models (the chat model is ~10GB - this is the slow part)..."
$ModelsDir = Join-Path $RepoRoot "models"

Get-FileRobust `
    -Url "https://huggingface.co/bartowski/Qwen_Qwen3-14B-GGUF/resolve/main/Qwen_Qwen3-14B-Q5_K_M.gguf?download=true" `
    -OutFile (Join-Path $ModelsDir "qwen3-14b-q5_k_m.gguf") `
    -MinBytes 9500000000

Get-FileRobust `
    -Url "https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.Q8_0.gguf?download=true" `
    -OutFile (Join-Path $ModelsDir "nomic-embed-text-v1.5.Q8_0.gguf") `
    -MinBytes 100000000

Get-FileRobust `
    -Url "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin?download=true" `
    -OutFile (Join-Path $ModelsDir "ggml-small.en.bin") `
    -MinBytes 480000000

Get-FileRobust `
    -Url "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx?download=true" `
    -OutFile (Join-Path $ModelsDir "en_US-lessac-medium.onnx") `
    -MinBytes 60000000

Get-FileRobust `
    -Url "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json?download=true" `
    -OutFile (Join-Path $ModelsDir "en_US-lessac-medium.onnx.json") `
    -MinBytes 1000

Write-Host "`n== Setup complete ==" -ForegroundColor Green
Write-Host "`nRun .\start_all.ps1 to launch everything and open the terminal UI,"
Write-Host "or start the pieces by hand - see README.md."
