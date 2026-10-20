@echo off
rem ============================================================
rem  One-click connect robot to Wi-Fi (Windows version)
rem  Double click THIS file. Real logic: robot-wifi.ps1 + robot-wifi-remote.sh
rem  Nothing is installed or changed on the robot side.
rem  NOTE: keep this .cmd ASCII-only (cmd.exe mis-reads CJK after chcp).
rem ============================================================
chcp 65001 >nul 2>&1
setlocal
cd /d "%~dp0"

where powershell >nul 2>&1
if errorlevel 1 (
  echo [FAILED] powershell not found. Please use Windows 10 / 11.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0robot-wifi.ps1" %*
exit /b %ERRORLEVEL%
