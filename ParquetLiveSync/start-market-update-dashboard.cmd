@echo off
setlocal
rem One canonical launcher: avoid maintaining two different Python GUI paths.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-gui.ps1"
if errorlevel 1 (
  echo [ERROR] Three-tab data manager failed to start.
  pause
  exit /b 1
)
exit /b 0
