<#
    Downloads the latest llama.cpp Vulkan Windows x64 release build and
    extracts it to .\vendor\llama.cpp\ (llama-server.exe lives there).

    Vulkan is the recommended backend for an AMD/RDNA4 card on Windows:
    it doesn't require the ROCm/HIP SDK, and RDNA4 ROCm support is still
    new and Linux-focused. If you want to experiment with the HIP build
    later for a speed comparison, llama.cpp also ships
    "llama-<tag>-bin-win-hip-radeon-x64.zip" in the same release.
#>

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$VendorDir = Join-Path $RepoRoot "vendor\llama.cpp"
$TmpZip = Join-Path $env:TEMP "llamacpp-vulkan.zip"

Write-Host "Querying latest llama.cpp release..."
$release = Invoke-RestMethod -Uri "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"

$asset = $release.assets | Where-Object { $_.name -like "*bin-win-vulkan-x64.zip" } | Select-Object -First 1
if (-not $asset) {
    throw "Could not find a win-vulkan-x64 asset in release $($release.tag_name)."
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

Write-Host "`nDone. llama-server.exe should be at:"
Get-ChildItem -Recurse -Filter "llama-server.exe" -Path $VendorDir | ForEach-Object { Write-Host "  $($_.FullName)" }
