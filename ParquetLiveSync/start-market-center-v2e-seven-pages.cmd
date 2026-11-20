@echo off
setlocal
cd /d "%~dp0"
set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERROR] Python virtual environment not found: %PY%
  pause
  exit /b 2
)
echo [V2E] Seven-page selected layout on latest V2D2C read-only backend.
echo [V2E] QMT connection check is user-initiated only; no downloads, repairs, or scheduled task changes.
echo [V2E] For real local status, provide --state-module with the canonical ParquetLiveSync path.
"%PY%" -u -B "%~dp0market_center_v2e_selected_ui.py" %*
if errorlevel 1 (
  echo [ERROR] Market Center V2E visual preview failed.
  pause
  exit /b 1
)
exit /b 0
