@echo off
REM Daily job for Windows Task Scheduler: PM scans the 7 employees -> Google Sheet -> e-mail.
cd /d "%~dp0"
venv\Scripts\python.exe bridge\run_daily.py
