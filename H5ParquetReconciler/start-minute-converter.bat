@echo off
setlocal
cd /d "%~dp0\.."
if not exist ".venv\Scripts\pythonw.exe" (
  echo Python virtual environment pythonw.exe was not found.
  echo Install or restore .venv first, then start again.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "H5ParquetReconciler\tools\minute-private-parquet-gui.py"
if errorlevel 1 (
  echo GUI could not be launched. Check virtual environment.
  pause
  exit /b 1
)
endlocal
