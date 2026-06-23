# Anvil — start the app locally. Then open http://localhost:8080
# Loads .env (secret key etc.), then serves the built SPA + API on port 8080.
Set-Location $PSScriptRoot
if (Test-Path .env) {
  Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]*)=(.*)$') { Set-Item "env:$($matches[1].Trim())" $matches[2].Trim() }
  }
}
Write-Host "Anvil starting on http://localhost:8080  (Ctrl+C to stop)" -ForegroundColor Green
.\.venv\Scripts\python.exe -m uvicorn anvil.api.app:app --host 0.0.0.0 --port 8080
