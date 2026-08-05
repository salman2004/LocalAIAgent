<#
    Convenience launcher: opens the chat model server, embedding model
    server, and assistant_core each in their own background window, then
    runs the terminal UI right here in this window. Run install.ps1 first
    if you haven't.

    Close the two background windows (or Ctrl+C in each) when you're done,
    or just close this window - assistant_core and the model servers keep
    running until you stop them.
#>

$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "No .venv found. Run install.ps1 first."
}

Write-Host "Starting chat model server, embedding server, and assistant core..."

Start-Process powershell -ArgumentList "-NoExit", "-Command", "& '$RepoRoot\scripts\start_llm_server.ps1'"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "& '$RepoRoot\scripts\start_embedding_server.ps1'"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "& '$VenvPython' -m assistant_core.main"

Write-Host "Waiting a few seconds for assistant_core to come up..."
Start-Sleep -Seconds 5

Write-Host "Launching the terminal UI. The chat/embedding models may still be"
Write-Host "loading into VRAM in their windows - if your first message errors,"
Write-Host "give them a few more seconds and try again.`n"

& $VenvPython -m cli.tui
