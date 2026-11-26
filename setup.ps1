# Windows one-shot setup: venv + dependencies + .env template
$ErrorActionPreference = "Stop"
if (-not (Test-Path venv)) { python -m venv venv }
& .\venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created .env - open it and fill in your values." }
Write-Host "`nNext:`n  .\venv\Scripts\python.exe bridge\run_daily.py --demo --dry-run   (works with no credentials)`n  .\venv\Scripts\python.exe bridge\ollama_agent.py --check`n  .\venv\Scripts\python.exe bridge\ollama_agent.py --all`n  .\venv\Scripts\python.exe bridge\run_daily.py"
