# Anvil one-command launcher.
# Always runs from THIS folder so every data path (instruments / closes / stores) is consistent,
# then starts the whole product (REST API + PWA + live cockpit) in one process.
# Usage:  right-click → "Run with PowerShell"   OR   .\run-anvil.ps1   (pass extra flags, e.g. --port 8011)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Error "venv not found at $py — create it first."; exit 1 }
Write-Host "Anvil launching from $PSScriptRoot ..." -ForegroundColor Cyan
Write-Host "Tip: if the header shows DEMO, run '.\.venv\Scripts\python.exe -m anvil.cli auth upstox' once, then relaunch." -ForegroundColor DarkGray
& $py -m anvil.cli go-live @args
