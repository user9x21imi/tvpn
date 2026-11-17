@echo off
setlocal
set "TVPN_INSTALLER=%TEMP%\Install-TVPN-%RANDOM%.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing 'https://raw.githubusercontent.com/user9x21imi/tvpn/main/Install-TVPN-Windows.ps1' -OutFile $env:TVPN_INSTALLER"
if errorlevel 1 goto failed
powershell -NoProfile -ExecutionPolicy Bypass -File "%TVPN_INSTALLER%"
set "TVPN_RESULT=%ERRORLEVEL%"
del "%TVPN_INSTALLER%" >nul 2>&1
if not "%TVPN_RESULT%"=="0" goto failed
exit /b 0
:failed
pause
exit /b 1
