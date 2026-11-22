@echo off
setlocal
rem Keep the GUI noninteractive: even PYTHONINSPECT=0 enters a Python REPL.
set "PYTHONINSPECT="
set "PYTHONSTARTUP="
cd /d "%~dp0"
set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERROR] Python virtual environment missing: %PY%
  pause
  exit /b 2
)
"%PY%" -u -B "%~dp0market_simple_desktop.py"
if errorlevel 1 (
  echo [ERROR] Dashboard ended with an error.
  pause
  exit /b 1
)
exit /b 0
