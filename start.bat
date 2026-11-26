@echo off
REM One-click start (Windows): sets up Python env on first run, then launches the autonomous agency.
cd /d "%~dp0"
if not exist venv ( python -m venv venv )
venv\Scripts\python.exe -m pip install -q -r requirements.txt
REM LiteLLM is optional (unified model interface). If it fails to install the app still works.
venv\Scripts\python.exe -m pip install -q -r requirements-litellm.txt || echo LiteLLM skipped, using built-in HTTP path.
if not exist .env ( copy .env.example .env >nul & echo Created .env - fill in SMTP/SHEET values for e-mail + Google Sheet. )
venv\Scripts\python.exe app.py
pause
