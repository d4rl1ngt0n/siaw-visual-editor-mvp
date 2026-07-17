@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.12 or newer, then run this file again.
  pause
  exit /b 1
)

if not exist .venv (
  echo Creating the local Python environment...
  py -m venv .venv
)

call .venv\Scripts\activate.bat
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
py manage.py migrate
py manage.py load_demo

echo.
echo Setup completed successfully.
echo Run run_windows.bat to open the editor.
pause
