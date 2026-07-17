@echo off
setlocal
cd /d "%~dp0"

if not exist .venv\Scripts\activate.bat (
  echo The editor has not been set up yet.
  echo Run setup_windows.bat first.
  pause
  exit /b 1
)

call .venv\Scripts\activate.bat
start "" http://127.0.0.1:8000/
py manage.py runserver 127.0.0.1:8000
