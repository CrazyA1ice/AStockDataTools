@echo off
setlocal
cd /d "%~dp0"
set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERROR] Project Python virtual environment missing: %PY%
  pause
  exit /b 2
)
echo [V2-A] Read-only market-center preview. No updates, downloads or task registration.
"%PY%" -u -B "%~dp0market_center_v2_preview.py"
if errorlevel 1 (
  echo [ERROR] Market center V2 preview exited with error.
  pause
  exit /b 1
)
exit /b 0
