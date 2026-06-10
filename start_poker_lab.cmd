@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_poker_lab.ps1" %*
if errorlevel 1 pause
