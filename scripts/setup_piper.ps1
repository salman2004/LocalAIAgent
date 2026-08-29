<#
    Downloads the archived rhasspy/piper Windows x64 build and extracts it
    to .\vendor\piper\ (piper.exe ends up at .\vendor\piper\piper\piper.exe -
    the zip itself has a top-level "piper/" folder).

    The original rhasspy/piper repo is archived (development moved to
    OHF-Voice/piper1-gpl, a pip package with no standalone Windows exe) -
    this pinned release (2023.11.14-2, MIT-licensed) is the last, and
    only, standalone Windows binary that fits this project's "vendor a
    native exe" pattern, so it's fetched from a fixed tag rather than
    "latest" (there is no newer Windows release to query for).

    Piper has no persistent server mode - it's invoked as a fresh
    subprocess per utterance (text in via stdin, WAV out), unlike
    llama-server.exe/whisper-server.exe, so there's no matching
    start_piper.ps1.
#>

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$VendorDir = Join-Path $RepoRoot "vendor\piper"
$TmpZip = Join-Path $env:TEMP "piper-windows.zip"
$Url = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip"

Write-Host "Downloading piper_windows_amd64.zip (2023.11.14-2)..."
Invoke-WebRequest -Uri $Url -OutFile $TmpZip

if (Test-Path $VendorDir) {
    Remove-Item -Recurse -Force $VendorDir
}
New-Item -ItemType Directory -Force -Path $VendorDir | Out-Null

Write-Host "Extracting to $VendorDir ..."
Expand-Archive -Path $TmpZip -DestinationPath $VendorDir -Force
Remove-Item $TmpZip

Write-Host "`nDone. piper.exe should be at:"
Get-ChildItem -Recurse -Filter "piper.exe" -Path $VendorDir | ForEach-Object { Write-Host "  $($_.FullName)" }
