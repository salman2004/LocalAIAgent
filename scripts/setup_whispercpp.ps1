<#
    Downloads the latest whisper.cpp CPU+BLAS Windows x64 release build and
    extracts it to .\vendor\whisper.cpp\ (whisper-server.exe lives there).

    Deliberately NOT using one of the unofficial single-maintainer "Vulkan
    Windows build" forks floating around online - no official Vulkan
    Windows release exists yet (upstream issue #3673 is still open), and
    those forks are one-release, no-CI side projects. Not worth the trust
    tradeoff for transcribing a short push-to-talk clip, which a modern
    CPU handles fine anyway.
#>

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$VendorDir = Join-Path $RepoRoot "vendor\whisper.cpp"
$TmpZip = Join-Path $env:TEMP "whispercpp-blas.zip"

Write-Host "Querying latest whisper.cpp release..."
$release = Invoke-RestMethod -Uri "https://api.github.com/repos/ggml-org/whisper.cpp/releases/latest"

$asset = $release.assets | Where-Object { $_.name -eq "whisper-blas-bin-x64.zip" } | Select-Object -First 1
if (-not $asset) {
    throw "Could not find whisper-blas-bin-x64.zip in release $($release.tag_name)."
}

Write-Host "Downloading $($asset.name) ($($release.tag_name))..."
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $TmpZip

if (Test-Path $VendorDir) {
    Remove-Item -Recurse -Force $VendorDir
}
New-Item -ItemType Directory -Force -Path $VendorDir | Out-Null

Write-Host "Extracting to $VendorDir ..."
Expand-Archive -Path $TmpZip -DestinationPath $VendorDir -Force
Remove-Item $TmpZip

Write-Host "`nDone. whisper-server.exe should be at:"
Get-ChildItem -Recurse -Filter "whisper-server.exe" -Path $VendorDir | ForEach-Object { Write-Host "  $($_.FullName)" }
