@echo off
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\install_production.ps1"
exit /b %ERRORLEVEL%
