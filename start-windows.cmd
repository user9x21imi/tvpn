@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 goto failed
  .venv\Scripts\python.exe -m pip install -r requirements-windows.txt
  if errorlevel 1 goto failed
)
.venv\Scripts\python.exe launch.py %*
if errorlevel 1 goto failed
exit /b 0
:failed
pause
exit /b 1
